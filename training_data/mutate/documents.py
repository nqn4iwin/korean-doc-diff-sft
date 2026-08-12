"""합성에 쓸 원천 문서를 중복 없이 고른다.

`data/raw_collection/`에는 같은 문서가 여러 형식으로 들어 있다. `after_2024.hwpx`와
`after_2024.txt`는 **같은 규정**이라 둘 다 돌리면 같은 조항에 같은 지시가 두 번 걸리고,
학습 데이터에 거의 같은 pair가 겹쳐 들어간다. 2026-08-12에 전체 용량을 재면서 걸렀더니
조항 후보가 4,131개에서 3,391개로 줄었다 -- **740개가 중복이었다.**

**같은 폴더 안에서 확장자만 다른 것을 같은 문서로 본다.** `.converted`처럼 변환 과정에서
붙은 꼬리도 뗀다. 형식이 여럿이면 `.hwpx`를 먼저 쓴다 -- 원본에 가깝고 `extract.py`가
문단 구조를 더 잘 살린다.

`changed_blocks.txt`는 원천이 아니라 다른 스크립트가 만든 파생물이라 뺀다.

사용:
    python3 training_data/mutate/documents.py              # 목록과 조항 수
    python3 training_data/mutate/documents.py --paths      # 경로만 (셸 반복문에 먹인다)

    for d in $(python3 training_data/mutate/documents.py --paths); do
      python3 training_data/mutate/generate.py "$d" --prompt v1.1 --per-clause 3
    done
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))
sys.path.insert(0, str(REPOSITORY_DIR / "source_data"))

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mutate_generate", HERE / "generate.py")
_generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_generate)

READABLE = (".hwpx", ".hwp", ".txt")
DERIVED = {"changed_blocks.txt"}


def _clauses(path: Path) -> int:
    try:
        return len(_generate.clause_candidates(path))
    except Exception:
        return 0


def unique(root: Path) -> list[Path]:
    """중복을 뺀 원천 문서 목록. 문서 순서는 경로순으로 고정한다.

    **어느 형식을 쓸지는 확장자가 아니라 조항이 실제로 나오는지로 정한다.** 확장자 순서로
    고르면 원본에 가까운 `.hwp`를 집게 되는데, 옛 이진 형식은 `extract.py`가 못 읽어
    조항이 0개로 나온다. 실제로 그렇게 골랐더니 조항 730개짜리 `.txt`가 버려지고 전체가
    3,391개에서 1,946개로 줄었다. 같은 수면 목록 순서대로 `.hwpx`를 쓴다.
    """
    groups: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in READABLE or path.name in DERIVED:
            continue
        # `2020_standard_terms.converted.hwpx`와 `2020_standard_terms.txt`는 같은 문서다.
        key = (path.parent.name, path.stem.replace(".converted", ""))
        groups.setdefault(key, []).append(path)

    best: dict[tuple[str, str], Path] = {}
    for key, paths in groups.items():
        best[key] = max(paths, key=lambda p: (_clauses(p), -READABLE.index(p.suffix.lower())))
    return [best[k] for k in sorted(best)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPOSITORY_DIR / "data" / "raw_collection")
    ap.add_argument("--paths", action="store_true", help="경로만 한 줄에 하나씩 낸다")
    args = ap.parse_args()

    documents = unique(args.root)
    if args.paths:
        for path in documents:
            print(path.relative_to(REPOSITORY_DIR))
        return

    total = 0
    allowed: list[int] = []          # 조항마다 걸 수 있는 지시가 몇 개인지
    for path in documents:
        try:
            candidates = _generate.clause_candidates(path)
        except Exception as error:  # 읽히지 않는 형식은 건너뛰되 조용히 지나가지 않는다
            print(f"  {'--':>5}  {path.relative_to(args.root)}  ({type(error).__name__})")
            continue
        total += len(candidates)
        allowed += [len([c for c in _generate.applicable(text)
                         if c not in _generate.BLOCKED]) for _, text in candidates]
        print(f"  {len(candidates):>5}  {path.relative_to(args.root)}")

    print(f"\n문서 {len(documents)}개, 조항 후보 {total}개")
    # 조항 × 지시 수가 아니라 **성립하는 지시만큼만** 걸린다. 조항 하나에 지시가 하나뿐인
    # 것이 절반 가까이라, 곱셈으로 어림하면 실제보다 크게 나온다.
    for per in (2, 3, 4):
        print(f"  --per-clause {per} 이면 계획 {sum(min(n, per) for n in allowed)}건")
    print(f"  성립하는 조합 전부      {sum(allowed)}건")


if __name__ == "__main__":
    main()
