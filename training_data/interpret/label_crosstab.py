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


def series_of(document: str) -> str:
    """`data/raw_collection/<계열>/<파일>`의 가운데. 계열별로 갈라 보려고 쓴다."""
    parts = Path(document or "").parts
    return parts[-2] if len(parts) >= 2 else "(모름)"


def load(patterns: list[str]) -> list[tuple[dict, str]]:
    """실행 디렉터리 여럿에서 pair를 모은다. `(pair, 계열)` 목록을 낸다.

    **같은 `(문서, 계획)` 짝이 두 번 돌아간 것은 먼저 것만 쓴다.** 실행이 죽은 줄 알고
    재실행한 것들이라 뒤엣것이 앞엣것과 같은 계획을 다시 돈 것이다. 안 걸러내면 그
    문서 몫이 두 배로 세어져 계열 비중이 틀어진다. **문서만으로 묶으면 안 된다** —
    계획 파일 이름이 겹쳐 다른 계획이 같은 문서에 걸린 실행이 있어서, 그것까지 지운다.
    """
    out: list[tuple[dict, str]] = []
    seen_files: set[Path] = set()
    seen_jobs: dict[tuple[str, str], str] = {}
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) or [pattern]
        for match in matches:
            path = Path(match)
            path = path if path.is_absolute() else (REPOSITORY_DIR / path)
            target = path / "pairs.json" if path.is_dir() else path
            if target in seen_files:
                continue
            if not target.exists():
                print(f"!  건너뜀 (pairs.json 없음): {path.name}")
                continue
            seen_files.add(target)
            summary = solar.read_json(target.parent / "summary.json") or {}
            document = summary.get("document") or ""
            job = (document, str(summary.get("plan") or ""))
            if job in seen_jobs:
                print(f"!  중복 건너뜀: {path.name[:24]}  (먼저 돈 {seen_jobs[job][:24]}와 같은 짝)")
                continue
            seen_jobs[job] = path.name
            series = series_of(document)
            out.extend((pair, series) for pair in solar.read_json(target))
    return out


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
    ap.add_argument("--by-series", action="store_true",
                    help="계열별로 갈라 낸다. 대상 회수가 계열에 따라 뒤집히는 지시가 있다")
    ap.add_argument("--pairs", action="store_true",
                    help="같은 조항에 `늘었다`·`줄었다`를 둘 다 건 짝을 맞대어 본다")
    args = ap.parse_args()

    loaded = load(args.runs)
    if not loaded:
        raise SystemExit("pair를 하나도 못 읽었습니다.")

    # `안 바꿈`(BM2=0)은 판정 호출이 아예 안 갔으므로 분모에서 뺀다. 넣어 두면 판정을
    # 받은 적 없는 건이 BM5 실패로 세어져 지시가 실제보다 나빠 보인다.
    def tally(rows_of: list[tuple[dict, str]]) -> tuple[dict, dict]:
        rows: dict[tuple[str, str], Counter] = defaultdict(Counter)
        stats: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for pair, _ in rows_of:
            want = instructed(pair)
            if want is None:
                continue
            got, blank = judged(pair)
            if not got:
                rows[want][blank] += 1
                stats[want]["제외" if blank == "(안 바꿈 BM2=0)" else "라벨없음"] += 1
                if blank != "(안 바꿈 BM2=0)":
                    stats[want]["건수"] += 1
                continue
            stats[want]["건수"] += 1
            if want in got:
                stats[want]["BM5"] += 1
            if want[0] in {t for t, _ in got}:
                stats[want]["BM5a"] += 1
            for pair_label in got:
                rows[want][f"{pair_label[0]} / {pair_label[1]}"] += 1
        return rows, stats

    if args.pairs:
        # **같은 조항에 방향만 다르게 건 짝은 한 변수 실험이다.** 조항·프롬프트가 같고
        # 지시 방향만 다르므로, 셜록의 답이 갈리면 지시가 듣는 것이고 안 갈리면 조항이
        # 방향을 정하는 것이다. BM5로는 이 둘이 구별되지 않는다 -- 둘 다 실패로 나온다.
        both: dict[tuple[str, str], dict[str, list]] = defaultdict(dict)
        for pair, _ in loaded:
            want = instructed(pair)
            if want is None or want[1] not in ("늘었다", "줄었다"):
                continue
            got, _blank = judged(pair)
            key = (str(pair.get("block_id")), want[0])
            both[key][want[1]] = [d for t, d in got if t == want[0]]

        verdicts, examples = Counter(), defaultdict(list)
        for (block, target), sides in both.items():
            if len(sides) < 2:
                verdicts[f"{target}: 홑 (짝 없음)"] += 1
                continue
            up, down = sides.get("늘었다", []), sides.get("줄었다", [])
            hit_up, hit_down = "늘었다" in up, "줄었다" in down
            if hit_up and hit_down:
                label = "지시대로 갈렸다"
            elif not up or not down:
                label = "한쪽이 라벨 없음"
            elif set(up) == set(down):
                label = "조항이 방향을 정한다"
            elif hit_up or hit_down:
                label = "한쪽만 맞다"
            else:
                label = "둘 다 어긋났다"
            verdicts[f"{target}: {label}"] += 1
            if len(examples[label]) < 3:
                examples[label].append((block, target, up, down))

        print(f"\n짝 {sum(1 for s in both.values() if len(s) >= 2)}쌍 "
              f"· 홑 {sum(1 for s in both.values() if len(s) < 2)}개\n")
        for name, count in sorted(verdicts.items()):
            print(f"  {count:>3}  {name}")
        print("\n읽는 법 — `지시대로 갈렸다`가 많으면 쪼개기가 듣는다."
              " `조항이 방향을 정한다`가 많으면\n지시가 무력하므로 프롬프트에"
              " \"무엇을 기준으로 늘고 줄었다고 하는가\"를 넣어야 한다.")
        for label, rows_ in examples.items():
            if label == "지시대로 갈렸다":
                continue
            print(f"\n[{label}]")
            for block, target, up, down in rows_:
                print(f"  {block} · {target}   늘었다 지시 -> {up or '없음'}"
                      f"   줄었다 지시 -> {down or '없음'}")
        return

    if args.by_series:
        by_series: dict[str, list] = defaultdict(list)
        for item in loaded:
            by_series[item[1]].append(item)
        print(f"\npair {len(loaded)}건 · 계열 {len(by_series)}개\n")
        print(f"{'지시':<24}" + "".join(f"{s[:16]:>20}" for s in sorted(by_series)))
        print("-" * (24 + 20 * len(by_series)))
        every = sorted({w for s in by_series for w in tally(by_series[s])[1]})
        per = {s: tally(by_series[s])[1] for s in by_series}
        for want in every:
            line = f"{want[0] + ' / ' + want[1]:<24}"
            for s in sorted(by_series):
                st = per[s].get(want)
                line += (f"{st['BM5']}/{st['건수']} · {st['BM5a']}/{st['건수']}".rjust(20)
                         if st and st["건수"] else "—".rjust(20))
            print(line)
        print("\n(각 칸은 BM5 · BM5a)")
        return

    rows, stats = tally(loaded)
    skipped = sum(s["제외"] for s in stats.values())
    print(f"pair {len(loaded)}건 · 지시 {len(stats)}종"
          f"{f' · 안 바꿈 {skipped}건은 분모에서 뺌' if skipped else ''}\n")
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
