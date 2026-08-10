"""Collect the three approved operating-guideline pairs from official sites."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw_collection"
CLASSIFIER = REPO / "source_data" / "classify_diff.py"
USER_AGENT = "data-collect/guideline-pairs"

PAIRS = [
    {
        "directory": "regional_industry_guideline_pair",
        "case_id": "regional-industry-guideline-2023__2026",
        "issuer": "산업통상자원부·산업통상부",
        "series": "지역산업지원사업 공통운영요령",
        "before": {
            "file": "before_2023.html",
            "date": "2023-02-03",
            "number": "산업통상자원부고시 제2023-21호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000218883",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000218883&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
        "after": {
            "file": "after_2026.html",
            "date": "2026-02-13",
            "number": "산업통상부고시 제2026-13호",
            "page_url": "https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000274750",
            "file_url": "https://www.law.go.kr/LSW/admRulLsInfoR.do?admRulSeq=2100000274750&joTpYn=Y&languageType=KO&chrClsCd=010202",
        },
    },
    {
        "directory": "mss_rd_guideline_pair",
        "case_id": "mss-rd-guideline-2024__2025",
        "issuer": "중소벤처기업부",
        "series": "중소기업기술개발 지원사업 운영요령",
        "before": {
            "file": "before_2024.hwpx",
            "date": "2024-07-29",
            "number": "중소벤처기업부고시 제2024-54호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1052198&cbIdx=127&parentSeq=1052198&searchRltnYn=",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1052198&cbIdx=127&streFileNm=2afa5ef4-b491-448f-80ec-f1c070514a81.hwpx",
        },
        "after": {
            "file": "after_2025.hwpx",
            "date": "2025-05-20",
            "number": "중소벤처기업부고시 제2025-53호",
            "page_url": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1059007&cbIdx=127",
            "file_url": "https://www.mss.go.kr/common/board/Download.do?bcIdx=1059007&cbIdx=127&streFileNm=3cc5feb5-8723-42d8-bc1a-acfb0c94d251.hwpx",
        },
    },
    {
        "directory": "mof_rd_regulation_pair",
        "case_id": "mof-rd-regulation-2022__2024",
        "issuer": "해양수산부",
        "series": "해양수산 연구개발사업 운영규정",
        "before": {
            "file": "before_2022.hwpx",
            "date": "2022-12-27",
            "number": "해양수산부훈령 제687호",
            "page_url": "https://www.mof.go.kr/doc/ko/selectDoc.do?bbsSeq=35&docSeq=48445&menuSeq=887",
            "file_url": "https://www.mof.go.kr/jfile/readDownloadFile.do?fileNum=3&fileType=MOF_ARTICLE&fileTypeSeq=48445",
        },
        "after": {
            "file": "after_2024.hwpx",
            "date": "2024-10-20",
            "number": "해양수산부훈령 제772호",
            "page_url": "https://www.mof.go.kr/doc/ko/selectDoc.do?bbsSeq=35&docSeq=58895&menuSeq=888",
            "file_url": "https://www.mof.go.kr/jfile/readDownloadFile.do?fileNum=2&fileType=MOF_ARTICLE&fileTypeSeq=58895",
        },
    },
]


def download(url: str, path: Path) -> tuple[str, int]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
        content_type = response.headers.get_content_type()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return content_type, len(payload)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(path: Path) -> tuple[list[str], Path]:
    sys.path.insert(0, str(REPO / "source_data"))
    from extract import blocks

    extracted = blocks(path)
    text_path = path.with_suffix(".txt")
    text_path.write_text("\n".join(extracted) + "\n", encoding="utf-8")
    return extracted, text_path


def collect_pair(pair: dict) -> None:
    directory = RAW / pair["directory"]
    sources = {}
    paths = {}
    for side in ("before", "after"):
        spec = pair[side]
        path = directory / spec["file"]
        url = spec.get("file_url", spec["page_url"])
        content_type, byte_size = download(url, path)
        if path.suffix == ".hwpx" and not zipfile.is_zipfile(path):
            raise RuntimeError(f"{path.name}: HWPX ZIP signature missing")
        blocks, text_path = extract(path)
        joined = "".join(blocks)
        if pair["series"].replace(" ", "") not in joined.replace(" ", ""):
            raise RuntimeError(f"{path.name}: document title missing from extracted text")
        if len(joined) < 5_000:
            raise RuntimeError(f"{path.name}: extracted body is too short ({len(joined)} characters)")
        paths[side] = path
        sources[side] = {
            "document_title": pair["series"],
            "effective_date": spec["date"],
            "authority_number": spec["number"],
            "page_url": spec["page_url"],
            "file_url": url,
            "local_file": path.name,
            "mime": content_type,
            "byte_size": byte_size,
            "sha256": digest(path),
            "extracted_text_file": text_path.name,
            "extracted_blocks": len(blocks),
            "extracted_text_characters": len(joined),
        }

    output = directory / f"{paths['before'].stem}__{paths['after'].stem}.classify.json"
    subprocess.run(
        [sys.executable, str(CLASSIFIER), str(paths["before"]), str(paths["after"]), "--json", str(output), "--show", "0"],
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    comparison = json.loads(output.read_text(encoding="utf-8"))
    manifest = {
        "case_id": pair["case_id"],
        "source_class": "기관 운영지침·사업시행지침",
        "collected_at": datetime.now().astimezone().isoformat(),
        "issuer": pair["issuer"],
        "document_series": pair["series"],
        "match_evidence": {
            "type": "official_administrative_rule_history",
            "note": "국가법령정보센터의 동일 제명 연혁과 각 판본의 일부개정 발령번호로 연결한다.",
        },
        "sources": sources,
        "comparison": {
            "classifier_file": output.name,
            "similarity": comparison["similarity"],
            "changed_regions": comparison["regions"],
            "no_real_change_blocks": comparison["no_real_change"]["blocks"],
            "added_blocks": len(comparison["added"]),
            "deleted_blocks": len(comparison["deleted"]),
            "real_change_blocks": comparison["real_change"]["blocks"],
            "real_change_groups": comparison["real_change"]["groups"],
        },
        "acceptance": "accepted_meaningful_change",
        "scope_note": "수정 명세에 따라 사업 운영지침 성격의 행정규칙을 포함한다.",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    selected = set(sys.argv[1:])
    for pair in PAIRS:
        if not selected or pair["directory"] in selected:
            collect_pair(pair)


if __name__ == "__main__":
    main()
