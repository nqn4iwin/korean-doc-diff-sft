"""`annotate.py`가 붙인 해석에서 학습 레코드로 쓸 것만 골라 JSONL로 내보낸다.

**형식을 여기서 정하지 않는다.** 학습 레코드에 `impacts` 배열을 넣을지, 규칙서를 넣을지는
아직 안 정했다(`training_data/설계_메모.md` 2절·4절). 그래서 네 필드를 모두 담아 내보내고,
학습 쪽에서 필요 없는 것을 자른다. **빼는 것은 문자열을 자르는 일이지만 없는 것은 만들 수
없다** -- 그 원칙이 교사 데이터에 배열을 넣어 둔 이유이고, 여기서도 같다.

거르는 기준은 다섯이다. 셋은 출력이 깨진 것이고 둘은 품질이다.

    파싱 실패        judgement가 비어 있다. JSON이 안 나왔다
    빈 배열          positive인데 impacts가 없다. 영향 대상을 아예 안 냈다
    어휘 위반        대상 7종·방향 5종 밖의 말을 썼다(AM2)
    주체 흘림        impacts에 적은 주체가 문장에서 사라졌다
    조문제목 접두     한쪽에만 조문 제목이 붙었을 뿐 내용이 같다

**홀드아웃은 `--exclude-series`로 뺀다.** 한 실행에 학습분과 채점분이 같이 들어 있어도
되고(2026-08-11 실행에 `mof` 37건이 그랬다), 나갈 때 가르면 된다. 빼는 쪽을 여기서만
막으면 안 된다 -- `model_train`의 `HOLDOUT_SERIES`가 같은 이름을 함께 들고 있어야 한다.

**주체 흘림 판정은 `run.subject_survives()`다. AM8과 같은 함수를 쓴다.** 원래 이 파일에만
어절 겹침 판정이 있고 AM8은 문자열을 통째로 대조해서, 채점을 통과한 레코드가 여기서
버려지는 일이 생길 수 있었다. 2026-08-13에 함수를 `run.py`로 옮겨 하나로 만들었다.
경위는 `CHANGELOG.md`.

라벨 중복(AM3)은 거르지 않고 중복만 걷어낸다. 같은 `(대상, 방향)`이 두 번 나온 것은 뜻이
달라지지 않으므로 버릴 이유가 없다.

사용:
    python training_data/interpret/export.py runs/<실행 디렉터리>
    python training_data/interpret/export.py runs/<...> --out /경로/train.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as _run  # noqa: E402

TARGETS = ("기한·시점", "수치·기준", "적용 범위", "수행 주체",
           "절차·요건", "제출물·기재사항", "명칭")
DIRECTIONS = ("늘었다", "줄었다", "다른 값", "새로 생겼다", "없어졌다")

# 주체 대조는 run.py의 AM8과 **같은 함수여야 한다.** 여기서 버리는 기준과 채점하는
# 기준이 다르면, 채점에서 통과한 레코드가 내보내기에서 버려지는 일이 생긴다.
subject_survives = _run.subject_survives


# **한쪽에만 붙은 조문 제목.** `제4조(전문기관) ① ...` ↔ `① ...`처럼 같은 조항인데
# 제목이 블록에 붙었다 안 붙었다 하는 차이이고 개정이 아니다. `classify_diff.py`가 실질
# 변경으로 넘기고 셜록은 negative로 맞게 판정하지만, **내용을 안 읽고도 맞힐 수 있는
# 공짜 negative라 negative로 도망갈 유인만 키운다.** 1차 스윕에서 70개 중 43개가 "무조건
# negative"로 붕괴한 자리다. 2026-08-19에 998묶음 중 129건을 셌다.
#
# **기존 605건은 이 규칙 전에 뽑혔고 그대로 둔다(아티팩트 57건 포함).** 605 -> 1,655 ->
# 3,000 곡선의 가운데 점이 그 데이터로 측정됐다. 2026-08-11 실행을 다시 export하면 605가
# 아니라 548이 나오므로 **그 파일은 다시 만들지 않는다.**
TITLE_PREFIX = re.compile(r"^제\s*\d+조(의\d+)?\s*\([^)]*\)\s*")


def title_prefix_only(before: str, after: str) -> bool:
    """한쪽 앞에 붙은 조문 제목을 떼면 나머지가 같은가.

    양쪽 다 제목이 있고 제목만 바뀐 경우(`제5조(위원회)` -> `제5조(운영위원회)`)는 진짜
    `명칭` 변경이므로 여기서 걸리면 안 된다. 한쪽에만 제목이 있을 때만 참이 되도록
    **뗀 나머지가 상대편 전체와 같은지**를 본다. 코퍼스에서 제목만 바뀐 묶음은 0건이다.
    """
    for head, tail in ((after, before), (before, after)):
        match = TITLE_PREFIX.match(head)
        if match and head[match.end():].strip() == tail.strip():
            return True
    return False


def verdict(record: dict) -> str:
    """이 레코드를 왜 버리는가. 쓸 만하면 빈 문자열."""
    judgement = record.get("judgement") or ""
    if judgement not in ("positive", "negative"):
        return "파싱 실패"

    if title_prefix_only(record.get("before") or "", record.get("after") or ""):
        return "조문제목 접두"

    labels = record.get("labels") or []
    pairs = [(x.get("대상"), x.get("방향")) for x in labels]
    if any(t not in TARGETS or d not in DIRECTIONS for t, d in pairs):
        return "어휘 위반"

    impacts = record.get("impacts") or []
    sentence = record.get("direct_impact") or ""

    if judgement == "negative":
        # negative는 영향 칸이 비어 있는 것이 정답이다. 판정은 negative로 해놓고 문장을
        # 쓴 것은 자기 안에서 앞뒤가 안 맞는 출력이라, 학습 레코드로 쓰면 "실질 변경이
        # 아닌데 영향은 있다"를 가르치게 된다.
        return "" if not impacts and not sentence.strip() else "negative인데 영향 있음"

    if not impacts:
        return "빈 배열"

    if not all(subject_survives(i.get("주체") or "", sentence) for i in impacts):
        return "주체 흘림"
    return ""


def to_record(record: dict) -> dict:
    """학습 쪽에 넘길 모양. 원문과 해석 넷, 그리고 어디서 왔는지."""
    seen, labels = set(), []
    for label in record.get("labels") or []:
        key = (label.get("대상"), label.get("방향"))
        if key in seen:          # AM3 중복은 버리지 않고 걷어낸다
            continue
        seen.add(key)
        labels.append(label)
    return {
        "id": record["id"],
        "series": record["series"],
        "before_id": record["before_id"], "before": record["before"],
        "after_id": record["after_id"], "after": record["after"],
        "judgement": record["judgement"],
        "labels": labels,
        "impacts": record.get("impacts") or [],
        "direct_impact": record.get("direct_impact") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path, help="annotate.py가 남긴 실행 디렉터리")
    ap.add_argument("--out", type=Path, default=None,
                    help="내보낼 JSONL 경로 (기본: 실행 디렉터리 안 train.jsonl)")
    ap.add_argument("--exclude-series", action="append", default=[],
                    help="학습 레코드에서 뺄 계열. 홀드아웃을 가를 때 쓴다. 여러 번 준다")
    ap.add_argument("--only-series", action="append", default=[],
                    help="이 계열만 내보낸다. 홀드아웃만 따로 뽑을 때 쓴다")
    args = ap.parse_args()
    if args.exclude_series and args.only_series:
        raise SystemExit("--exclude-series와 --only-series는 같이 못 쓴다")

    run_dir = args.run_dir if args.run_dir.is_absolute() else (HERE / args.run_dir)
    records = solar.read_json(run_dir / "records.json")
    out_path = args.out or (run_dir / "train.jsonl")

    if args.only_series:
        records = [r for r in records if r.get("series") in set(args.only_series)]
    elif args.exclude_series:
        records = [r for r in records if r.get("series") not in set(args.exclude_series)]

    kept, dropped = [], Counter()
    for record in records:
        reason = verdict(record)
        if reason:
            dropped[reason] += 1
            continue
        kept.append(to_record(record))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in kept:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    judgements = Counter(r["judgement"] for r in kept)
    series = Counter(r["series"] for r in kept)
    solar.write_json(run_dir / "export_summary.json", {
        "source_run": run_dir.name,
        "excluded_series": args.exclude_series,
        "only_series": args.only_series,
        "input": len(records),
        "kept": len(kept),
        "dropped": dict(dropped),
        "judgements": dict(judgements),
        "series": dict(sorted(series.items(), key=lambda kv: -kv[1])),
        "subject_kept_ratio": _run.SUBJECT_KEPT,
    })

    print(f"입력 {len(records)}건 → 내보냄 {len(kept)}건")
    for reason, count in dropped.most_common():
        print(f"  버림  {reason:<10} {count:>4}")
    print()
    for judgement, count in judgements.most_common():
        print(f"  {judgement:<10} {count:>4}")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
