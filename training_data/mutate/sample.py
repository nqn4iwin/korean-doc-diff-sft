"""옛 실행에서 표본을 뽑아 `generate.py --plan`에 먹일 계획 파일을 만든다.

교사 모델이나 프롬프트를 바꾼 뒤 좋아졌는지 보려면 **같은 조항 × 같은 지시**를 다시
돌려야 한다. 계획을 새로 세우면 조항이 달라져 두 실행을 맞댈 수 없고, 평균 두 개만
비교하게 된다. 같은 건을 짝지으면 뒤집힌 건수를 직접 셀 수 있어 훨씬 예민하다 --
2026-08-12에 60건으로 BM5가 18건 좋아지고 3건 나빠진 것을 이렇게 봤다.

**지시 구성을 보존해서 뽑는다.** 그냥 무작위로 자르면 드문 지시가 통째로 빠진다.
`(기한·시점, 다른 값)`은 180건에 2건뿐이라 1/3만 가져오면 0건이 되기도 한다. 그래서
지시별로 나눠 비율대로 뽑되, 배당이 그 지시의 실제 건수보다 크면 전수로 가져간다.

**씨앗을 고정한다.** 같은 명령이 언제나 같은 표본을 낸다.

**다만 재현해야 할 것은 뽑는 절차가 아니라 뽑힌 결과다.** 계획 파일을 `plans/`에 남기고
그것을 계속 쓴다. 배당 규칙을 나중에 손대면 같은 씨앗이라도 다른 표본이 나오고, 그러면
옛 판본과 비교할 수 없게 된다. 실제로 `plans/sample60.json`은 2026-08-12에 손으로 정한
배당(20/20/12/4/2/2)으로 뽑은 것이라 아래 규칙으로는 다시 안 나온다 -- **그 파일이
기준선이므로 파일을 쓰고, 이 스크립트는 새 표본을 뽑을 때 쓴다.**

사용:
    python3 training_data/mutate/sample.py RUN_DIR --size 60
    python3 training_data/mutate/sample.py RUN_DIR --size 120 --out plans/sample120.json
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def draw(pairs: list[dict], size: int, seed: int) -> list[dict]:
    """지시 구성을 보존해 `size`건을 뽑는다."""
    strata: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for record in pairs:
        strata[(record["instruct"]["대상"], record["instruct"]["방향"])].append(record)
    # 층 안의 순서를 block_id로 고정한다. 파일에 실린 순서에 기대면 재현되지 않는다.
    for group in strata.values():
        group.sort(key=lambda r: r["block_id"])

    rng = random.Random(seed)
    total = len(pairs)
    picked: list[dict] = []
    # 드문 층부터 배당한다. 비율대로만 자르면 2건짜리 지시가 1건이 되어 사실상 사라지므로,
    # 층이 작으면 전수로 가져가고 남은 자리를 큰 층이 나눠 갖는다.
    for key in sorted(strata, key=lambda k: len(strata[k])):
        group = strata[key]
        quota = max(min(len(group), 2), round(size * len(group) / total))
        quota = min(quota, len(group), max(0, size - len(picked)))
        picked += group if quota >= len(group) else rng.sample(group, quota)

    picked.sort(key=lambda r: (r["instruct"]["대상"], r["instruct"]["방향"], r["block_id"]))
    return picked


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path, help="generate.py가 만든 runs/ 아래 디렉터리")
    ap.add_argument("--size", type=int, default=60, help="뽑을 건수")
    ap.add_argument("--seed", type=int, default=20260812,
                    help="고정 씨앗. 바꾸면 다른 60건이 나와 옛 기준선과 못 맞댄다")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    pairs = json.loads((args.run_dir / "pairs.json").read_text(encoding="utf-8"))
    picked = draw(pairs, args.size, args.seed)
    plan = [{"block_id": r["block_id"], "clause": r["clause"], "instruct": r["instruct"]}
            for r in picked]

    out = args.out or (HERE / "runs" / f"sample{len(plan)}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"표본 {len(plan)}건  (씨앗 {args.seed})  저장: {out}")
    origin = collections.Counter((r["instruct"]["대상"], r["instruct"]["방향"]) for r in pairs)
    got = collections.Counter((r["instruct"]["대상"], r["instruct"]["방향"]) for r in picked)
    print("\n지시 구성 (표본 / 원본)")
    for key in sorted(origin, key=lambda k: -origin[k]):
        print(f"  {got[key]:>3} / {origin[key]:<3}   {key}")


if __name__ == "__main__":
    main()
