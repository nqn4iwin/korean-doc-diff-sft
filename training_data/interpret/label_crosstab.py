"""역할 B의 지시와 역할 A가 낸 라벨을 맞대어 교차표를 낸다.

**BM5는 "지시한 라벨이 셜록 라벨에 들어 있나"만 본다.** 어긋난 것이 *어디로 흘렀는지*는
안 보인다. 2026-08-12에 `(절차·요건, 늘었다)`가 0/12였을 때, 셜록이 그것을 일관되게
`새로 생겼다`로 읽고 있다는 것을 교차표로 찾아 지시 이름을 갈아 10/12가 됐다. 그 일을
다시 할 수 있게 도구로 만든다.

**읽는 법이 처방을 가른다.**

    한 지시의 답이 흩어진다   모리아티가 그 지시로 무엇을 해야 하는지 모른다
                              -> 프롬프트에 정의와 예시를 준다
    한 라벨로 몰린다          우리가 붙인 이름이 틀렸다
                              -> 지시 이름을 그 라벨로 간다

**대상과 방향을 갈라서 본다.** 대상은 맞고 방향만 어긋나는 것이 가장 흔한 실패이고,
그것은 이름을 갈면 풀리는 종류다. 대상부터 틀리면 자리를 못 찾은 것이라 다른 문제다.

사용:
    python3 training_data/interpret/label_crosstab.py training_data/mutate/runs/<실행> ...
    python3 training_data/interpret/label_crosstab.py 'training_data/mutate/runs/*__plan_*'
"""
from __future__ import annotations

import argparse
import glob
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as _run  # noqa: E402


def load(patterns: list[str]) -> list[dict]:
    """실행 디렉터리 여럿에서 pair를 모은다. 글로브도 받는다."""
    pairs, seen = [], set()
    for pattern in patterns:
        matches = glob.glob(pattern) or [pattern]
        for match in matches:
            path = Path(match)
            path = path if path.is_absolute() else (REPOSITORY_DIR / path)
            target = path / "pairs.json" if path.is_dir() else path
            if not target.exists() or target in seen:
                if not target.exists():
                    print(f"!  건너뜀 (pairs.json 없음): {path}")
                continue
            seen.add(target)
            pairs.extend(solar.read_json(target))
    return pairs


def instructed(pair: dict) -> tuple[str, str] | None:
    given = pair.get("instruct") or {}
    target, direction = given.get("대상"), given.get("방향")
    return (target, direction) if target and direction else None


def judged(pair: dict) -> tuple[list[tuple[str, str]], str]:
    """셜록이 낸 라벨과, 라벨이 없다면 그 사유.

    **라벨이 없는 이유가 넷이고 처방이 다 다르다.** 하나로 뭉치면 안 된다.

        안 바꿈       BM2=0. 모리아티가 조항을 그대로 뒀다 -> 걸 자리가 없는 지시다
        호출 실패     생성이나 판정 호출이 죽었다 -> 재실행하면 된다
        파싱 실패     JSON이 깨졌다 -> 프롬프트 문제다
        negative      셜록이 실질 변경이 아니라고 봤다 -> 변경이 너무 작다
    """
    labels = pair.get("judge_labels")
    if labels:
        return [(str(x.get("대상")), str(x.get("방향")))
                for x in labels if isinstance(x, dict)], ""
    if pair.get("error") or pair.get("judge_error"):
        return [], "(호출 실패)"
    scores = pair.get("scores") or {}
    if not pair.get("judge_raw"):
        # BM2=0이면 generate.py가 판정을 아예 안 부른다. 바꾼 것이 없기 때문이다.
        return [], "(안 바꿈 BM2=0)" if scores.get("BM2") == 0 else "(판정 안 함)"
    parsed = _run.parse_output(pair.get("judge_raw") or "")
    if parsed is None:
        return [], "(파싱 실패)"
    if str(parsed.get("judgement", "")).strip() == "negative":
        return [], "(셜록 negative)"
    return [], "(라벨 빔)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", help="generate.py 실행 디렉터리 (글로브 가능)")
    ap.add_argument("--min", type=int, default=1, help="이 건수 미만인 지시는 표에서 접는다")
    args = ap.parse_args()

    pairs = load(args.runs)
    if not pairs:
        raise SystemExit("pair를 하나도 못 읽었습니다.")

    rows: dict[tuple[str, str], Counter] = defaultdict(Counter)
    stats: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for pair in pairs:
        want = instructed(pair)
        if want is None:
            continue
        got, blank = judged(pair)
        stat = stats[want]
        stat["건수"] += 1
        if not got:
            stat["라벨없음"] += 1
            rows[want][blank] += 1
            continue
        if want in got:
            stat["BM5"] += 1
        if want[0] in {t for t, _ in got}:
            stat["BM5a"] += 1
        for pair_label in got:
            rows[want][f"{pair_label[0]} / {pair_label[1]}"] += 1

    print(f"pair {len(pairs)}건 · 지시 {len(stats)}종\n")
    print(f"{'지시':<26}{'건수':>5}{'BM5':>7}{'BM5a':>7}  진단")
    print("-" * 96)
    for want, stat in sorted(stats.items(), key=lambda kv: -kv[1]["건수"]):
        n = stat["건수"]
        bm5, bm5a = stat["BM5"] / n, stat["BM5a"] / n
        top, top_n = rows[want].most_common(1)[0]
        # 대상은 맞는데 방향이 어긋나고, 그 어긋남이 한 라벨로 몰리면 이름 문제다.
        if bm5a - bm5 >= 0.3 and top_n / max(sum(rows[want].values()), 1) >= 0.5:
            note = f"이름 의심 -> 대부분 `{top}`"
        elif bm5 < 0.5 and bm5a < 0.5:
            note = "자리를 못 찾음"
        elif bm5 < 0.5:
            note = f"방향 어긋남 -> `{top}`"
        else:
            note = ""
        print(f"{want[0] + ' / ' + want[1]:<26}{n:>5}{bm5 * 100:>6.0f}%{bm5a * 100:>6.0f}%  {note}")

    print("\n\n=== 지시 -> 셜록이 낸 라벨 ===")
    for want, counts in sorted(rows.items(), key=lambda kv: -stats[kv[0]]["건수"]):
        if stats[want]["건수"] < args.min:
            continue
        total = sum(counts.values())
        print(f"\n{want[0]} / {want[1]}   (지시 {stats[want]['건수']}건 -> 라벨 {total}개)")
        for label, count in counts.most_common(6):
            mark = " <- 지시" if label == f"{want[0]} / {want[1]}" else ""
            print(f"    {count:>4}  {count / total * 100:5.1f}%  {label}{mark}")


if __name__ == "__main__":
    main()
