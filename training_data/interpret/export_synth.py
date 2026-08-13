"""`mutate/generate.py`가 만든 합성 pair에서 학습 레코드를 뽑는다.

**역할 A를 다시 부르지 않는다.** 생성할 때 왕복 검증(BM5)을 하느라 역할 A를 이미 한 번
부르고, `mutate/run.py`의 `round_trip()`이 그 출력을 `judge_raw`에 통째로 남긴다. 그것이
곧 A-2의 해석이다. 확인한 것 넷이다.

    프롬프트 파일   `interpret/prompts/v2.2.txt` -- `annotate.py`와 같은 파일
    온도            0.2 -- `annotate.py`의 INTERPRET_TEMPERATURE와 같다
    치환 자리       v2.2에는 $before_id $before $after_id $after 넷뿐이다. round_trip이
                    넘기는 given_labels는 자리가 없어 무시되므로 프롬프트가 완전히 같다
    실물            60건 실행의 pairs.json 60건 전부에 네 필드가 들어 있다

**그래서 생성 2,900회 한 번이면 끝나고 해석 1,461회가 통째로 빠진다.**

거르는 기준은 `export.py`의 `verdict()`를 그대로 쓴다. 같은 기준이어야 실제 pair에서 온
레코드와 합성에서 온 레코드가 같은 잣대로 걸러진다.

**라벨은 버킷과 무관하게 역할 A가 낸 것(`judge_labels`)을 쓴다.** `학습 후보`는 BM5를
통과했으니 지시와 같고, `라벨 교체 후보`는 `docs/학습데이터_생성_프로세스.md` 3-5절이
"역할 A가 준 라벨로 갈아끼운다"고 정해뒀다. 양쪽 다 결론이 같고, 학습 데이터의 정답이
역할 A의 해석이라는 3-0절과도 맞는다.

**`series`에 `synth:` 접두를 붙인다.** 학습·평가 분할을 계열 단위로 하므로 합성과 실제를
가를 수 있어야 한다. 뒤에 붙는 이름은 씨앗이 된 원천의 계열이라, 같은 계열의 실제 pair가
평가로 빠지면 그 계열의 합성도 함께 뺄 수 있다.

사용:
    python3 training_data/interpret/export_synth.py training_data/mutate/runs/<실행>
    python3 training_data/interpret/export_synth.py <실행1> <실행2> ... --out train_synth.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import export as _export  # noqa: E402
import run as _run  # noqa: E402


def series_of(summary: dict) -> str:
    """씨앗이 된 원천의 계열. `data/raw_collection/<계열>/<파일>`의 가운데다."""
    document = summary.get("document") or ""
    parts = Path(document).parts
    return parts[-2] if len(parts) >= 2 else (Path(document).stem or "unknown")


def to_source_record(pair: dict, series: str, index: int) -> dict | None:
    """pairs.json 한 건을 `export.verdict()`가 읽는 모양으로 바꾼다."""
    raw = pair.get("judge_raw")
    if not raw:
        return None
    parsed = _run.parse_output(raw)
    if parsed is None:
        # judgement를 비워 두면 verdict()가 `파싱 실패`로 세어 준다.
        parsed = {}
    block = pair.get("block_id") or f"item{index:05d}"
    return {
        "id": f"synth:{series}:{block}#{index}",
        "series": f"synth:{series}",
        "before_id": f"{block}(원문)", "before": pair.get("clause") or "",
        "after_id": f"{block}(개정)", "after": pair.get("after") or "",
        "judgement": parsed.get("judgement"),
        "labels": parsed.get("labels") or [],
        "impacts": parsed.get("impacts") or [],
        "direct_impact": parsed.get("direct_impact") or "",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dirs", type=Path, nargs="+",
                    help="generate.py가 남긴 실행 디렉터리 (여럿 가능)")
    ap.add_argument("--out", type=Path, default=None,
                    help="내보낼 JSONL 경로 (기본: training_data/interpret/train_synth.jsonl)")
    args = ap.parse_args()

    out_path = args.out or (HERE / "train_synth.jsonl")
    kept, dropped, buckets, sources = [], Counter(), Counter(), Counter()
    total = 0

    for run_dir in args.run_dirs:
        run_dir = run_dir if run_dir.is_absolute() else (REPOSITORY_DIR / run_dir)
        pairs_path = run_dir / "pairs.json"
        if not pairs_path.exists():
            print(f"!  건너뜀 (pairs.json 없음): {run_dir}")
            continue
        summary = solar.read_json(run_dir / "summary.json")
        series = series_of(summary)
        pairs = solar.read_json(pairs_path)

        for index, pair in enumerate(pairs, 1):
            total += 1
            if pair.get("error") or pair.get("judge_error"):
                dropped["호출 실패"] += 1
                continue
            record = to_source_record(pair, series, index)
            if record is None:
                dropped["판정 없음"] += 1
                continue
            reason = _export.verdict(record)
            if reason:
                dropped[reason] += 1
                continue
            kept.append(_export.to_record(record))
            buckets[pair.get("bucket") or "(없음)"] += 1
            sources[series] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in kept:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    judgements = Counter(r["judgement"] for r in kept)
    label_counts = Counter(len(r["labels"]) for r in kept)
    targets = Counter(x.get("대상") for r in kept for x in r["labels"])
    solar.write_json(out_path.with_suffix(".summary.json"), {
        "runs": [str(d) for d in args.run_dirs],
        "input": total, "kept": len(kept), "dropped": dict(dropped),
        "judgements": dict(judgements), "buckets": dict(buckets),
        "series": dict(sources.most_common()),
        "labels_per_record": dict(sorted(label_counts.items())),
        "targets": dict(targets.most_common()),
    })

    print(f"입력 {total}건 → 내보냄 {len(kept)}건  ({out_path})")
    for reason, count in dropped.most_common():
        print(f"  버림  {reason:<12} {count:>5}")
    print()
    multi = sum(v for k, v in label_counts.items() if k >= 2)
    if kept:
        print(f"  복합(라벨 2개 이상) {multi}/{len(kept)} = {multi / len(kept) * 100:.1f}%")
    for target, count in targets.most_common():
        print(f"  {target:<14} {count:>5}  {count / max(sum(targets.values()), 1) * 100:5.1f}%")


if __name__ == "__main__":
    main()
