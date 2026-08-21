"""2차런의 생성 계획을 **전 문서에서 한 번에** 세운다. 모델 호출은 하지 않는다.

`generate.py`도 계획을 세우지만 **문서 하나씩** 세운다. 그것으로는 두 가지를 못 한다.

**하나 - 복합의 조합 비율.** 복합을 `적용 범위`를 축으로 75% 채우려면 어느 문서에 그런
조항이 몇 개 있는지를 전부 본 뒤에 배분해야 한다. 문서별로 나눠 세우면 조합표를 맞출 수
없다.

**둘 - 같은 조항이 두 문서에서 뽑히는 것.** `documents.py`가 한 문서쌍의 이전판과 이후판을
둘 다 씨앗으로 쓰므로, 개정 때 안 바뀌고 남은 조항이 양쪽에서 똑같이 뽑힌다. 2026-08-13
본 생성에서 `export_synth.py`가 이 이유로 **97건을 버렸다** -- 생성 호출을 다 쓰고 난
뒤였다. 여기서 조항 본문으로 걸러내면 호출을 쓰기 전에 사라진다.

`TODO.md`는 이 문제를 「씨앗을 이후판 하나로 줄인다」로 풀려고 했으나 그러면 공급이 절반이
된다. `적용 범위 + 수치·기준`이 성립하는 조항은 전체에 25개뿐이라 절반이 되면 말라버린다.
**본문 대조는 공급을 안 깎고 같은 낭비를 없앤다.**

## 두 판으로 나눠 돌린다 -- 1패스와 2패스

3,000건은 두 판으로 맞대어진다(`docs/PLAN.md`). 조건 A는 복합 192건이 들어간 판이고,
조건 B는 그 192건을 단일로 바꾼 판이며, **두 판이 1,046건을 공유한다.**

    1패스   전 계획에 v1.2를 한 번 건다        -> 단일 1,238건 (두 판이 다 쓴다)
    2패스   그 중 일부의 산출에 v1.2를 한 번 더 -> 복합 192건 (조건 A만 쓴다)

**1패스는 기존 합성 1,093건을 만든 공정과 글자 하나까지 같다.** 같은 프롬프트(v1.2), 같은
온도(0.9), 수정하지 않은 `generate.py`다. 곡선 605 -> 1,655 -> 3,000의 세 번째 점이 앞의 두
점과 같은 자에 올라가야 하므로 생성기를 바꾸지 않는다.

**2패스의 입력은 1패스의 산출이다.** 그래서 이 파일은 2패스를 계획하지 않는다 -- 어느 건이
살아남았는지 알아야 고를 수 있다. 다만 **`적용 범위`를 축으로 하는 조합은 조항이 드물어**
1패스에서 미리 잡아둔다. 잡아둔 건에는 `instruct2`가 붙어 있고, `generate.py`는 그 키를
모르므로 1패스에서는 그냥 지나간다(`pairs.json`에 그대로 실려 나온다).

## 조합표

실제 복합 61건의 모양을 따른다(`interpret/CHANGELOG.md`의 「복합의 모양」) -- 라벨 2개짜리
79%, `적용 범위`를 축으로 75%, 최빈 조합이 `적용 범위`+`절차·요건`이다.

**지시1이 공급이 많은 쪽, 지시2가 적은 쪽이다.** 순서에 이유가 있다. 1패스의 산출(지시1만
들어간 개정문)이 곧 조건 B의 레코드가 되므로, 축 대상인 `적용 범위`를 지시1에 놓으면 조건
B가 `적용 범위`로 쏠려 「복합 미증량」이 아니라 「적용 범위 과다」인 판이 된다.

**`명칭`이 빠진 자리는 못 메운다.** 실제 복합의 30%가 `명칭`을 끼는데 `generate.py`의
`BLOCKED`에 걸려 있다. 셜록 v2.3이 `명칭`과 `제출물·기재사항`의 경계를 가른 뒤에 열린다.

사용:
    python3 training_data/mutate/plan.py --out plans/run2 --limit 1450 --composite 330
    python3 training_data/mutate/plan.py --out plans/run2 --limit 1450 --dry-run
    python3 training_data/mutate/plan.py --out plans/archive/smoke --limit 50 --composite 0 \
        --per-series 10 --series mafra_rd_guideline_pair me_environment_tech_guideline_pair
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))
sys.path.insert(0, str(REPOSITORY_DIR / "source_data"))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_generate = _load("mutate_generate", HERE / "generate.py")
_documents = _load("mutate_documents", HERE / "documents.py")

# (지시1 후보들, 지시2, 복합 144건에서의 몫).
#
# 지시1이 목록인 것은 방향이 둘인 대상 때문이다. `수치·기준`과 `기한·시점`은 `늘었다`와
# `줄었다`를 둘 다 걸어야 한다 -- 2026-08-13에 `다른 값`으로 걸었을 때 BM5가 5%·17%였고
# 두 방향으로 가르자 95%·90%가 됐다. 한쪽만 걸면 조항이 정한 방향과 어긋난 절반이 깎인다.
COMPOSITE_AXIS: list[tuple[list[tuple[str, str]], tuple[str, str], int]] = [
    ([("절차·요건", "새로 생겼다")],                       ("적용 범위", "늘었다"), 55),
    ([("수행 주체", "늘었다"), ("수행 주체", "다른 값")],  ("적용 범위", "늘었다"), 40),
    ([("제출물·기재사항", "늘었다")],                      ("적용 범위", "늘었다"), 30),
    ([("기한·시점", "늘었다"), ("기한·시점", "줄었다")],   ("적용 범위", "늘었다"), 10),
    ([("수치·기준", "늘었다"), ("수치·기준", "줄었다")],   ("적용 범위", "늘었다"),  9),
]

# 축이 아닌 조합 48건(전체 복합의 25%)은 여기서 안 잡는다. 전부 지시1이 `절차·요건`이고
# 지시2가 `수행 주체`·`제출물`·`기한`·`수치`인데, 그런 조항이 208~2,512개씩 있어 2패스에서
# 1패스 산출을 보고 골라도 늦지 않다. **드문 것만 미리 잡는다.**


def normalize(clause: str) -> str:
    """중복 대조용. 공백 차이만 다른 것은 같은 조항으로 본다."""
    return re.sub(r"\s+", " ", clause).strip()


def key_of(row: dict) -> tuple[str, str]:
    """조항 하나를 가리키는 이름. `id()`를 쓰면 기록에 남길 수 없다."""
    return (row["document"], row["block_id"])


def collect(root: Path, series_filter: set[str] | None) -> list[dict]:
    """씨앗 문서 전부에서 조항 후보를 모으고 본문이 같은 것을 걸러낸다.

    **먼저 나온 것을 남긴다.** `documents.unique()`가 경로순으로 고정된 목록을 주므로
    같은 입력에 같은 결과가 나온다.
    """
    seen: set[str] = set()
    rows: list[dict] = []
    duplicates = no_instruct = 0
    for path in _documents.unique(root):
        series = path.parent.name
        if series_filter and series not in series_filter:
            continue
        try:
            candidates = _generate.clause_candidates(path)
        except Exception as error:
            print(f"  !  건너뜀 {path.name} ({type(error).__name__})")
            continue
        for block_id, clause in candidates:
            marker = normalize(clause)
            if marker in seen:
                duplicates += 1
                continue
            seen.add(marker)
            allowed = [c for c in _generate.applicable(clause)
                       if c not in _generate.BLOCKED]
            if not allowed:
                no_instruct += 1
                continue
            rows.append({"document": str(path.relative_to(REPOSITORY_DIR)),
                         "series": series, "block_id": block_id,
                         "clause": clause, "allowed": allowed})
    print(f"  조항 후보          {len(rows) + duplicates + no_instruct}개")
    print(f"  본문이 같아 뺀 것  {duplicates}개"
          f"   (2026-08-13에 호출을 다 쓰고 97건을 버렸던 그것)")
    print(f"  걸 지시가 없어 뺀 것 {no_instruct}개")
    print(f"  남은 조항          {len(rows)}개")
    return rows


def earmark_composites(rows: list[dict], total: int) -> tuple[list[dict], list[str]]:
    """`적용 범위`를 축으로 하는 복합용 조항을 미리 잡아둔다.

    **공급이 적은 조합부터 고른다.** 조합끼리 같은 조항을 두고 경쟁하는데(`다음 각 호`가
    있는 조항은 여러 조합에 다 들어간다), 흔한 조합이 먼저 집으면 드문 조합은 걸 자리가
    남지 않는다. `적용 범위 + 수치·기준`은 전체에 25조항뿐이다.
    """
    lines: list[str] = []
    if total <= 0:
        return [], lines
    scale = total / sum(share for _, _, share in COMPOSITE_AXIS)
    wanted = [(firsts, second, max(1, round(share * scale)))
              for firsts, second, share in COMPOSITE_AXIS]
    pools = {id(firsts): [r for r in rows if second in r["allowed"]
                          and any(f in r["allowed"] for f in firsts)]
             for firsts, second, _ in wanted}

    taken_keys: set[tuple[str, str]] = set()
    picked: list[dict] = []
    for firsts, second, need in sorted(wanted, key=lambda w: len(pools[id(w[0])])):
        pool = pools[id(firsts)]
        count = 0
        for row in pool:
            if count >= need:
                break
            if key_of(row) in taken_keys:
                continue
            # 이 조항에서 실제로 성립하는 지시1만 쓴다. 방향이 둘인 대상은 번갈아 건다.
            options = [f for f in firsts if f in row["allowed"]]
            first = options[count % len(options)]
            taken_keys.add(key_of(row))
            picked.append({**row, "instruct": {"대상": first[0], "방향": first[1]},
                           "instruct2": {"대상": second[0], "방향": second[1]}})
            count += 1
        short = "" if count >= need else f"   ← {need - count}건 부족"
        lines.append(f"      {count:>3}/{need:<4} {firsts[0][0]:<8} → {second[0]}"
                     f"   (공급 {len(pool)}조항){short}")
    return picked, lines


def allocate_singles(rows: list[dict], limit: int, per_clause: int,
                     per_series: int | None) -> list[dict]:
    """단일 지시를 배분한다. `generate.py`의 뽑기 규칙을 그대로 쓴다.

    **드문 지시가 먼저 고른다.** 조항 하나에 걸 수 있는 지시가 `per_clause`개로 묶여 있어
    자리를 두고 경쟁하는데, 흔한 지시가 먼저 집으면 드문 지시는 걸 조항이 남지 않는다.
    2026-08-13에 이 순서를 넣어 `수행 주체`가 59.6%에서 21.9%로 내려갔다.

    같은 규칙을 쓰는 데 이유가 있다 -- 기존 합성 1,093건이 이 배분으로 나왔고, 곡선의 세
    번째 점을 앞의 두 점과 같은 자에 올리려면 배분도 같아야 한다.
    """
    by_instruct: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        for instruct in row["allowed"]:
            by_instruct[instruct].append(row)
    # 공급이 적은 지시부터. 각 풀은 그 지시를 걸 수 있는 조항 목록이다.
    pools = sorted(by_instruct.items(), key=lambda item: len(item[1]))
    cursors = {instruct: 0 for instruct, _ in pools}

    plan: list[dict] = []
    clause_used: Counter[tuple[str, str]] = Counter()
    series_used: Counter[str] = Counter()
    while len(plan) < limit:
        progressed = False
        for instruct, members in pools:
            if len(plan) >= limit:
                break
            while cursors[instruct] < len(members):
                row = members[cursors[instruct]]
                cursors[instruct] += 1
                if clause_used[key_of(row)] >= per_clause:
                    continue
                if per_series is not None and series_used[row["series"]] >= per_series:
                    continue
                clause_used[key_of(row)] += 1
                series_used[row["series"]] += 1
                plan.append({**row, "instruct": {"대상": instruct[0], "방향": instruct[1]}})
                progressed = True
                break
        if not progressed:
            break
    return plan


def report(plan: list[dict], limit: int) -> None:
    """배분이 어떻게 됐는지 눈으로 본다. 호출을 쓰기 전에 여기서 걸러야 한다."""
    composites = [p for p in plan if "instruct2" in p]
    print(f"\n  계획 {len(plan)}건 (요청 {limit}건) · 그 중 복합용으로 잡아둔 것 {len(composites)}건")

    targets = Counter(p["instruct"]["대상"] for p in plan)
    print("\n  [지시1의 대상별 비중]   기획서 2.3의 상한은 25%다")
    for target, count in targets.most_common():
        share = count / len(plan)
        flag = "  ← 상한 넘음" if share > 0.25 else ""
        print(f"      {count:>5}  {share:>5.1%}  {target}{flag}")

    print("\n  [지시1의 (대상, 방향)별 비중]")
    pairs = Counter(f'({p["instruct"]["대상"]}, {p["instruct"]["방향"]})' for p in plan)
    for label, count in pairs.most_common():
        print(f"      {count:>5}  {count / len(plan):>5.1%}  {label}")

    print("\n  [계열별]")
    for series, count in Counter(p["series"] for p in plan).most_common():
        print(f"      {count:>5}  {count / len(plan):>5.1%}  {series}")


def write_plans(plan: list[dict], out_dir: Path, prompt: str, concurrency: int,
                timeout: int) -> None:
    """문서별 계획 파일과 실행 스크립트를 쓴다. `plans/archive/retry/`와 같은 모양이다."""
    # 다시 돌리면 앞의 계획을 지우고 새로 쓴다. **다만 이 스크립트가 만든 폴더만.**
    # 표시가 없는 폴더를 지우면 손으로 만든 계획이 날아간다 -- `plans/archive/retry/`는
    # 2026-08-13 복구 실행의 기록이라 다시 만들 수 없다.
    marker = out_dir / ".made_by_plan_py"
    if out_dir.exists() and not marker.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir}에 내용이 있는데 plan.py가 만든 폴더가 아닙니다. "
                         f"다른 --out을 쓰거나 폴더를 손으로 비우세요.")
    out_dir.mkdir(parents=True, exist_ok=True)
    marker.touch()
    for stale in list(out_dir.glob("*.json")) + list(out_dir.glob("run.sh")):
        stale.unlink()

    by_document: dict[str, list[dict]] = defaultdict(list)
    for item in plan:
        by_document[item["document"]].append(item)

    commands = []
    for document in sorted(by_document):
        path = Path(document)
        name = f"{path.parent.name}__{path.stem}.json"
        items = [{k: v for k, v in item.items()
                  if k in ("block_id", "clause", "instruct", "instruct2")}
                 for item in by_document[document]]
        solar.write_json(out_dir / name, items)
        commands.append(
            f'python3 -u training_data/mutate/generate.py "{document}" \\\n'
            f'  --prompt {prompt} --plan "{(out_dir / name).relative_to(REPOSITORY_DIR)}"'
            f' --concurrency {concurrency}')

    script = out_dir / "run.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# training_data/mutate/plan.py가 만들었다. 손으로 고치지 말고 다시 만든다.\n"
        "#\n"
        "# 1패스 -- 계획 전체에 v1.2를 한 번 건다. `generate.py`는 수정하지 않은 것이고,\n"
        "# 계획에 실린 `instruct2`는 이 패스에서 쓰이지 않는다(2패스가 읽는다).\n"
        "#\n"
        "# 시간 초과 기본값 180초는 1,000건 넘는 실행에 안 맞는다 -- 2026-08-13에 227건을\n"
        "# TimeoutError로 잃었다. 동시 요청도 16에서 8로 내린다(많을수록 응답이 늦어졌다).\n"
        "set -u\n"
        # 이 스크립트는 mutate/plans/<이름>/run.sh 이므로 저장소 뿌리까지 네 칸이다.
        'cd "$(dirname "$0")/../../../.." || exit 1\n'
        f"export SOLAR_TIMEOUT_SECONDS={timeout}\n\n"
        + "\n\n".join(commands) + "\n",
        encoding="utf-8")
    script.chmod(0o755)
    print(f"\n  계획 파일 {len(by_document)}개와 run.sh: {out_dir.relative_to(REPOSITORY_DIR)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True,
                    help="계획 파일을 쓸 폴더 (mutate/ 기준 상대경로도 됨)")
    ap.add_argument("--limit", type=int, required=True, help="계획 총량")
    ap.add_argument("--composite", type=int, default=0,
                    help="`적용 범위` 축 복합용으로 미리 잡아둘 조항 수. 2패스가 이것을 쓴다")
    ap.add_argument("--per-clause", type=int, default=2,
                    help="조항 하나에 걸 지시 수. 기존 합성 1,093건과 같은 값이 기본이다")
    ap.add_argument("--per-series", type=int, default=None, help="계열당 상한")
    ap.add_argument("--series", nargs="+", default=None, help="이 계열만 쓴다")
    ap.add_argument("--prompt", default="v1.2")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--root", type=Path, default=REPOSITORY_DIR / "data" / "raw_collection")
    ap.add_argument("--dry-run", action="store_true", help="배분만 보고 파일은 안 쓴다")
    args = ap.parse_args()

    out_dir = args.out if args.out.is_absolute() else (HERE / args.out)

    print(f"씨앗 {args.root.relative_to(REPOSITORY_DIR)}")
    rows = collect(args.root, set(args.series) if args.series else None)
    if not rows:
        raise SystemExit("조항이 없습니다.")

    print(f"\n  [복합용으로 미리 잡아두기]  공급이 적은 조합부터")
    composites, lines = earmark_composites(rows, args.composite)
    for line in lines:
        print(line)

    reserved = {key_of(c) for c in composites}
    remaining = [r for r in rows if key_of(r) not in reserved]
    singles = allocate_singles(remaining, args.limit - len(composites),
                               args.per_clause, args.per_series)

    plan = composites + singles
    if len(plan) < args.limit:
        print(f"\n  !  요청 {args.limit}건인데 {len(plan)}건만 잡혔다. 공급이 모자란다.")
    report(plan, args.limit)

    if args.dry_run:
        print("\n--dry-run 이므로 파일을 쓰지 않았습니다.")
        return
    write_plans(plan, out_dir, args.prompt, args.concurrency, args.timeout)


if __name__ == "__main__":
    main()
