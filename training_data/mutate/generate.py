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

사용:
    python training_data/mutate/generate.py DOC --prompt v1.1 --limit 20
    python training_data/mutate/generate.py DOC --prompt v1.1 --dry-run   # 호출 없이 계획만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
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
NUMBER = re.compile(r"\d+\s*(?:퍼센트|%|원|억|만원|배|개|명|점|등급)")
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
# `새로 생겼다`를 내지 않는다.
def applicable(clause: str) -> list[tuple[str, str]]:
    # 정의·목적 조항은 무엇을 규정하는 것이 아니라 무엇을 가리키는지 정하는 조항이다.
    # 넓히고 좁히는 것만 성립하고, 절차나 주체를 고칠 자리가 없다.
    if DEFINITION.search(clause) or PURPOSE.search(clause):
        return [("적용 범위", "늘었다")]
    out: list[tuple[str, str]] = []
    if ACTOR.search(clause):
        out += [("수행 주체", "늘었다"), ("수행 주체", "다른 값")]
    if PREDICATE.search(clause):
        out += [("절차·요건", "늘었다")]
    if ENUM.search(clause):
        out += [("적용 범위", "늘었다"), ("적용 범위", "줄었다")]
    if NUMBER.search(clause):
        out += [("수치·기준", "다른 값")]
    if DEADLINE.search(clause):
        out += [("기한·시점", "다른 값")]
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
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 계획만 출력")
    args = ap.parse_args()

    whole_document = " ".join(text for _, text in indexed(args.document, args.document.stem))
    candidates = clause_candidates(args.document)
    by_instruct: dict[tuple[str, str], list[dict]] = {}
    for block_id, clause in candidates:
        allowed = [c for c in applicable(clause) if c not in BLOCKED]
        for target, direction in allowed[:args.per_clause]:
            by_instruct.setdefault((target, direction), []).append(
                {"block_id": block_id, "clause": clause,
                 "instruct": {"대상": target, "방향": direction}})

    # 문서 순서대로 자르면 한 지시가 몰린다 -- 서술어는 거의 모든 조항에 있고 수치나
    # 기한은 드물기 때문이다. 실제로 20건 중 12건이 `(절차·요건, 늘었다)`로 나왔다.
    # `docs/기획서_최종.md` 2.3절이 단일 변경 유형 비중을 25%로 제한하므로, 지시별로
    # 돌아가며 하나씩 뽑아 상한에 걸리지 않게 한다.
    plan, pools = [], [list(v) for v in by_instruct.values()]
    while len(plan) < args.limit and any(pools):
        for pool in pools:
            if not pool or len(plan) >= args.limit:
                continue
            plan.append(pool.pop(0))

    print(f"문서 {args.document.name}")
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

    out_dir = HERE / "runs" / f"{solar.timestamp()}__generate__{args.document.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs, failures = [], 0
    for index, job in enumerate(plan, 1):
        target, direction = job["instruct"]["대상"], job["instruct"]["방향"]
        prompt = template.substitute(
            clause=job["clause"], target=target, direction=direction,
            target_def=_run.TARGET_DEF[target], direction_def=_run.DIRECTION_DEF[direction])
        try:
            raw = _run.call(url, api_key, prompt, _run.GENERATE_TEMPERATURE, timeout)
        except Exception as error:
            failures += 1
            print(f"  [{index}/{len(plan)}] x 생성 실패 {job['block_id']}")
            pairs.append({**job, "error": solar.safe_error(error)})
            continue
        marked = _run.score_generation(job, raw)
        after = marked.pop("after")
        trip = {"M5": 0, "judge_labels": None, "judge_judgement": None, "judge_raw": None}
        if after and marked["M2"]:
            try:
                trip = _run.round_trip(url, api_key, timeout, judge, job, after)
            except Exception as error:
                failures += 1
                trip["judge_error"] = solar.safe_error(error)
        scores = {k: marked.get(k, 0) for k in ("M1", "M2", "M3", "M4")}
        scores["M5"] = trip.pop("M5")
        # M7 -- 문장이 문서에 실릴 수 있는가. 하드 게이트가 아니라 표시다(`inspect.py`).
        notes = text_check.inspect(job["clause"], after or "",
                                      job["instruct"]["대상"], whole_document) if after else []
        scores["M7"] = int(not notes)
        # 게이트를 다 통과한 것만 학습 후보다. M5에서 떨어진 것은 폐기하지 않고 A가 준
        # 라벨로 갈아 끼울 수 있다(`docs/기획서_최종.md` 2.3절). 서식 차이만 남은 것은
        # negative 표본으로 보낸다.
        gates = {k: v for k, v in scores.items() if k != "M7"}
        bucket = ("사람 확인 필요" if after and notes
                  else "학습 후보" if all(gates.values())
                  else "negative" if scores["M1"] and not scores["M2"]
                  else "라벨 교체 후보" if scores["M5"] == 0 and after else "폐기")
        pairs.append({**job, "after": after, "scores": scores, "bucket": bucket,
                      "inspect": notes,
                      "changed_ratio": marked.get("changed_ratio"), **trip, "raw": raw})
        print(f"  [{index}/{len(plan)}] {sum(gates.values())}/5  {bucket:<12} "
              f"({target}, {direction})  {job['block_id']}")

    graded = [p for p in pairs if "scores" in p]
    buckets = Counter(p["bucket"] for p in graded)
    summary = {
        "document": str(args.document), "prompt": args.prompt,
        "judge_prompt": _run.JUDGE_PROMPT, "planned": len(plan),
        "generated": len(graded), "failures": failures,
        "buckets": dict(buckets),
        "M_rates": {k: round(sum(p["scores"][k] for p in graded) / len(graded), 3)
                    for k in ("M1", "M2", "M3", "M4", "M5", "M7")} if graded else {},
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "pairs.json", pairs)
    print()
    for key, rate in summary["M_rates"].items():
        print(f"  {key} {rate:>6.1%}")
    for bucket, count in buckets.most_common():
        print(f"  {bucket:<14} {count}")
    print(f"  저장: {out_dir.relative_to(REPOSITORY_DIR)}")


if __name__ == "__main__":
    main()
