"""Collect changed HWP pairs linked by a prior-specification identifier.

No title similarity matching or LLM call is used.  A saved case has exactly
one HWP from each source, a direct API identifier link, distinct SHA-256
digests, and normalized HWP text whose edit distance is greater than three.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from test_connections import load_env


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PROJECT_DIR.parent
ENV_PATH = PROJECT_DIR / ".env.g2b"  # see test_connections.py for why not `.env`
DATA_DIR = REPOSITORY_DIR / "data" / "source_data"
RAW_PRIOR_DIR = DATA_DIR / "raw" / "사전규격"
RAW_BID_DIR = DATA_DIR / "raw" / "입찰공고"
CHANGE_DIR = DATA_DIR / "processed" / "변경점"
RUN_DIR = DATA_DIR / "runs"
PRIOR_ENDPOINT = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"
BID_ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
PRIOR_KEY_NAME = "G2B_PRIOR_SPEC_SERVICE_KEY"
BID_KEY_NAME = "G2B_BID_NOTICE_SERVICE_KEY"
USER_AGENT = "data-collect/changed-hwp-pairs"
TIMEOUT_SECONDS = 30
PRIOR_ID_FIELDS = ("bfSpecRgstNo", "priorSpecId", "prearngPrceDcsnNo")
BID_NUMBER_FIELDS = ("bidNtceNo", "bidNoticeNo", "ntceNo")
BID_ORDER_FIELDS = ("bidNtceOrd", "bidNoticeOrd", "ntceOrd")
TITLE_FIELDS = ("bidNtceNm", "bfSpecNm", "prdctClsfcNoNm", "bizNm")


@dataclass(frozen=True)
class Source:
    directory: Path
    endpoint: str
    key_name: str
    name: str


PRIOR_SOURCE = Source(RAW_PRIOR_DIR, PRIOR_ENDPOINT, PRIOR_KEY_NAME, "prior_spec")
BID_SOURCE = Source(RAW_BID_DIR, BID_ENDPOINT, BID_KEY_NAME, "bid_notice")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="내용이 달라진 직접 연결 HWP pair만 수집합니다.")
    parser.add_argument("--start", required=True, help="조회 시작시각(YYYYMMDDHHMM)")
    parser.add_argument("--end", required=True, help="조회 종료시각(YYYYMMDDHHMM)")
    parser.add_argument("--page-size", type=int, default=999)
    parser.add_argument("--max-api-requests", type=int, default=20)
    parser.add_argument("--max-pairs", type=int, default=10, help="문서 다운로드를 시도할 직접 연결 pair 상한")
    parser.add_argument("--max-files-per-side", type=int, default=5)
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d%H%M")


def find_mapping(value: Any, wanted: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    for key, item in value.items():
        if str(key).casefold() == wanted.casefold() and isinstance(item, dict):
            return item
    for item in value.values():
        found = find_mapping(item, wanted)
        if found is not None:
            return found
    return None


def find_value(value: Any, wanted: str) -> Any:
    if not isinstance(value, dict):
        return None
    for key, item in value.items():
        if str(key).casefold() == wanted.casefold():
            return item
    for item in value.values():
        found = find_value(item, wanted)
        if found is not None:
            return found
    return None


def response_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    body = find_mapping(data, "body") or {}
    items = body.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if isinstance(items, dict):
        nested = items.get("item")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            return [nested]
    return []


def first_present(item: dict[str, Any], names: Iterable[str]) -> tuple[str | None, str | None]:
    folded = {str(key).casefold(): (str(key), value) for key, value in item.items()}
    for name in names:
        found = folded.get(name.casefold())
        if found is not None and found[1] is not None and str(found[1]).strip():
            return found[0], str(found[1]).strip()
    return None, None


def attachment_urls(item: dict[str, Any]) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, value in item.items():
        field, url = str(key), str(value).strip() if value is not None else ""
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        if "file" not in field.casefold() and "atch" not in field.casefold():
            continue
        seen.add(url)
        urls.append({"url_field": field, "url": url})
    return urls


def fetch_page(source: Source, service_key: str, page_no: int, page_size: int, start: str, end: str) -> list[dict[str, Any]]:
    public_query = {"pageNo": page_no, "numOfRows": page_size, "inqryDiv": 1, "inqryBgnDt": start, "inqryEndDt": end, "type": "json"}
    query = {"serviceKey": urllib.parse.unquote(service_key), **public_query}
    request = urllib.request.Request(f"{source.endpoint}?{urllib.parse.urlencode(query)}", headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"{source.name} API HTTP 상태가 {response.status}입니다.")
        payload = response.read()
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{source.name} API 응답이 JSON 형식이 아닙니다.") from error
    code = str(find_value(data, "resultCode") or "")
    if code not in {"0", "00", "000"}:
        raise RuntimeError(f"{source.name} API 응답코드={code or '없음'}")
    return response_items(data)


def collect_source(source: Source, service_key: str, args: argparse.Namespace, budget: int) -> tuple[list[dict[str, Any]], int, bool]:
    records: list[dict[str, Any]] = []
    for page_no in range(1, budget + 1):
        rows = fetch_page(source, service_key, page_no, args.page_size, args.start, args.end)
        records.extend(rows)
        if len(rows) < args.page_size:
            return records, page_no, True
    return records, budget, False


def build_pairs(prior_rows: list[dict[str, Any]], bid_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priors: dict[str, dict[str, Any]] = {}
    for row in prior_rows:
        _, prior_id = first_present(row, PRIOR_ID_FIELDS)
        if prior_id:
            priors.setdefault(prior_id, row)
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bid in bid_rows:
        link_field, prior_id = first_present(bid, PRIOR_ID_FIELDS)
        if not prior_id or prior_id not in priors:
            continue
        _, bid_number = first_present(bid, BID_NUMBER_FIELDS)
        _, bid_order = first_present(bid, BID_ORDER_FIELDS)
        case_id = f"{prior_id}__{bid_number or 'unknown'}-{bid_order or 'unknown'}"
        if case_id in seen:
            continue
        seen.add(case_id)
        prior, = (priors[prior_id],)
        _, prior_title = first_present(prior, TITLE_FIELDS)
        _, bid_title = first_present(bid, TITLE_FIELDS)
        pairs.append({"case_id": case_id, "prior": prior, "bid": bid, "prior_id": prior_id, "bid_number": bid_number, "bid_order": bid_order, "prior_title": prior_title, "bid_title": bid_title, "match_evidence": {"type": "direct_prior_spec_identifier", "bid_notice_field": link_field, "value": prior_id}})
    return pairs


def is_hwp(payload: bytes) -> bool:
    return payload.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))


def download_hwp_candidates(urls: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for reference in urls[:limit]:
        request = urllib.request.Request(reference["url"], headers={"Accept": "*/*", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            candidates.append({**reference, "status": "download_failed", "error_type": type(error).__name__})
            continue
        candidates.append({**reference, "status": "downloaded", "payload": payload, "sha256": sha256_bytes(payload), "byte_size": len(payload), "content_type": content_type, "is_hwp": is_hwp(payload)})
    return candidates


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def hwpx_blocks(path: Path) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("Contents/section") and name.endswith(".xml"))
        for name in names:
            root = ET.fromstring(archive.read(name))
            for paragraph in root.iter():
                if local_name(paragraph.tag) != "p":
                    continue
                text = "".join((node.text or "") for node in paragraph.iter() if local_name(node.tag) == "t").strip()
                if text:
                    blocks.append({"id": f"B{len(blocks) + 1:04d}", "text": text})
    return blocks


def hwp_blocks(path: Path, temporary_dir: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    converted = temporary_dir / f"{path.stem}.hwpx"
    script_path = temporary_dir / "convert_hwp.ps1"
    script = r'''param([string]$InputPath, [string]$OutputPath)
$ErrorActionPreference = "Stop"
$hwp = $null
try {
  $hwp = New-Object -ComObject HWPFrame.HwpObject
  if ($hwp.Open($InputPath, "HWP", "") -eq $false) { throw "HWP open failed" }
  if ($hwp.SaveAs($OutputPath, "HWPX", "") -eq $false) { throw "HWPX save failed" }
} finally {
  if ($null -ne $hwp) { $hwp.Quit() }
}
'''
    script_path.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-File", str(script_path), "-InputPath", str(path), "-OutputPath", str(converted)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("한컴오피스 COM HWPX 변환에 실패했습니다.")
    if not converted.is_file():
        raise RuntimeError("한컴오피스 HWPX 변환 결과가 생성되지 않았습니다.")
    return hwpx_blocks(converted), {"name": "powershell_hancom_com_to_hwpx_xml", "version": "runtime"}


def bounded_edit_distance(left: str, right: str, maximum: int = 3) -> int | None:
    if abs(len(left) - len(right)) > maximum:
        return None
    unavailable = maximum + 1
    previous = {index: index for index in range(min(len(right), maximum) + 1)}
    for left_index, left_character in enumerate(left, start=1):
        start = max(0, left_index - maximum)
        end = min(len(right), left_index + maximum)
        current: dict[int, int] = {}
        for right_index in range(start, end + 1):
            if right_index == 0:
                current[right_index] = left_index
                continue
            right_character = right[right_index - 1]
            cost = 0 if left_character == right_character else 1
            current[right_index] = min(
                previous.get(right_index, unavailable) + 1,
                current.get(right_index - 1, unavailable) + 1,
                previous.get(right_index - 1, unavailable) + cost,
            )
        if not current or min(current.values()) > maximum:
            return None
        previous = current
    result = previous.get(len(right), unavailable)
    return result if result <= maximum else None


def change_blocks(prior: list[dict[str, str]], bid: list[dict[str, str]]) -> list[dict[str, Any]]:
    prior_texts, bid_texts = [block["text"] for block in prior], [block["text"] for block in bid]
    matcher = SequenceMatcher(a=prior_texts, b=bid_texts, autojunk=False)
    changes: list[dict[str, Any]] = []
    for tag, p0, p1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before = "\n".join(prior_texts[p0:p1])
        after = "\n".join(bid_texts[b0:b1])
        mapping = "1:1" if p1 - p0 and b1 - b0 else "1:0" if p1 - p0 else "0:1"
        changes.append({"change_id": f"C{len(changes) + 1:02d}", "mapping": mapping, "prior_block_ids": [f"prior_spec-{block['id']}" for block in prior[p0:p1]], "bid_block_ids": [f"bid_notice-{block['id']}" for block in bid[b0:b1]], "before": before, "after": after, "changed_span": {"before": before, "after": after}, "detection_method": "deterministic_sequence_matcher"})
    return changes


def save_case(pair: dict[str, Any], prior_document: dict[str, Any], bid_document: dict[str, Any], prior_blocks: list[dict[str, str]], bid_blocks: list[dict[str, str]], normal_prior: str, normal_bid: str) -> None:
    case_id = pair["case_id"]
    prior_hwp = RAW_PRIOR_DIR / f"{case_id}.hwp"
    bid_hwp = RAW_BID_DIR / f"{case_id}.hwp"
    prior_hwp.parent.mkdir(parents=True, exist_ok=True)
    bid_hwp.parent.mkdir(parents=True, exist_ok=True)
    prior_hwp.write_bytes(prior_document["payload"])
    bid_hwp.write_bytes(bid_document["payload"])
    common = {"case_id": case_id, "match_evidence": pair["match_evidence"], "collected_at": datetime.now().astimezone().isoformat()}
    write_json(RAW_PRIOR_DIR / f"{case_id}.json", {**common, "api_record": pair["prior"], "document": {key: prior_document[key] for key in ("url_field", "url", "sha256", "byte_size", "content_type")}, "local_file": prior_hwp.relative_to(REPOSITORY_DIR).as_posix()})
    write_json(RAW_BID_DIR / f"{case_id}.json", {**common, "api_record": pair["bid"], "document": {key: bid_document[key] for key in ("url_field", "url", "sha256", "byte_size", "content_type")}, "local_file": bid_hwp.relative_to(REPOSITORY_DIR).as_posix()})
    write_json(CHANGE_DIR / f"{case_id}.json", {**common, "project_title": {"prior_spec": pair["prior_title"], "bid_notice": pair["bid_title"]}, "comparison": {"source_format": "hwp", "sha256": {"prior_spec": prior_document["sha256"], "bid_notice": bid_document["sha256"]}, "normalized_character_counts": {"prior_spec": len(normal_prior), "bid_notice": len(normal_bid)}, "edit_distance_threshold": 3, "edit_distance": "gt_3", "llm_used": False, "text_extractor": "powershell_hancom_com_to_hwpx_xml"}, "changes": change_blocks(prior_blocks, bid_blocks)})


def main() -> int:
    args = parse_args()
    try:
        if parse_timestamp(args.start) >= parse_timestamp(args.end):
            raise ValueError
    except ValueError:
        print("[실패] --start와 --end는 YYYYMMDDHHMM 형식의 올바른 범위여야 합니다.")
        return 2
    if not 1 <= args.page_size <= 999 or args.max_api_requests < 2 or args.max_pairs < 1 or args.max_files_per_side < 1:
        print("[실패] 페이지·API 요청·pair·파일 상한을 확인하세요.")
        return 2
    if not ENV_PATH.is_file():
        print("[실패] source_data/.env 파일이 없습니다.")
        return 2
    env = load_env(ENV_PATH)
    if not env.get(PRIOR_KEY_NAME) or not env.get(BID_KEY_NAME):
        print("[실패] 사전규격·입찰공고 API 인증키가 모두 필요합니다.")
        return 2
    prior_budget = args.max_api_requests // 2
    bid_budget = args.max_api_requests - prior_budget
    try:
        prior_rows, prior_used, prior_complete = collect_source(PRIOR_SOURCE, env[PRIOR_KEY_NAME], args, prior_budget)
        bid_rows, bid_used, bid_complete = collect_source(BID_SOURCE, env[BID_KEY_NAME], args, bid_budget)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as error:
        print(f"[실패] {type(error).__name__}: {error}")
        return 1
    exclusions: list[dict[str, Any]] = []
    saved = 0
    pairs = build_pairs(prior_rows, bid_rows)
    with tempfile.TemporaryDirectory(prefix="g2b-hwp-") as temp_name:
        temporary_dir = Path(temp_name)
        for pair in pairs[:args.max_pairs]:
            prior_candidates = [item for item in download_hwp_candidates(attachment_urls(pair["prior"]), args.max_files_per_side) if item.get("is_hwp")]
            bid_candidates = [item for item in download_hwp_candidates(attachment_urls(pair["bid"]), args.max_files_per_side) if item.get("is_hwp")]
            if len(prior_candidates) != 1 or len(bid_candidates) != 1:
                exclusions.append({"case_id": pair["case_id"], "status": "ambiguous_or_missing_hwp", "prior_hwp_candidates": len(prior_candidates), "bid_hwp_candidates": len(bid_candidates)})
                continue
            prior_document, bid_document = prior_candidates[0], bid_candidates[0]
            if prior_document["sha256"] == bid_document["sha256"]:
                exclusions.append({"case_id": pair["case_id"], "status": "identical_sha256", "sha256": prior_document["sha256"]})
                continue
            prior_path, bid_path = temporary_dir / f"{pair['case_id']}_prior.hwp", temporary_dir / f"{pair['case_id']}_bid.hwp"
            prior_path.write_bytes(prior_document["payload"])
            bid_path.write_bytes(bid_document["payload"])
            try:
                prior_blocks, _ = hwp_blocks(prior_path, temporary_dir)
                bid_blocks, _ = hwp_blocks(bid_path, temporary_dir)
            except (RuntimeError, subprocess.TimeoutExpired, ET.ParseError, zipfile.BadZipFile) as error:
                exclusions.append({"case_id": pair["case_id"], "status": "hwp_text_extraction_failed", "reason": str(error)})
                continue
            normal_prior = normalize_text("\n".join(block["text"] for block in prior_blocks))
            normal_bid = normalize_text("\n".join(block["text"] for block in bid_blocks))
            if not normal_prior or not normal_bid:
                exclusions.append({"case_id": pair["case_id"], "status": "empty_hwp_text"})
                continue
            distance = bounded_edit_distance(normal_prior, normal_bid)
            if distance is not None:
                exclusions.append({"case_id": pair["case_id"], "status": "text_edit_distance_lte_3", "edit_distance": distance})
                continue
            save_case(pair, prior_document, bid_document, prior_blocks, bid_blocks, normal_prior, normal_bid)
            saved += 1
    run_id = compact_timestamp(datetime.now())
    report = {"run_id": run_id, "collection_window": {"start": args.start, "end": args.end}, "llm_used": False, "request_budget": {"prior_spec_used": prior_used, "bid_notice_used": bid_used}, "source_completion": {"prior_spec": prior_complete, "bid_notice": bid_complete}, "received_rows": {"prior_spec": len(prior_rows), "bid_notice": len(bid_rows)}, "direct_pairs": len(pairs), "pairs_checked": min(len(pairs), args.max_pairs), "saved_changed_pairs": saved, "exclusions": exclusions}
    write_json(RUN_DIR / f"changed_hwp_pairs_{run_id}.json", report)
    print(f"[완료] 직접 연결 {len(pairs)}건 중 변경 HWP pair {saved}건 저장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
