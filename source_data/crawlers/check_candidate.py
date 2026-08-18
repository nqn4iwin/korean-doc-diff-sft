"""원천 후보 한 쌍이 쓸 만한지 자동으로 판정한다. **받기 전에 돌린다.**

수집을 맡은 사람이나 에이전트가 판본 두 개를 고르면, 그것이 `docs/원천데이터_선정_프로세스.md`의
수락 규칙을 통과하는지 눈으로 볼 필요 없이 이 스크립트가 답한다. **합격한 것만
`collect_guideline_pairs.py`의 `PAIRS`에 넣는다.**

여기 박힌 기준값은 정하지 않고 **이미 채택·반려한 25쌍에서 실측해 뽑았다**(2026-08-18).
그 표는 아래 각 상수의 주석에 있다.

인자는 세 가지 꼴을 다 받는다. 어느 쪽인지는 알아서 가린다.

    # 1) 국가법령정보센터 행정규칙: 판본 번호(admRulSeq) 두 개
    python3 source_data/crawlers/check_candidate.py 2100000208247 2100000251982

    # 2) 첨부파일 내려받기 주소 두 개 (공정위 표준약관, 부처 공고 등)
    python3 source_data/crawlers/check_candidate.py \
        "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=14853" \
        "https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=14863"

    # 3) 이미 받아 둔 파일 두 개
    python3 source_data/crawlers/check_candidate.py before.hwpx after.hwpx

주소로 받은 것은 확장자가 주소에 안 들어 있는 경우가 많아 **내용의 첫 바이트로**
형식을 가린다(`sniff`). PDF와 구형 HWP는 그 자리에서 반려한다 -- 이 저장소에 두
형식의 추출 경로가 없다.

**`data/raw_collection/`에 아무것도 안 쓴다.** 떨어진 후보가 원천 폴더를 더럽히면
`annotate.py`가 그것까지 세기 때문이다(2026-08-18에 실제로 겪었다). 받은 파일은
`data/candidates/<이름>/`에 남으므로 합격하면 그대로 옮겨 쓰면 된다.

**이미 가진 문서를 다시 받는 것도 반려한다.** `data/raw_collection/` 아래 문서를 전부
읽어 후보와 대조한다. 새 세션에서 수집을 시작한 사람은 무엇을 이미 가졌는지 모르므로,
목록을 외우게 하지 않고 여기서 막는다.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLASSIFIER = REPO / "source_data" / "classify_diff.py"
CANDIDATES = REPO / "data" / "candidates"
RAW = REPO / "data" / "raw_collection"
USER_AGENT = "data-collect/check-candidate"

# 국가법령정보센터의 **조문 본문 HTML** 엔드포인트. 목록 화면(`admRulLsInfoP.do`)이 아니라
# 이쪽이라야 조문이 다 들어 있다. 판본마다 `admRulSeq`가 다르므로 **pair 하나는 같은 제명의
# 서로 다른 `admRulSeq` 둘**이다. 연혁 탭은 자바스크립트로 채워져 URL만으로는 목록이 안 나온다.
LAW_URL = ("https://www.law.go.kr/LSW/admRulLsInfoR.do"
           "?admRulSeq={seq}&joTpYn=Y&languageType=KO&chrClsCd=010202")

# --- 기준값. 전부 실측에서 뽑았다 -------------------------------------------------
#
# **유사도 하한.** 채택된 것 중 제일 낮은 값이 해수부 운영규정 0.5983이고, 반려한
# 산업기술혁신사업 2020->2024가 0.2891, 행안부 평가편람이 0.016이다. 0.55는 채택된 것을
# 안 떨어뜨리면서 반려한 것을 잡는 자리다.
SIMILARITY_FLOOR = 0.55

# **실질 변경 묶음 수는 판정에 쓰지 않는다.** 2026-08-18에 사용자가 정한 것이다 --
# "원천 하나에서 가져올 수 있는 블록쌍이 1쌍밖에 없을 수도 있지 뭐. 그럼 그냥 그 1쌍도
# 원천 1쌍으로 쓰는 거야." 표준약관은 원래 한 쌍에서 1~4건밖에 안 나오고 정정공고는
# 3건이다. 여기에 하한을 두면 그 두 유형이 통째로 걸린다.
#
# 그전에는 20묶음 미만을 `[경고]`로 냈는데, 지시문이 "경고는 무시해도 된다"고 적혀 있어
# 수집자가 작은 쌍 다섯 개를 그대로 통과시켰다. 경고는 판정에 안 쓰이면서 판단만
# 흔들었으므로 **정보로 내린다.** 이 값은 "이보다 적으면 수량 기여가 작다"는 눈금일 뿐이다.
GROUPS_NOTE = 20

# **중복 상한.** 후보 한쪽이 이미 가진 문서와 이만큼 겹치면 같은 문서로 본다.
# 지금 가진 67개 파일을 서로 대조해 실측한 값이다(2026-08-18).
#
#   같은 문서의 다른 판본 (한 pair의 before <-> after)   0.95 ~ 1.00
#   남남이지만 같은 장르 (산업부 운영요령 <-> 지역산업)   최고 0.32
#
# 두 무리 사이가 0.32와 0.95로 크게 벌어져 있어 그 사이 아무 데나 그으면 된다.
# 0.55로 둔 것은 유사도 하한과 눈금을 맞추려는 것뿐이다.
DUPLICATE_CEILING = 0.55

# 지문은 짧은 줄을 뺀다. "제1조(목적)" 같은 것은 남남인 문서끼리도 그대로 겹친다.
FINGERPRINT_MIN_CHARACTERS = 20

# 지문이 이보다 적게 나온 파일은 대조 대상에서 뺀다. 추출이 안 되는 형식(PDF, 구형 HWP)이
# 여기 걸린다. 적은 지문은 우연히 100% 겹칠 수 있어 오히려 거짓 중복을 만든다.
FINGERPRINT_MIN_BLOCKS = 10

# 대조할 파일 형식. `extract.py`가 문단 단위로 읽을 수 있는 것만이다.
INDEXED_SUFFIXES = (".hwpx", ".html", ".htm", ".txt")

# **최다 치환 집중도 상한.** 한 종류의 치환이 실질 변경 묶음의 몇 %를 차지하는가다.
# 제도가 용어를 일괄로 갈아치운 판본을 걸러내려고 만들었다 -- 산업기술혁신사업
# 2020->2024는 국가연구개발혁신법(2021 시행)이 `과제 -> 연구개발과제`를 224회 부르며
# 집중도가 61%였고, 블록 수는 470개나 되지만 내용은 명칭 변경 하나뿐이었다.
#
# 묶음 20개 이상인 정상 pair의 실측 분포는 6~36%다(최고가 인사혁신처 14->15의 36%).
# 40%는 그 위이고 61%보다 아래다.
CONCENTRATION_CEILING = 0.40

# 집중도는 묶음이 적으면 뜻이 없다. 묶음이 1개면 집중도가 무조건 100%다.
CONCENTRATION_MIN_GROUPS = 20

# 본문이 이만큼도 안 나오면 추출이 실패한 것이지 문서가 짧은 것이 아니다.
#
# 5,000자였는데 2026-08-18에 2,000자로 내렸다. **이미 채택한 문서 중 제일 짧은 것이
# 4,868자(공정위 신유형 상품권 표준약관 2020년판)라 옛 하한에 스스로 걸렸다.** 표준약관은
# 원래 그 길이다. 형식을 확장자와 첫 바이트로 먼저 거르므로(`check_format`) 이 값이
# 떠맡던 "PDF를 글자로 잘못 읽었다" 같은 경우는 여기까지 오지 않는다.
MIN_CHARACTERS = 2_000


def slug(target: str) -> str:
    """인자 하나를 폴더 이름으로 쓸 수 있는 짧은 토막으로 만든다."""
    return re.sub(r"[^0-9A-Za-z._-]+", "-", target).strip("-")[-40:] or "candidate"


def sniff(payload: bytes) -> str:
    """내려받은 것이 무슨 형식인지 첫 바이트로 가린다.

    첨부파일 주소에는 확장자가 없는 경우가 많다 -- 공정위는
    `downloadBbsFile.do?atchmnflNo=14853`이라고만 준다. 그런데 `extract.py`는 확장자를
    보고 읽는 방법을 고르므로, 여기서 형식을 정해 그 확장자로 저장해야 한다.
    """
    if payload[:4] == b"PK\x03\x04":            # ZIP. HWPX도 ZIP이다
        return ".hwpx"
    if payload[:4] == b"%PDF":
        return ".pdf"
    if payload[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE 복합문서 = 구형 HWP
        return ".hwp"
    head = payload[:2048].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return ".html"
    return ".txt"


def download(url: str, stem: Path, force: str | None = None) -> Path:
    """주소에서 받아 **내용에 맞는 확장자**로 저장한다. 저장한 경로를 낸다.

    `force`를 주면 형식을 가리지 않고 그 확장자로 저장한다. 국가법령정보센터 본문처럼
    무엇이 올지 이미 아는 곳에 쓴다.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    path = stem.with_suffix(force or sniff(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def check_format(path: Path) -> None:
    """읽을 수 없는 형식이면 그 자리에서 멈춘다."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        sys.exit(
            f"반려: {path.name}은 PDF다. PDF는 인쇄된 지면을 좌표 위의 글자로 적을 뿐 "
            f"문단이라는 개념이 없어서 조항 단위로 자를 수 없고, 이 저장소에는 PDF 추출 "
            f"경로 자체가 없다(`source_data/extract.py`). **같은 게시물에 HWPX나 HTML "
            f"판본이 붙어 있는지 보고, 없으면 이 후보는 버린다.**")
    if suffix == ".hwp":
        sys.exit(
            f"반려: {path.name}은 구형 HWP(한/글 바이너리)다. 그대로는 못 읽고 한컴오피스로 "
            f"HWPX 변환을 거쳐야 하는데 그것은 사람 손이 필요한 작업이다. **같은 게시물에 "
            f"HWPX가 같이 올라와 있는지 보고, 없으면 이 후보는 건너뛴다.**")
    if suffix == ".hwpx" and not zipfile.is_zipfile(path):
        sys.exit(f"반려: {path.name}이 HWPX인 줄 알았는데 ZIP이 아니다. 받다 만 파일로 본다.")


def extract_text(path: Path, workspace: Path) -> tuple[int, int]:
    """`extract.py`로 블록을 뽑아 `.txt`로 남긴다. (블록 수, 글자 수)를 낸다.

    추출본은 **원본 옆이 아니라 후보 폴더에** 쓴다. 인자로 `data/raw_collection/` 안의
    파일을 주면 원본 옆에 쓰는 순간 원천 폴더를 더럽히기 때문이다.
    """
    sys.path.insert(0, str(REPO / "source_data"))
    from extract import blocks

    found = blocks(path)
    joined = "".join(found)
    (workspace / f"{path.stem}.txt").write_text(
        "\n".join(found) + "\n", encoding="utf-8")
    return len(found), len(joined)


def fingerprint(path: Path) -> set[str]:
    """문서 하나를 **긴 문단들의 집합**으로 만든다. 이것으로 같은 문서인지 본다."""
    sys.path.insert(0, str(REPO / "source_data"))
    from extract import blocks

    tight = (re.sub(r"\s+", "", block) for block in blocks(path))
    return {block for block in tight if len(block) >= FINGERPRINT_MIN_CHARACTERS}


def held_documents() -> dict[Path, set[str]]:
    """`data/raw_collection/` 아래 이미 가진 문서를 전부 지문으로 만든다."""
    index: dict[Path, set[str]] = {}
    if not RAW.exists():
        return index
    for path in sorted(RAW.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in INDEXED_SUFFIXES:
            continue
        if path.name == "changed_blocks.txt":   # 원문이 아니라 변경분만 추려 둔 것
            continue
        try:
            found = fingerprint(path)
        except Exception:                        # 읽을 수 없는 파일은 그냥 뺀다
            continue
        if len(found) >= FINGERPRINT_MIN_BLOCKS:
            index[path] = found
    return index


def overlaps(candidate: set[str], held: dict[Path, set[str]]) -> list[tuple[str, float, Path]]:
    """후보가 이미 가진 문서들과 얼마나 겹치는가. 원천 폴더마다 제일 높은 값 하나씩.

    나누는 쪽을 **후보의 크기**로 둔다. 후보가 이미 가진 문서 안에 통째로 들어 있으면
    1.0이 되고, 후보 쪽이 훨씬 길어도 겹치는 만큼은 그대로 드러난다.
    """
    best: dict[str, tuple[float, Path]] = {}
    for path, found in held.items():
        ratio = len(candidate & found) / len(candidate)
        directory = path.relative_to(RAW).parts[0]
        if ratio > best.get(directory, (-1.0, path))[0]:
            best[directory] = (ratio, path)
    return sorted(((d, r, p) for d, (r, p) in best.items()), key=lambda row: -row[1])


def classify(before: Path, after: Path, out: Path) -> dict:
    subprocess.run(
        [sys.executable, str(CLASSIFIER), str(before), str(after),
         "--json", str(out), "--show", "0"],
        check=True, capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return json.loads(out.read_text(encoding="utf-8"))


def concentration(report: dict) -> tuple[float, tuple[str, str] | None, int]:
    """가장 많이 나온 치환 하나가 실질 변경 묶음의 몇 %를 차지하는가."""
    counter: collections.Counter = collections.Counter()
    for item in report["real_change"]["items"]:
        for pair in item["substitutions"]:
            counter[tuple(pair)] += 1
    groups = report["real_change"]["groups"]
    if not counter or not groups:
        return 0.0, None, 0
    (top, count), = counter.most_common(1)
    return count / groups, top, count


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before", help="이전판의 admRulSeq · 내려받기 주소 · 파일 경로")
    ap.add_argument("after", help="이후판의 admRulSeq · 내려받기 주소 · 파일 경로")
    ap.add_argument("--name", default=None, help="후보 폴더 이름 (기본값은 두 인자에서 만든다)")
    ap.add_argument(
        "--allow-series", metavar="폴더이름", action="append", default=[],
        help="이 원천 폴더와 겹치는 것은 중복으로 보지 않는다. **같은 계열의 다른 판본 "
             "조합을 일부러 하나 더 받을 때만 쓴다**(한 계열 최대 3쌍). 값은 "
             "`data/raw_collection/` 아래 폴더 이름이다.")
    args = ap.parse_args()

    name = args.name or f"{slug(args.before)}__{slug(args.after)}"
    workspace = CANDIDATES / name
    workspace.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for side, target in (("before", args.before), ("after", args.after)):
        if target.isdigit():
            print(f"받는 중: {side} admRulSeq={target}")
            path = download(LAW_URL.format(seq=target), workspace / f"{side}_{target}",
                            force=".html")
        elif target.startswith(("http://", "https://")):
            print(f"받는 중: {side} {target}")
            path = download(target, workspace / side)
            print(f"  형식 판정: {path.suffix}")
        else:
            path = Path(target).resolve()
            if not path.exists():
                sys.exit(f"없는 파일: {path}")
        check_format(path)
        count, characters = extract_text(path, workspace)
        print(f"  {path.name}  블록 {count}개 · {characters:,}자")
        if characters < MIN_CHARACTERS:
            sys.exit(f"반려: {path.name}의 본문이 {characters}자뿐이다. 추출이 실패한 것으로 본다.")
        paths[side] = path

    print("\n이미 가진 문서와 대조하는 중...")
    held = held_documents()
    print(f"  대조 대상 {len(held)}개 파일")
    matches: dict[str, list[tuple[str, float, Path]]] = {}
    for side, path in paths.items():
        matches[side] = overlaps(fingerprint(path), held)

    report = classify(paths["before"], paths["after"], workspace / "candidate.classify.json")

    similarity = report["similarity"]
    groups = report["real_change"]["groups"]
    blocks_ = report["real_change"]["blocks"]
    ratio, top, top_count = concentration(report)

    print("\n" + "=" * 62)
    print(f"  유사도            {similarity:.4f}   (하한 {SIMILARITY_FLOOR})")
    print(f"  실질 변경         {blocks_}블록 / {groups}묶음")
    if top is not None:
        print(f"  최다 치환         {top[0]!r} -> {top[1]!r}  {top_count}회")
        if groups >= CONCENTRATION_MIN_GROUPS:
            print(f"  집중도            {ratio:.0%}   (상한 {CONCENTRATION_CEILING:.0%})")
        else:
            # 묶음 하나에 같은 치환이 여러 번 들어갈 수 있어 100%를 넘기도 한다. 묶음이
            # 적을 때는 애초에 판정에 안 쓰므로 숫자를 아예 안 보여 준다. 167% 같은 값이
            # 찍히면 읽는 사람만 놀란다.
            print(f"  집중도            보지 않는다 (묶음이 {groups}개뿐, "
                  f"{CONCENTRATION_MIN_GROUPS}개 이상일 때만 본다)")
    for side in ("before", "after"):
        head = matches[side][:1]
        label = "  중복 검사" if side == "before" else "           "
        if not head:
            print(f"{label}        {side:6s}  대조할 문서가 없다")
            continue
        directory, ratio, path = head[0]
        print(f"{label}        {side:6s}  최다 {ratio:.2f}  {directory}"
              f"   (상한 {DUPLICATE_CEILING})")
    print("=" * 62)

    fail: list[str] = []
    warn: list[str] = []
    note: list[str] = []

    for side in ("before", "after"):
        for directory, ratio, path in matches[side]:
            if ratio < DUPLICATE_CEILING:
                break
            if directory in args.allow_series:
                warn.append(
                    f"{side} 쪽이 `{directory}`의 {path.name}과 {ratio:.0%} 겹치는데 "
                    f"`--allow-series {directory}`로 허용했다. **같은 계열에서 세 쌍까지가 "
                    f"한도다.** 그 폴더에 이미 몇 쌍이 들어 있는지 세고 넘어간다.")
                continue
            fail.append(
                f"{side} 쪽이 **이미 가진 문서**다. `{directory}/{path.name}`과 "
                f"{ratio:.0%} 겹친다(상한 {DUPLICATE_CEILING:.0%}). 남남인 문서끼리는 "
                f"같은 장르여도 32%를 넘은 적이 없으므로 이 정도면 같은 문서다. "
                f"**다른 계열을 고른다.** 같은 계열에서 판본 조합을 하나 더 받는 것이 "
                f"목적이었다면 `--allow-series {directory}`를 붙여 다시 돌린다.")

    if similarity < SIMILARITY_FLOOR:
        fail.append(
            f"유사도 {similarity:.4f}가 하한 {SIMILARITY_FLOOR} 아래다. 두 판본이 너무 멀어 "
            f"조항이 대응하지 않는다. **간격을 좁힌 다른 판본 조합을 고른다.**")
    if groups >= CONCENTRATION_MIN_GROUPS and ratio > CONCENTRATION_CEILING:
        fail.append(
            f"최다 치환 집중도가 {ratio:.0%}다. 한 종류의 치환이 변경의 대부분이면 "
            f"블록 수는 많아도 내용은 명칭 변경 하나뿐이다. **제도가 용어를 일괄로 갈아치운 "
            f"시점을 사이에 두지 않았는지 본다** (예: 국가연구개발혁신법 2021년 시행).")
    if groups < GROUPS_NOTE:
        note.append(
            f"실질 변경이 {groups}묶음이다. 판정에는 안 쓴다 -- 1묶음짜리 원천도 원천 한 쌍으로 "
            f"센다. 다만 수량 기여는 그만큼 작으니, 같은 품으로 더 큰 쌍을 고를 수 있는 "
            f"자리였는지만 생각해 보면 된다.")

    for line in fail:
        print(f"\n[반려] {line}")
    for line in warn:
        print(f"\n[경고] {line}")
    for line in note:
        print(f"\n[참고] {line}")

    if fail:
        print(f"\n판정: **반려**. `PAIRS`에 넣지 않는다.")
        sys.exit(1)
    print(f"\n판정: **합격**{' (경고 있음)' if warn else ''}. "
          f"`collect_guideline_pairs.py`의 `PAIRS`에 넣어도 된다.")
    print(f"받은 파일: {workspace}")


if __name__ == "__main__":
    main()
