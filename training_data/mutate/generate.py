"""문서 하나를 받아 합성 pair를 뽑는다. 실제 파이프라인의 1단계다.

`run.py`는 사람이 고른 조항과 지시로 프롬프트를 깎는 도구다. 이쪽은 그렇게 깎은
프롬프트를 **문서 하나에 통째로 적용**한다. 조항을 고르고 지시를 정하는 일까지 기계가
해야 하며, 그 둘이 여기서 새로 하는 일이다.

    문서 → 조항 후보 추리기 → 조항마다 걸 수 있는 지시 정하기 → 생성 → 왕복 검증

**조항 후보 추리기.** 추출된 블록이 전부 조항인 것은 아니다. 제목(`나) 구성`), 표 조각,
목차 줄이 절반쯤 섞여 있다. 개정할 수 있으려면 서술어가 있어야 하고, 너무 짧거나 너무
길면 국소 수정이 성립하지 않는다.

**지시 정하기.** `probes/mutate_probe/`의 결론이 여기 걸린다 -- 조항에 그 변경을 넣을
자리가 없으면 모델은 가장 가까운 다른 개정을 하고, 산출의 25~30%가 지시와 어긋난다.
그래서 조항이 무엇을 담고 있는지 보고 걸 수 있는 지시만 고른다. `source_data/
block_components.py`가 이 일을 하도록 만들어졌으나 **옛 13종 어휘로 키가 잡혀 있어**
아직 못 쓴다(`README.md`). 그때까지는 여기 있는 표층 판정으로 대신한다.

**그 표층 판정이 버틸 만하다는 것이 2026-08-12에 확인됐다.** 새 교사 모델 60건에서
`수행 주체` 19/20·18/20, `기한·시점` 2/2, `제출물` 2/2가 나왔다 -- 자리 없는 지시를
걸고 있었다면 이렇게 안 나온다. **막고 있던 것은 성립 판정이 아니라 `allowed[:2]`로
앞 둘만 집는 것이었다.** 목록 맨 앞의 `수행 주체`가 두 자리를 늘 먹어 전체 코퍼스에서
59.6%가 되고 `수치·기준`은 1.5%밖에 안 나왔다.

**2026-08-13에 고쳤다.** 성립하는 지시를 전부 후보에 담고, 조항당 상한은 뽑을 때 걸며,
공급이 적은 지시부터 고르게 했다. 계획 총량(5,423건)과 조항당 상한은 그대로다.

| 대상 | 고치기 전 | 전량 5,423건 | 문서당 120건(1,461건) |
| --- | ---: | ---: | ---: |
| 수행 주체 | 59.6% | 38.6% | 25.1% |
| 절차·요건 | 25.5% | 28.1% | 29.8% |
| 제출물·기재사항 | 2.3% | 12.2% | 12.2% |
| 수치·기준 | 1.5% | 5.2% | 8.3% |
| 기한·시점 | 1.3% | 5.0% | 10.7% |

**적게 뽑을수록 고르다.** 드문 지시부터 집으므로 공급이 큰 `절차·요건`은 뒤로 밀리고,
많이 뽑을수록 남는 것이 그쪽뿐이라 다시 쏠린다.

**여기서 25% 상한을 강제하지는 않는다.** 상한이 걸리는 것은 지시가 아니라 셜록이 붙인
**산출 라벨**인데 셜록이 라벨을 갈아 끼우므로 둘이 다르다(옛 180건에서 `(절차·요건,
늘었다)` 지시 34건 중 6건만 그 라벨로 남았다). 게다가 문서 하나에 성립하는 대상이
두셋뿐인 것이 있어, 문서 단위로 25%를 강제하면 그런 문서는 계획이 거의 안 잡힌다.
**상한은 산출을 보고 합본할 때 잘라 맞춘다.**

사용:
    python3 training_data/mutate/generate.py DOC --prompt v1.1 --limit 20
    python3 training_data/mutate/generate.py DOC --prompt v1.1 --limit 200 --concurrency 16
    python3 training_data/mutate/generate.py DOC --prompt v1.1 --dry-run   # 호출 없이 계획만
    python3 training_data/mutate/generate.py DOC --prompt v1.1 --plan plans/sample60.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))
sys.path.insert(0, str(REPOSITORY_DIR / "source_data"))

import solar  # noqa: E402
import classify_diff  # noqa: E402
from extract import indexed  # noqa: E402

HERE = Path(__file__).resolve().parent
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("mutate_run", HERE / "run.py")
_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run)

# 파일 이름이 `inspect.py`이면 안 된다. 스크립트 폴더가 sys.path 맨 앞에 오므로
# 표준 라이브러리 `inspect`를 가리고, argparse가 그것을 쓰다가 터진다.
_ispec = importlib.util.spec_from_file_location("mutate_text_check", HERE / "text_check.py")
text_check = importlib.util.module_from_spec(_ispec)
_ispec.loader.exec_module(text_check)

MIN_CHARS, MAX_CHARS = 60, 400

# 조항이 무엇을 담고 있는지 보는 표층 판정. block_components.py를 새 체계로 다시 잡으면
# 그쪽으로 옮긴다. 정규식은 코퍼스에 실제로 나오는 표기에서 가져왔다.
PREDICATE = re.compile(r"(하여야 한다|해야 한다|하여야 합니다|한다\.|합니다\.|"
                       r"할 수 있다|할 수 있습니다|말한다\.|같다\.)")
ACTOR = re.compile(r"[가-힣]{2,}(?:의 장|기관|위원회|담당관|장관|처|부|사|자)"
                   r"(?:은|는|이|가|으로 하여금)\s")
ENUM = re.compile(r"(다음 각 호|각 호의|어느 하나에 해당)")
# `개`에 `(?!월)`이 붙은 이유 -- 경계가 없으면 `3개월`이 `3개`로 걸려 기한 조항이
# `수치·기준` 후보가 된다. 2026-08-13 탐침에서 `수치·기준` 지시가 다른 대상으로 읽힌
# 8건이 **예외 없이** 이것이었다(`3개` 6건, `1개` 2건). 붙이면 8건이 전부 사라진다.
# 대신 맞았던 3건도 후보에서 빠지고 성립 조항이 305개에서 183개로 준다 -- 필요량
# (1,500건의 8~12%면 120~175건)에는 남는다.
NUMBER = re.compile(r"\d+\s*(?:퍼센트|%|원|억|만원|배|개(?!월)|명|점|등급)")
DEADLINE = re.compile(r"\d+\s*(?:일|개월|년|주|시간)\s*(?:이내|이전|전까지|까지)")
SUBMIT = re.compile(r"(제출|첨부|기재|보고|통보|신고)")
# 정의 조항(`"사업단"이란 … 말한다`)과 목적 조항. 서술어가 있어 후보에 들어오지만
# **절차도 수행 주체도 없다.** 첫 실행에서 `(절차·요건, 늘었다)`가 0/5였는데 다섯 건이
# 전부 이것이었다 -- 모리아티는 정의를 넓혔고 셜록은 `적용 범위`로 읽었다. 둘 다 옳았고
# 지시가 틀렸다. 문서 앞쪽에 몰려 있어 계획의 앞자리를 차지하는 것도 문제였다:
# 후보의 7%인데 20건 계획의 25%를 가져갔다.
DEFINITION = re.compile(r'(?:”|"|“)?[^"”“]{2,30}(?:”|"|“)?\s*(?:이란|란|이라 함은|라 함은)\s')
PURPOSE = re.compile(r"제\s*\d+\s*조\s*\(\s*(?:목적|정의|적용\s*범위)\s*\)")

# 조항이 담은 것 -> 걸 수 있는 (대상, 방향). 방향 판정 기준은
# `docs/학습데이터_생성_프로세스.md` 2절이다 -- 개정 전 조항에 그 대상이 있으면
# `늘었다/줄었다/다른 값`이고, 없어야 `새로 생겼다`다. 여기서는 있는 것만 보므로
# 원칙적으로 `새로 생겼다`를 내지 않는다.
#
# **`절차·요건`만 예외다.** 절차에 단계를 더하면 그 단계 자체는 개정 전에 없던 것이라
# 역할 A가 `새로 생겼다`로 읽는다. 2026-08-12에 같은 12개 조항으로 확인했다 --
# `늘었다`로 지시하면 BM5가 0/12인데 셜록이 붙인 라벨은 10건이 `새로 생겼다`였고,
# 지시를 `새로 생겼다`로 바꾸자 **10/12**가 됐다. `rubric.md`의 회수율 실측에서도
# `(절차·요건, 새로 생겼다)`가 3/3인데 `(절차·요건, 늘었다)`는 3/6이다.
# **정의로 정한 것이 아니라 A가 실제로 어떻게 읽는지로 정했다.**
def applicable(clause: str) -> list[tuple[str, str]]:
    # 정의·목적 조항은 무엇을 규정하는 것이 아니라 무엇을 가리키는지 정하는 조항이다.
    # 넓히고 좁히는 것만 성립하고, 절차나 주체를 고칠 자리가 없다.
    if DEFINITION.search(clause) or PURPOSE.search(clause):
        return [("적용 범위", "늘었다")]
    out: list[tuple[str, str]] = []
    if ACTOR.search(clause):
        out += [("수행 주체", "늘었다"), ("수행 주체", "다른 값")]
    if PREDICATE.search(clause):
        out += [("절차·요건", "새로 생겼다")]
    if ENUM.search(clause):
        out += [("적용 범위", "늘었다"), ("적용 범위", "줄었다")]
    # **`다른 값`이 아니라 `늘었다`·`줄었다`로 건다.** 2026-08-13 탐침에서 두 지시 다
    # 대상은 잘 회수되는데(기한 17/19, 수치는 운영지침 계열 9/11) BM5가 11%·6%였다.
    # 셜록이 붙인 방향이 늘었다/줄었다로 갈렸고 `다른 값`은 대상이 맞은 건 중 0건이다.
    # 수가 바뀌면 늘거나 줄지 "다른 값"이 되지 않는다 -- `10명 → 12명`은 늘었고
    # `1개월 → 30일`은 줄었다. `(절차·요건, 늘었다)` → `새로 생겼다`와 같은 자리이며,
    # **정의로 정한 것이 아니라 A가 실제로 어떻게 읽는지로 정했다.**
    if NUMBER.search(clause):
        out += [("수치·기준", "늘었다"), ("수치·기준", "줄었다")]
    if DEADLINE.search(clause):
        out += [("기한·시점", "늘었다"), ("기한·시점", "줄었다")]
    if SUBMIT.search(clause):
        out += [("제출물·기재사항", "늘었다")]
    return out


# 역할 A가 회수하지 못하는 라벨은 B가 잘 써도 왕복 검증을 통과할 수 없다. A v2.2 실측
# 기준으로 0%인 쌍은 지시하지 않는다(`rubric.md`). A를 고치면 여기를 푼다.
BLOCKED = {("명칭", "다른 값"), ("적용 범위", "줄었다"), ("적용 범위", "다른 값")}


def clause_candidates(path: Path) -> list[tuple[str, str]]:
    """문서에서 개정할 수 있는 조항만 추린다."""
    blocks = indexed(path, path.stem)
    out = []
    for block_id, text in blocks:
        stripped = text.strip()
        if not (MIN_CHARS <= len(stripped) <= MAX_CHARS):
            continue
        if not PREDICATE.search(stripped):
            continue
        out.append((block_id, stripped))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("document", type=Path)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--limit", type=int, default=20, help="생성할 pair 수 상한")
    ap.add_argument("--per-clause", type=int, default=2, help="조항 하나에 걸 지시 수")
    ap.add_argument("--plan", type=Path,
                    help="계획을 세우지 말고 JSON으로 받은 것을 그대로 돌린다. 같은 조항·"
                         "같은 지시를 다른 모델로 다시 돌려 건별로 짝지어 비교할 때 쓴다. "
                         "`--limit`과 `--per-clause`는 무시한다")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="동시에 띄울 요청 수. GPU가 놀지 않을 만큼 올린다")
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 계획만 출력")
    args = ap.parse_args()

    whole_document = " ".join(text for _, text in indexed(args.document, args.document.stem))

    print(f"문서 {args.document.name}")
    if args.plan:
        # 계획을 밖에서 받는 경로. 조항 추리기와 지시 배분을 건너뛰므로, 옛 실행과 **같은
        # 조항 × 같은 지시**가 그대로 다시 돈다. 모델을 바꿔 놓고 건별로 짝지어 비교할 때
        # 이것이 필요하다 -- 계획을 새로 세우면 조항이 달라져 두 실행을 맞댈 수 없다.
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        print(f"  계획 파일      {args.plan.name}")
        print(f"  생성 계획      {len(plan)}건  (밖에서 받았다. --limit 무시)")
    else:
        candidates = clause_candidates(args.document)
        # 성립하는 지시를 **전부** 담는다. 조항당 상한(`--per-clause`)은 여기서 자르지
        # 않고 아래 뽑기에서 건다 -- 여기서 자르면 `applicable()`이 적어 놓은 순서가
        # 그대로 배분이 되어 버린다. 맨 위의 `수행 주체`가 두 자리를 늘 먼저 먹어서
        # 전 문서 기준 59.6%가 되고, `기한·시점`은 공급 271건 중 68건만 후보에 올라
        # 대상 6종 균등 배분(1,400건이면 종당 233건)이 아예 불가능했다.
        by_instruct: dict[tuple[str, str], list[dict]] = {}
        for block_id, clause in candidates:
            for target, direction in applicable(clause):
                if (target, direction) in BLOCKED:
                    continue
                by_instruct.setdefault((target, direction), []).append(
                    {"block_id": block_id, "clause": clause,
                     "instruct": {"대상": target, "방향": direction}})

        # 문서 순서대로 자르면 한 지시가 몰린다 -- 서술어는 거의 모든 조항에 있고 수치나
        # 기한은 드물기 때문이다. 실제로 20건 중 12건이 `(절차·요건, 늘었다)`로 나왔다.
        # `docs/기획서_최종.md` 2.3절이 단일 변경 유형 비중을 25%로 제한하므로, 지시별로
        # 돌아가며 하나씩 뽑아 상한에 걸리지 않게 한다.
        #
        # **드문 지시가 먼저 고른다.** 조항 하나에 걸 수 있는 지시가 `--per-clause`개로
        # 묶여 있어 자리를 두고 경쟁하는데, 흔한 지시가 먼저 집으면 드문 지시는 걸 조항이
        # 남지 않는다. 공급이 적은 지시부터 뽑아야 그 몫이 지켜진다.
        plan: list[dict] = []
        pools = [list(v) for v in sorted(by_instruct.values(), key=len)]
        per_clause_used: Counter[str] = Counter()
        while len(plan) < args.limit and any(pools):
            for pool in pools:
                if len(plan) >= args.limit:
                    break
                # 조항 상한에 이미 걸린 것은 앞으로도 못 쓴다(쓴 횟수는 늘기만 한다).
                # 버리면서 쓸 수 있는 첫 건까지 내려간다.
                while pool:
                    item = pool.pop(0)
                    if per_clause_used[item["block_id"]] < args.per_clause:
                        per_clause_used[item["block_id"]] += 1
                        plan.append(item)
                        break

        print(f"  조항 후보      {len(candidates)}개  ({MIN_CHARS}~{MAX_CHARS}자, 서술어 있음)")
        print(f"  생성 계획      {len(plan)}건  (조항당 최대 {args.per_clause}개 지시)")
    spread = Counter(f'({p["instruct"]["대상"]}, {p["instruct"]["방향"]})' for p in plan)
    for label, count in spread.most_common():
        print(f"      {count:>3}  {label}")
    if args.dry_run:
        print("\n--dry-run 이므로 호출하지 않았습니다.")
        return
    if not plan:
        raise SystemExit("걸 수 있는 지시가 없습니다.")

    template = Template((HERE / "prompts" / f"{args.prompt}.txt").read_text(encoding="utf-8"))
    judge = Template((HERE.parent / "interpret" / "prompts"
                      / f"{_run.JUDGE_PROMPT}.txt").read_text(encoding="utf-8"))
    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))

    tag = f"__plan_{args.plan.stem}" if args.plan else ""
    out_dir = HERE / "runs" / f"{solar.timestamp()}__generate__{args.document.stem}{tag}"
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(numbered: tuple[int, dict]) -> dict:
        """계획 한 건. 생성 → 채점 → 왕복 검증까지 하고 레코드를 돌려준다."""
        index, job = numbered
        target, direction = job["instruct"]["대상"], job["instruct"]["방향"]
        prompt = template.substitute(
            clause=job["clause"], target=target, direction=direction,
            target_def=_run.TARGET_DEF[target], direction_def=_run.DIRECTION_DEF[direction])
        try:
            raw = _run.call(url, api_key, prompt, _run.GENERATE_TEMPERATURE, timeout)
        except Exception as error:
            print(f"  [{index}/{len(plan)}] x 생성 실패 {job['block_id']}")
            return {**job, "error": solar.safe_error(error)}
        marked = _run.score_generation(job, raw)
        after = marked.pop("after")
        trip = {"BM5": 0, "BM5a": 0, "judge_labels": None,
                "judge_judgement": None, "judge_raw": None}
        if after and marked["BM2"]:
            try:
                trip = _run.round_trip(url, api_key, timeout, judge, job, after)
            except Exception as error:
                trip["judge_error"] = solar.safe_error(error)
        scores = {k: marked.get(k, 0) for k in ("BM1", "BM2", "BM3", "BM4")}
        scores["BM5"] = trip.pop("BM5")
        scores["BM5a"] = trip.pop("BM5a")
        # BM7 -- 문장이 문서에 실릴 수 있는가. 하드 게이트가 아니라 표시다(`inspect.py`).
        notes = text_check.inspect(job["clause"], after or "",
                                      job["instruct"]["대상"], whole_document) if after else []
        scores["BM7"] = int(not notes)
        # 게이트를 다 통과한 것만 학습 후보다. BM5에서 떨어진 것은 폐기하지 않고 A가 준
        # 라벨로 갈아 끼울 수 있다(`docs/기획서_최종.md` 2.3절). 서식 차이만 남은 것은
        # negative 표본으로 보낸다.
        # BM7과 BM5a는 게이트가 아니다. BM7은 `rubric.md`가 "하드 게이트가 아니라 표시"로
        # 정해 뒀는데도 여기서 맨 앞에 서서 버킷을 갈랐다 -- 2026-08-12 60건에서
        # `사람 확인 필요` 18건 중 12건이 C2·C4 오탐이었고 11건은 원래 `라벨 교체 후보`였다.
        # 6,000건이면 1,800건이 사람 검수로 빠지고 그 절반 이상이 헛알람이 된다.
        # 걸린 것은 `inspect`와 `scores["BM7"]`에 그대로 남으므로 검수 순서를 정하는 데는
        # 계속 쓸 수 있다. BM5a는 BM5를 갈라 보는 칸이라 애초에 게이트가 아니다.
        gates = {k: v for k, v in scores.items() if k not in ("BM7", "BM5a")}
        bucket = ("학습 후보" if all(gates.values())
                  else "negative" if scores["BM1"] and not scores["BM2"]
                  else "라벨 교체 후보" if scores["BM5"] == 0 and after else "폐기")
        print(f"  [{index}/{len(plan)}] {sum(gates.values())}/5  {bucket:<12} "
              f"({target}, {direction})  {job['block_id']}")
        return {**job, "after": after, "scores": scores, "bucket": bucket,
                "inspect": notes,
                "changed_ratio": marked.get("changed_ratio"), **trip, "raw": raw}

    # 한 건씩 보내면 서버에 요청이 항상 하나만 떠 있어 GPU가 논다. 요청을 여러 개
    # 동시에 띄워야 서버가 묶어서 처리한다(continuous batching). `work`가 공유하는
    # 것은 전부 읽기 전용이고 `_run.call`은 호출마다 페이로드를 새로 만들므로
    # 스레드로 나눠도 된다 -- 기다리는 동안 GIL을 놓는 것은 HTTP 대기뿐이다.
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        pairs = list(pool.map(work, enumerate(plan, 1)))

    graded = [p for p in pairs if "scores" in p]
    failures = sum("error" in p for p in pairs) + sum("judge_error" in p for p in pairs)
    buckets = Counter(p["bucket"] for p in graded)
    summary = {
        "document": str(args.document), "prompt": args.prompt,
        "plan": str(args.plan) if args.plan else None,
        # 어느 모델이 생성하고 판정했는지. 교사 모델이 바뀌면 같은 프롬프트라도 점수가
        # 달라지므로, 판본만 적어두면 나중에 두 실행을 잘못 맞대게 된다.
        "model": os.environ.get("SOLAR_MODEL"),
        "judge_prompt": _run.JUDGE_PROMPT, "planned": len(plan),
        "generated": len(graded), "failures": failures,
        "concurrency": args.concurrency,
        "buckets": dict(buckets),
        "BM_rates": {k: round(sum(p["scores"][k] for p in graded) / len(graded), 3)
                    for k in ("BM1", "BM2", "BM3", "BM4", "BM5a", "BM5", "BM7")} if graded else {},
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "pairs.json", pairs)
    print()
    for key, rate in summary["BM_rates"].items():
        print(f"  {key} {rate:>6.1%}")
    for bucket, count in buckets.most_common():
        print(f"  {bucket:<14} {count}")
    print(f"  저장: {out_dir.relative_to(REPOSITORY_DIR)}")


if __name__ == "__main__":
    main()
