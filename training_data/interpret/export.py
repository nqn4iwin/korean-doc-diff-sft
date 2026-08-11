"""`annotate.py`가 붙인 해석에서 학습 레코드로 쓸 것만 골라 JSONL로 내보낸다.

**형식을 여기서 정하지 않는다.** 학습 레코드에 `impacts` 배열을 넣을지, 규칙서를 넣을지는
아직 안 정했다(`training_data/설계_메모.md` 2절·4절). 그래서 네 필드를 모두 담아 내보내고,
학습 쪽에서 필요 없는 것을 자른다. **빼는 것은 문자열을 자르는 일이지만 없는 것은 만들 수
없다** -- 그 원칙이 교사 데이터에 배열을 넣어 둔 이유이고, 여기서도 같다.

거르는 기준은 넷이다. 셋은 출력이 깨진 것이고 하나는 품질이다.

    파싱 실패        judgement가 비어 있다. JSON이 안 나왔다
    빈 배열          positive인데 impacts가 없다. 영향 대상을 아예 안 냈다
    어휘 위반        대상 7종·방향 5종 밖의 말을 썼다(AM2)
    주체 흘림        impacts에 적은 주체가 문장에서 사라졌다

**주체 흘림은 AM8s를 그대로 쓰지 않는다.** AM8s는 주체 문자열이 문장에 통째로 들어 있는지만
보므로, 모델이 `연구개발성과의 활용 촉진을 수행하는 기관`을 문장에서 `촉진을 수행하는 기관`
으로 줄여 쓰면 실패로 잡는다. 2026-08-11 실행에서 AM8s 실패 109건 중 56건이 그런 오탐이었다.
그래서 어절 단위로 다시 재어, 절반 이상이 문장에 남아 있으면 통과로 본다.

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

TARGETS = ("기한·시점", "수치·기준", "적용 범위", "수행 주체",
           "절차·요건", "제출물·기재사항", "명칭")
DIRECTIONS = ("늘었다", "줄었다", "다른 값", "새로 생겼다", "없어졌다")

# 주체를 문장에서 찾을 때 쓰는 어절 하한. 한 글자는 우연히 걸리므로 뺀다.
SUBJECT_WORD = re.compile(r"[\s,·ㆍ()]+")
SUBJECT_KEPT = 0.5


def subject_survives(subject: str, sentence: str) -> bool:
    """주체가 문장에 남아 있는가. 통째로 있으면 참, 줄여 썼으면 어절 비율로 본다."""
    if not subject:
        return True
    if subject in sentence:
        return True
    words = [w for w in SUBJECT_WORD.split(subject) if len(w) >= 2]
    if not words:
        return False
    return sum(1 for w in words if w in sentence) / len(words) >= SUBJECT_KEPT


def verdict(record: dict) -> str:
    """이 레코드를 왜 버리는가. 쓸 만하면 빈 문자열."""
    judgement = record.get("judgement") or ""
    if judgement not in ("positive", "negative"):
        return "파싱 실패"

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
    args = ap.parse_args()

    run_dir = args.run_dir if args.run_dir.is_absolute() else (HERE / args.run_dir)
    records = solar.read_json(run_dir / "records.json")
    out_path = args.out or (run_dir / "train.jsonl")

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
        "input": len(records),
        "kept": len(kept),
        "dropped": dict(dropped),
        "judgements": dict(judgements),
        "series": dict(sorted(series.items(), key=lambda kv: -kv[1])),
        "subject_kept_ratio": SUBJECT_KEPT,
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
