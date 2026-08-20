"""2패스 -- 1패스가 만든 개정문에 v1.2를 **한 번 더** 걸어 복합을 만든다.

    원문 ──v1.2(지시1)──▶ 중간본 ──v1.2(지시2)──▶ 최종본
           (1패스, 끝났다)        (여기)

**새 프롬프트를 만들지 않는다.** v1.2를 두 번 쓰고 호출마다 지시가 하나씩이라 규칙
6("지시한 변경 하나만 넣습니다")이 그대로 성립한다. v1.3을 만들면 기존 합성 1,093건과
생성기가 달라져 곡선 605 -> 1,655 -> 3,000의 세 번째 점이 앞의 두 점과 같은 자에 못
올라간다. **변수를 하나만 늘린다 -- 「겹쳐 건다」 그 하나다.**

## 두 판이 여기서 갈린다

    조건 A   이 파일이 만든 최종본        (복합)
    조건 B   1패스의 중간본을 그대로       (단일)

**조건 B는 이미 끝나 있다.** 1패스 산출에 판정까지 붙어 있으므로 따로 만들 것이 없다.
여기서 만드는 것은 조건 A의 복합분뿐이고, **두 판은 이 조항들에서만 갈린다.**

## 새로 재는 칸 둘

사슬에만 있는 고장이 하나 있다 -- **2차 지시가 1차 변경을 덮어쓸 수 있다.** 모리아티가
2차에서 같은 문장을 다시 손대면 1차에 넣은 변경이 지워지고, 최종본은 변경이 하나뿐인데
우리는 그것을 복합으로 세게 된다.

    BM2c   원문 -> 중간본에서 새로 들어간 글자 조각이 최종본에도 남아 있는가 (기록만)
    BM8    셜록이 라벨을 2개 이상 붙였는가 (게이트)

**BM2c는 게이트에 넣지 않는다.** 이 라운드가 BM2c의 첫 측정이라 합격선을 그을 근거가
없다. 근거 없는 선으로 떨어뜨리면 사슬이 고장 난 것인지 선이 잘못된 것인지 가릴 수 없다.
`interpret/rubric.md`가 BM4의 문턱 0.5를 처음 둘 때 쓴 처리와 같다 -- 재서 기록하고,
라운드가 쌓이면 통과·실패 분포를 보고 정한다. 잴 것이 있는 비율(1패스 실측 50.2%)을
값과 함께 찍는 것도 그래서다. 커버리지 없이 적힌 BM2c 값은 나중에 읽을 수 없다.

**BM8이 복합의 성립 여부다.** BM5(지시한 쌍을 짚었는가)는 게이트에서 뺀다 -- 라벨은
어차피 셜록이 준 것으로 갈아끼우고(`docs/학습데이터_생성_프로세스.md` 3-5절), 우리가 사는
것은 「한 블록에 라벨이 여럿」이라는 학습 신호이지 라벨 이름이 아니다. 두 칸을 가르는 것은
「합치면 신호가 지워진다」를 따른 것이다.

## 후보에서 빼는 것 셋

    지시2 대상이 이미 붙음   1패스 판정에 그 대상이 벌써 있다. 걸어도 라벨이 안 는다
    이미 라벨 2개 이상       이미 복합이다. 자연 복합 50건에 이미 세어져 있다
    개정문이 없음            1패스에서 폐기된 것

## 출력

문서마다 실행 폴더를 따로 쓰고 `pairs.json`의 모양을 1패스와 똑같이 맞춘다. 그래야
`interpret/export_synth.py`가 **수정 없이** 읽는다 -- 그 파일은 역할 A 소유다.
`clause`가 원문, `after`가 최종본, `judge_raw`가 원문↔최종본 판정이다.

사용:
    python3 training_data/mutate/chain.py --runs <1패스 실행들> --plan-out plans/pass2/plan.json --dry-run
    python3 training_data/mutate/chain.py --plan plans/pass2/plan.json --slice :60
    python3 training_data/mutate/chain.py --plan plans/pass2/plan.json --slice 60:240
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_run = _load("mutate_run", HERE / "run.py")
_generate = _load("mutate_generate", HERE / "generate.py")
text_check = _load("mutate_text_check", HERE / "text_check.py")

# 축이 아닌 조합(전체 복합의 25%)에 쓸 지시2 후보.
#
# **지시1을 고정하지 않는다.** 처음에는 `절차·요건`으로 잡았다가 공급을 재고 바꿨다 --
# `plan.py`의 「드문 지시가 먼저 고른다」 규칙 때문에 **제일 흔한 `절차·요건`이 제일 나쁜
# 조항을 받는다.** 여러 대상이 성립하는 조항은 드문 지시들이 먼저 가져가고, `절차·요건`에는
# 그 대상 하나만 성립하는 조항이 남는다. 실측으로 1패스 산출 119건 중 **15건**만 두 번째
# 지시를 걸 수 있었다. 지시1을 안 묶으면 같은 후보가 504건이 된다.
#
# **실제 분포를 모르므로 성립하는 조합에 고르게 나눈다.** 「복합의 모양」 61건은 축이 되는
# `적용 범위`까지만 말해 주고, 축이 안 낀 25%의 내부 구성은 표본이 15건이라 안 나뉜다.
# 모르는 것을 지어내지 않고 균등으로 둔다.
NON_AXIS_SECOND = [("수행 주체", "늘었다"), ("제출물·기재사항", "늘었다"),
                   ("수치·기준", "늘었다")]
# **`기한·시점`은 지시2에서 뺀다.** 실제 복합 61건 중 `기한·시점`이 낀 것은 1건뿐인데,
# 우리 공급에서는 `기한·시점`이 걸리는 조항이 제일 많다(309건). 그대로 두면 공급이 실제
# 모양을 덮어써서 비축 복합의 절반 이상이 기한 조합이 된다.
NON_AXIS_EXCLUDE = {"기한·시점"}

# BM2c에서 무시할 조각 길이. 한두 글자짜리 삽입은 조사나 띄어쓰기 차이라 보존 여부를
# 물을 것이 못 된다. **근거가 있는 값이 아니다** -- BM4의 0.5와 같은 자리이고, 라운드가
# 쌓이면 분포를 보고 정한다. 지금은 재서 기록만 한다.
MIN_FRAGMENT = 5


def squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


def first_change_kept(before: str, mid: str, final: str) -> int | None:
    """BM2c -- 1차 변경이 최종본에 남아 있는가. 잴 것이 없으면 None.

    **삽입된 조각만 본다.** 1차가 삭제만 했다면 남아 있는지를 물을 대상이 없다. 공백을
    빼고 대조하는 것은 2차가 같은 문장을 손대며 띄어쓰기를 바꾸는 일이 흔하기 때문이다.
    """
    opcodes = difflib.SequenceMatcher(None, before, mid, autojunk=False).get_opcodes()
    fragments = [squeeze(mid[j1:j2]) for tag, _, _, j1, j2 in opcodes
                 if tag in ("insert", "replace")]
    fragments = [f for f in fragments if len(f) >= MIN_FRAGMENT]
    if not fragments:
        return None
    packed = squeeze(final)
    return int(all(f in packed for f in fragments))


def candidates(run_dirs: list[Path]) -> list[dict]:
    """1패스 산출에서 사슬을 걸 수 있는 것만 추린다."""
    out, skipped = [], Counter()
    for run_dir in run_dirs:
        summary = solar.read_json(run_dir / "summary.json")
        document = summary["document"]
        for pair in solar.read_json(run_dir / "pairs.json"):
            mid = pair.get("after")
            if not mid or pair.get("bucket") == "폐기":
                skipped["개정문이 없음"] += 1
                continue
            labels = pair.get("judge_labels") or []
            got = {str(x.get("대상")) for x in labels if isinstance(x, dict)}
            if len(labels) >= 2:
                skipped["이미 라벨 2개 이상"] += 1
                continue
            out.append({"document": document, "series": Path(document).parent.name,
                        "block_id": pair["block_id"], "clause": pair["clause"],
                        "mid": mid, "instruct": pair["instruct"],
                        "instruct2": pair.get("instruct2"), "got": sorted(got),
                        "source_run": run_dir.name})
    for reason, count in skipped.most_common():
        print(f"      뺌  {reason:<18} {count}건")
    return out


def build_plan(pool: list[dict], axis_target: int, non_axis_target: int) -> list[dict]:
    """축 복합과 비축 복합을 섞어 계획을 세운다.

    **조합끼리 번갈아 담는다.** 앞 60건만 먼저 돌려 BM8을 재고 멈출 것이므로, 계획 앞쪽이
    한 조합으로 몰리면 그 60건이 전체를 대표하지 못한다.
    """
    axis, non_axis = [], []
    for row in pool:
        if row["instruct2"]:
            # 지시2 대상이 1패스 판정에 벌써 있으면 걸어도 라벨이 안 는다.
            if row["instruct2"]["대상"] in row["got"]:
                continue
            axis.append({**row, "축": True})
    used = {(r["document"], r["block_id"]) for r in axis}

    # 비축 -- 두 번째 대상이 성립하는 조항을 고른다. **성립 판정은 중간본에 대고 한다.**
    # 모리아티가 2차에서 실제로 보는 것이 원문이 아니라 중간본이기 때문이다.
    #
    # 조합별 몫은 균등으로 두되, 공급이 모자란 조합이 있으면 남는 몫은 다른 조합이
    # 가져간다. 조합 수로 나눈 값을 상한으로 두고 돌아가며 담는 것으로 그렇게 된다.
    per_combo = max(1, -(-non_axis_target // max(len(NON_AXIS_SECOND), 1)))
    taken: Counter[tuple[str, str, str]] = Counter()
    for row in pool:
        if len(non_axis) >= non_axis_target:
            break
        if row["instruct2"] or (row["document"], row["block_id"]) in used:
            continue
        first = row["instruct"]["대상"]
        if first in NON_AXIS_EXCLUDE:
            continue
        allowed = [c for c in _generate.applicable(row["mid"])
                   if c not in _generate.BLOCKED]
        for second in NON_AXIS_SECOND:
            key = (first, second[0], second[1])
            if second not in allowed or second[0] == first or second[0] in row["got"]:
                continue
            if taken[key] >= per_combo:
                continue
            taken[key] += 1
            non_axis.append({**row, "축": False,
                             "instruct2": {"대상": second[0], "방향": second[1]}})
            break

    # 조합별로 나눠 담고 **몫에 비례해** 번갈아 뽑는다. 앞 60건만 먼저 돌려 BM8을 재고
    # 멈출 것이므로, 그 60건이 계획 전체의 축소판이어야 잰 값을 그대로 쓸 수 있다.
    # 균등하게 번갈아 담으면 12건짜리 조합이 60건 중 10건을 차지해 잰 값이 기운다.
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in axis[:axis_target] + non_axis[:non_axis_target]:
        groups[f'{row["instruct"]["대상"]} → {row["instruct2"]["대상"]}'].append(row)
    total = sum(len(v) for v in groups.values())
    plan, cursors = [], {k: 0 for k in groups}
    while len(plan) < total:
        # 지금까지 담은 비율이 제 몫에 가장 못 미치는 조합을 집는다.
        key = min((k for k in groups if cursors[k] < len(groups[k])),
                  key=lambda k: cursors[k] / len(groups[k]))
        plan.append(groups[key][cursors[key]])
        cursors[key] += 1
    return plan


def score(job: dict, raw: str, final: str | None, marked: dict, trip: dict,
          document_text: str) -> tuple[dict, list[str]]:
    """원문을 기준으로 매긴다. 중간본이 아니다 -- 학습 레코드의 입력이 원문이다."""
    before, mid = job["clause"], job["mid"]
    i1, i2 = job["instruct"], job["instruct2"]
    scores = {"BM1": marked["BM1"]}
    if not final:
        return {**scores, "BM2": 0, "BM2b": 0, "BM2c": 0, "BM2c_잼": 0, "BM3": 0,
                "BM4": 0, "BM5": 0, "BM5a": 0, "BM5_2": 0, "BM7": 0, "BM8": 0}, []
    scores["BM2"] = int(classify_diff.classify(before, final) is None)
    scores["BM2b"] = marked["BM2"]          # 2차 지시가 실제로 무언가 바꿨나
    # BM2c는 **잴 수 있을 때만 뜻이 있다.** 1차가 삽입을 안 했으면 보존 여부를 물을 대상이
    # 없어 게이트를 통과시키되, 잰 건인지를 따로 남긴다. 2026-08-20 실측으로 1패스 1,447건
    # 중 **50.2%에만 5자 이상 삽입 조각이 있다.** 전체 평균으로 보고하면 절반이 공짜 통과라
    # 「90%」가 실제로는 「잰 것의 80%」일 수 있다. 합격선은 잰 것 중에서 본다.
    kept = first_change_kept(before, mid, final)
    scores["BM2c"] = 1 if kept is None else kept
    scores["BM2c_잼"] = int(kept is not None)
    leaked = [w for w in (i1["대상"], i1["방향"], i2["대상"], i2["방향"]) if w in final]
    scores["BM3"] = int(not leaked)
    scores["BM4"] = int(_run.changed_ratio(before, final) <= 0.5)

    labels = trip.get("judge_labels") or []
    got = {(str(x.get("대상")), str(x.get("방향"))) for x in labels if isinstance(x, dict)}
    scores["BM5"] = int((i1["대상"], i1["방향"]) in got and (i2["대상"], i2["방향"]) in got)
    scores["BM5a"] = int(i1["대상"] in {t for t, _ in got}
                         and i2["대상"] in {t for t, _ in got})
    scores["BM5_2"] = int((i2["대상"], i2["방향"]) in got)
    scores["BM8"] = int(len(labels) >= 2)

    # BM7 -- 지시가 둘이므로 두 번 재고 합친다. C1은 `수행 주체` 지시일 때만 켜지는
    # 검사라 어느 한쪽이 그것이면 봐야 하고(합집합), C3은 값을 바꾸라는 지시가 **면제**
    # 하는 검사라 어느 한쪽이 그것이면 빼야 한다. 교집합으로 하면 C1이 통째로 꺼진다.
    notes = sorted(set(text_check.inspect(before, final, i1["대상"], document_text))
                   | set(text_check.inspect(before, final, i2["대상"], document_text)))
    if {i1["대상"], i2["대상"]} & set(text_check.VALUE_TARGETS):
        notes = [n for n in notes if not n.startswith("C3")]
    scores["BM7"] = int(not notes)
    return scores, notes


def report(plan: list[dict]) -> None:
    print(f"\n  계획 {len(plan)}건 "
          f"(축 {sum(p['축'] for p in plan)} · 비축 {sum(not p['축'] for p in plan)})")
    axis = sum(p["축"] for p in plan)
    print(f"  축 비중 {axis / max(len(plan), 1):.1%}   (실제 복합은 75%)")
    print("\n  [조합별]")
    for label, count in Counter(f'{p["instruct"]["대상"]} → {p["instruct2"]["대상"]}'
                                for p in plan).most_common():
        print(f"      {count:>4}  {label}")
    print("\n  [계열별]")
    for series, count in Counter(p["series"] for p in plan).most_common(8):
        print(f"      {count:>4}  {series}")
    head = plan[:60]
    print(f"\n  [앞 60건의 조합]  BM8을 여기서 잰다")
    for label, count in Counter(f'{p["instruct"]["대상"]} → {p["instruct2"]["대상"]}'
                                for p in head).most_common():
        print(f"      {count:>4}  {label}")


def parse_slice(text: str, total: int) -> tuple[int, int]:
    start, _, stop = text.partition(":")
    return (int(start) if start else 0), (int(stop) if stop else total)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, nargs="*", default=[],
                    help="1패스 실행 폴더들. --plan을 쓰면 필요 없다")
    ap.add_argument("--plan", type=Path, help="계획을 파일에서 받는다")
    ap.add_argument("--plan-out", type=Path, help="세운 계획을 이 파일에 쓴다")
    ap.add_argument("--slice", default=":", help="계획의 일부만 돌린다. 예: :60  60:240")
    ap.add_argument("--skip-saved", action="store_true",
                    help="runs/의 사슬 실행 폴더에 이미 저장된 (문서, 블록)은 건너뛴다")
    ap.add_argument("--axis", type=int, default=107, help="축 복합 목표")
    ap.add_argument("--non-axis", type=int, default=35, help="비축 복합 목표")
    ap.add_argument("--over", type=float, default=2.5,
                    help="BM8 실패를 감안한 배수. 앞 60건으로 재고 나서 정한다")
    ap.add_argument("--prompt", default="v1.2")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.plan:
        # `--plan-out`과 같은 규칙으로 푼다. 저장소 어디서 실행해도 같은 파일을 가리켜야
        # 한다 -- `run.sh`는 뿌리에서 돌고 사람은 보통 mutate/ 기준으로 친다.
        plan_path = args.plan if args.plan.is_absolute() else HERE / args.plan
        if not plan_path.exists():
            plan_path = REPOSITORY_DIR / args.plan
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        print(f"계획 파일 {plan_path.name} · {len(plan)}건")
    else:
        if not args.runs:
            raise SystemExit("--runs 또는 --plan 중 하나가 필요합니다.")
        print(f"1패스 실행 {len(args.runs)}개에서 후보 추리기")
        pool = candidates([r if r.is_absolute() else REPOSITORY_DIR / r
                           for r in args.runs])
        print(f"      후보 {len(pool)}건")
        plan = build_plan(pool, round(args.axis * args.over),
                          round(args.non_axis * args.over))
        report(plan)
        if args.plan_out:
            out = args.plan_out if args.plan_out.is_absolute() else HERE / args.plan_out
            out.parent.mkdir(parents=True, exist_ok=True)
            solar.write_json(out, plan)
            print(f"\n  계획을 적었다: {out.relative_to(REPOSITORY_DIR)}")

    start, stop = parse_slice(args.slice, len(plan))
    plan = plan[start:stop]
    print(f"\n  이번에 돌릴 것 {len(plan)}건  (계획의 [{start}:{stop}])")

    # **이미 파일로 남은 것은 다시 부르지 않는다.** 슬라이스는 계획의 자리를 자르는 것이라
    # 중간에 빠진 것을 도로 채울 수 없다. 2026-08-20에 폴더 이름이 겹쳐 16건을 잃었을 때
    # 그 16건이 [0:60] 안에 흩어져 있어 슬라이스로는 집을 수가 없었다.
    if args.skip_saved:
        # **조항이 아니라 「조항 + 지시 두 개」로 센다.** 계획은 같은 조항을 다른 지시
        # 조합으로 두 번 쓴다(356건 중 36개 조항). 조항만으로 세면 아직 안 돌린 두 번째
        # 조합까지 같이 빠진다.
        def signature(row: dict) -> tuple:
            return (row["document"], row["block_id"],
                    row["instruct"]["대상"], row["instruct"]["방향"],
                    row["instruct2"]["대상"], row["instruct2"]["방향"])

        saved: Counter = Counter()
        for pairs_file in (HERE / "runs").glob("*__chain/pairs.json"):
            for row in json.loads(pairs_file.read_text(encoding="utf-8")):
                saved[signature(row)] += 1
        # 같은 서명이 계획에 두 번 있으면 저장된 것도 두 번까지만 뺀다.
        kept, used = [], Counter()
        for job in plan:
            key = signature(job)
            if used[key] < saved[key]:
                used[key] += 1
            else:
                kept.append(job)
        print(f"  이미 저장된 {len(plan) - len(kept)}건을 뺐다 → {len(kept)}건")
        plan = kept
    if args.dry_run:
        print("\n--dry-run 이므로 호출하지 않았습니다.")
        return
    if not plan:
        raise SystemExit("돌릴 것이 없습니다.")

    template = Template((HERE / "prompts" / f"{args.prompt}.txt").read_text(encoding="utf-8"))
    judge = Template((HERE.parent / "interpret" / "prompts"
                      / f"{_run.JUDGE_PROMPT}.txt").read_text(encoding="utf-8"))
    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "900"))

    # 문서 전문은 BM7의 C2·C3이 쓴다. 문서마다 한 번만 읽는다.
    documents = {d: " ".join(t for _, t in indexed(REPOSITORY_DIR / d, Path(d).stem))
                 for d in sorted({p["document"] for p in plan})}

    def work(numbered: tuple[int, dict]) -> dict:
        index, job = numbered
        i1, i2 = job["instruct"], job["instruct2"]
        prompt = template.substitute(
            clause=job["mid"], target=i2["대상"], direction=i2["방향"],
            target_def=_run.TARGET_DEF[i2["대상"]],
            direction_def=_run.DIRECTION_DEF[i2["방향"]])
        try:
            raw = _run.call(url, api_key, prompt, _run.GENERATE_TEMPERATURE, timeout)
        except Exception as error:
            print(f"  [{index}/{len(plan)}] x 2차 생성 실패 {job['block_id']}")
            return {**job, "error": solar.safe_error(error)}
        marked = _run.score_generation({"clause": job["mid"], "instruct": i2}, raw)
        final = marked.pop("after")
        trip = {"BM5": 0, "BM5a": 0, "judge_labels": None,
                "judge_judgement": None, "judge_raw": None}
        # 원문과 최종본을 짝지어 판정한다. 중간본은 판정에 안 넣는다 -- 학습 레코드의
        # 입력이 (원문, 최종본)이므로 셜록도 그 둘만 봐야 한다.
        if final and marked["BM2"]:
            try:
                trip = _run.round_trip(url, api_key, timeout, judge,
                                       {"block_id": job["block_id"],
                                        "clause": job["clause"], "instruct": i1}, final)
            except Exception as error:
                trip["judge_error"] = solar.safe_error(error)
        trip.pop("BM5", None)
        trip.pop("BM5a", None)
        scores, notes = score(job, raw, final, marked, trip, documents[job["document"]])
        # **BM2c는 게이트가 아니다.** 재서 기록만 한다 -- 아래 「새로 재는 칸 둘」 참조.
        gates = ("BM1", "BM2", "BM2b", "BM3", "BM4", "BM8")
        bucket = ("복합" if all(scores[k] for k in gates)
                  else "복합 실패" if scores["BM1"] and final else "폐기")
        print(f"  [{index}/{len(plan)}] {sum(scores[k] for k in gates)}/{len(gates)}  "
              f"{bucket:<8} ({i1['대상']} → {i2['대상']})  {job['block_id']}")
        return {**job, "after": final, "scores": scores, "bucket": bucket,
                "inspect": notes, "changed_ratio": _run.changed_ratio(job["clause"], final)
                if final else None, **trip, "raw": raw}

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool_exec:
        pairs = list(pool_exec.map(work, enumerate(plan, 1)))

    graded = [p for p in pairs if "scores" in p]
    stamp = solar.timestamp()
    by_document: dict[str, list[dict]] = defaultdict(list)
    for pair in pairs:
        by_document[pair["document"]].append(pair)

    # **문서마다 실행 폴더를 따로 쓴다.** `export_synth.series_of`가 summary의 document
    # 경로에서 계열을 읽으므로, 여러 문서를 한 폴더에 담으면 계열이 전부 한 이름이 된다.
    #
    # **폴더 이름에 계열을 넣는다.** 파일 이름만 쓰면 계열이 달라도 이름이 같은 원천이
    # 한 폴더로 뭉쳐 나중 것이 앞의 것을 덮어쓴다 -- 2026-08-20 앞 60건에서 그렇게
    # 16건을 잃었다(`ftc_deposit_terms_pair/after_2024`와
    # `me_environment_tech_guideline_pair/after_2024`). `plan.py`가 계획 파일을
    # `{계열}__{파일명}.json`으로 짓는 것과 같은 규칙이다.
    #
    # 1패스에는 이 고장이 없다 -- `generate.py`는 한 번에 문서 하나만 다룬다. 여러
    # 문서를 한 프로세스에서 처리하는 `chain.py`에만 있다.
    for document, items in sorted(by_document.items()):
        source = Path(document)
        series = source.parent.name or "unknown"
        out_dir = HERE / "runs" / f"{stamp}__generate__{series}__{source.stem}__chain"
        if out_dir.exists():
            raise SystemExit(f"{out_dir} 가 이미 있습니다. 폴더 이름이 겹칩니다.")
        out_dir.mkdir(parents=True)
        solar.write_json(out_dir / "pairs.json", items)
        solar.write_json(out_dir / "summary.json", {
            "document": document, "prompt": args.prompt, "plan": str(args.plan or ""),
            "pass": 2, "model": os.environ.get("SOLAR_MODEL"),
            "judge_prompt": _run.JUDGE_PROMPT,
            "planned": len(items), "generated": sum("scores" in p for p in items),
            "failures": sum("error" in p or "judge_error" in p for p in items),
            "concurrency": args.concurrency,
            "buckets": dict(Counter(p.get("bucket") for p in items if "scores" in p)),
        })

    keys = ("BM1", "BM2", "BM2b", "BM3", "BM4", "BM5a", "BM5", "BM5_2", "BM7", "BM8")
    print()
    for key in keys:
        if graded:
            print(f"  {key:<5} {sum(p['scores'][key] for p in graded) / len(graded):>6.1%}")
    # BM2c는 잰 것 중에서만 본다. 커버리지를 같이 찍어야 그 값을 읽을 수 있다.
    measurable = [p for p in graded if p["scores"]["BM2c_잼"]]
    if measurable:
        rate = sum(p["scores"]["BM2c"] for p in measurable) / len(measurable)
        print(f"  BM2c  {rate:>6.1%}   (잰 것 {len(measurable)}/{len(graded)} = "
              f"{len(measurable) / len(graded):.1%}. 1패스 실측 커버리지는 50.2%였다)")
    for bucket, count in Counter(p["bucket"] for p in graded).most_common():
        print(f"  {bucket:<10} {count}")
    print(f"  실행 폴더 {len(by_document)}개: runs/{stamp}__generate__*__chain")


if __name__ == "__main__":
    main()
