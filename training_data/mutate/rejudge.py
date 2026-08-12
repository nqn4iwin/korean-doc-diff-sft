"""이미 뽑아 놓은 개정문을 **다시 판정만** 한다. 생성 호출은 하지 않는다.

교사 모델을 바꾸면 BM5가 두 가지 이유로 움직인다 -- 생성이 좋아졌거나, 판정이 달라졌거나.
같은 실행에서 둘을 함께 바꾸면 어느 쪽인지 가릴 수 없다. 그래서 칸을 셋으로 나눈다.

              옛 판정            새 판정
    옛 생성    이미 있다          <- 이 파일이 채운다 (생성 콜 0)
    새 생성    --                generate.py --plan

가운데 칸이 있으면 `옛 생성/옛 판정`과 비교해 **판정 모델만의 효과**가 나오고,
`새 생성/새 판정`과 비교해 **생성 모델만의 효과**가 나온다.

판정은 `run.py`의 `round_trip`을 그대로 쓴다. BM5의 정의(완전일치가 아니라 포함)가 한
군데에만 있어야 두 실행의 점수를 맞댈 수 있기 때문이다.

사용:
    python training_data/mutate/rejudge.py RUN_DIR
    python training_data/mutate/rejudge.py RUN_DIR --plan runs/sample60.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mutate_run", HERE / "run.py")
_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run)


def key(record: dict) -> tuple[str, str, str]:
    """한 건을 가리키는 이름. 조항과 지시가 같으면 같은 건으로 본다."""
    return (record["block_id"], record["instruct"]["대상"], record["instruct"]["방향"])


def old_bm5(record: dict) -> int:
    """옛 실행의 BM5를 꺼낸다.

    채점 항목 이름을 `M1~M7`에서 `BM1~BM7`로 바꾼 것이 2026-08-10 실행보다 **뒤**라,
    그때 저장된 `pairs.json`은 아직 옛 이름으로 남아 있다. 이 파일이 하려는 일이 바로
    그 옛 실행과 맞대는 것이므로 두 이름을 다 읽어야 한다.
    """
    scores = record["scores"]
    return scores["BM5"] if "BM5" in scores else scores["M5"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path, help="다시 판정할 pairs.json이 있는 실행 폴더")
    ap.add_argument("--plan", type=Path,
                    help="이 계획에 든 건만 판정한다. 없으면 전부 한다")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    pairs = json.loads((args.run_dir / "pairs.json").read_text(encoding="utf-8"))

    # 판정할 것이 없는 건은 거른다. 생성이 실패했거나 BM2에서 떨어져 개정문이 비어 있으면
    # 원래 실행에서도 왕복 검증을 돌리지 않았다(`generate.py`의 `if after and marked["BM2"]`).
    # 여기서 억지로 돌리면 옛 실행에 없는 칸이 생겨 짝이 어긋난다.
    todo = [p for p in pairs if p.get("after")]
    if args.plan:
        wanted = {key(p) for p in json.loads(args.plan.read_text(encoding="utf-8"))}
        todo = [p for p in todo if key(p) in wanted]
        missing = wanted - {key(p) for p in todo}
        if missing:
            print(f"경고: 계획의 {len(missing)}건이 이 실행에 없거나 개정문이 비었습니다")

    print(f"실행    {args.run_dir.name}")
    print(f"  판정 대상    {len(todo)}건 / 전체 {len(pairs)}건  (생성 호출 없음)")
    if not todo:
        raise SystemExit("판정할 것이 없습니다.")

    judge = Template((HERE.parent / "interpret" / "prompts"
                      / f"{_run.JUDGE_PROMPT}.txt").read_text(encoding="utf-8"))
    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))
    model = os.environ.get("SOLAR_MODEL")
    print(f"  판정 모델    {model}  (역할 A {_run.JUDGE_PROMPT})")

    def work(numbered: tuple[int, dict]) -> dict:
        index, old = numbered
        try:
            trip = _run.round_trip(url, api_key, timeout, judge, old, old["after"])
        except Exception as error:
            print(f"  [{index}/{len(todo)}] x 판정 실패 {old['block_id']}")
            return {**{k: old[k] for k in ("block_id", "clause", "instruct", "after")},
                    "judge_error": solar.safe_error(error)}
        was, now = old_bm5(old), trip["BM5"]
        flip = "  " if was == now else ("↑" if now else "↓")
        print(f'  [{index}/{len(todo)}] BM5 {was}->{now} {flip}  '
              f'({old["instruct"]["대상"]}, {old["instruct"]["방향"]})  {old["block_id"]}')
        return {**{k: old[k] for k in ("block_id", "clause", "instruct", "after")},
                "BM5_old": was, "BM5_new": now,
                "judge_labels_old": old.get("judge_labels"),
                "judge_labels_new": trip["judge_labels"],
                "judge_judgement_new": trip["judge_judgement"],
                "judge_raw_new": trip["judge_raw"]}

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(work, enumerate(todo, 1)))

    graded = [r for r in results if "BM5_new" in r]
    out_dir = HERE / "runs" / f"{solar.timestamp()}__rejudge__{args.run_dir.name[:24]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 짝지어 놓고 어느 쪽으로 얼마나 움직였는지 센다. 평균 두 개를 비교하는 것보다
    # 예민하다 -- 같은 조항에서 뒤집힌 건수를 직접 세기 때문이다.
    moved = Counter()
    for r in graded:
        moved[(r["BM5_old"], r["BM5_new"])] += 1
    summary = {
        "source_run": str(args.run_dir), "plan": str(args.plan) if args.plan else None,
        "judge_model": model, "judge_prompt": _run.JUDGE_PROMPT,
        "judged": len(graded), "failures": len(results) - len(graded),
        "BM5_old": round(sum(r["BM5_old"] for r in graded) / len(graded), 3) if graded else None,
        "BM5_new": round(sum(r["BM5_new"] for r in graded) / len(graded), 3) if graded else None,
        "moved": {f"{a}->{b}": n for (a, b), n in sorted(moved.items())},
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "rejudged.json", results)

    print()
    print(f'  BM5  옛 판정 {summary["BM5_old"]:.1%}  ->  새 판정 {summary["BM5_new"]:.1%}')
    print(f'    그대로 통과 {moved[(1, 1)]}   그대로 실패 {moved[(0, 0)]}')
    print(f'    새로 통과   {moved[(0, 1)]}   새로 실패   {moved[(1, 0)]}')
    print(f"  저장: {out_dir.relative_to(REPOSITORY_DIR)}")


if __name__ == "__main__":
    main()
