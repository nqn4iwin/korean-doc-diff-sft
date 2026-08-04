"""Collect one prior-specification batch and measure its document yield.

The service key is read from ``raw_collection/.env`` and is never written to
the snapshot, summary, manifest, or console output.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from test_connections import load_env


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PROJECT_DIR.parent
ENV_PATH = PROJECT_DIR / ".env"
DATA_DIR = REPOSITORY_DIR / "data" / "raw_collection"
API_DIR = DATA_DIR / "raw" / "api"
ATTACHMENT_DIR = DATA_DIR / "raw" / "attachments"
RUN_DIR = DATA_DIR / "runs"
ENDPOINT = (
    "https://apis.data.go.kr/1230000/ao/"
    "HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"
)
KEY_NAME = "G2B_PRIOR_SPEC_SERVICE_KEY"
USER_AGENT = "data-collect/first-hour-yield"
TIMEOUT_SECONDS = 30
DOCUMENT_KEYWORDS = (
    "제안요청",
    "과업지시",
    "과업내용",
    "규격서",
    "제안서",
    "평가기준",
    "rfp",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="사전규격 용역 목록 한 묶음의 첨부문서 수율을 측정합니다."
    )
    parser.add_argument("--target-rows", type=int, default=1000)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument(
        "--download-sample",
        type=int,
        default=30,
        help="우선순위 첨부파일 다운로드 시도 수",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=1.0,
        help="첨부파일 다운로드 요청 사이의 대기 시간(초)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="첨부파일을 내려받지 않고 메타데이터 수율만 측정",
    )
    return parser.parse_args()


def utc_offset_now() -> datetime:
    return datetime.now().astimezone()


def compact_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_metadata_page(
    service_key: str, page_no: int, page_size: int, lookback_days: int
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    query_end = datetime.now()
    query_start = query_end - timedelta(days=lookback_days)
    public_query = {
        "pageNo": page_no,
        "numOfRows": page_size,
        "inqryDiv": 1,
        "inqryBgnDt": query_start.strftime("%Y%m%d%H%M"),
        "inqryEndDt": query_end.strftime("%Y%m%d%H%M"),
        "type": "json",
    }
    secret_query = {
        "serviceKey": urllib.parse.unquote(service_key),
        **public_query,
    }
    request = urllib.request.Request(
        f"{ENDPOINT}?{urllib.parse.urlencode(secret_query)}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type", "")
    elapsed_seconds = round(time.monotonic() - started, 3)

    if status != 200:
        raise RuntimeError(f"목록 API HTTP 상태가 {status}입니다.")
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("목록 API 응답이 JSON 형식이 아닙니다.") from error

    request_info = {
        "endpoint": ENDPOINT,
        "query": public_query,
        "elapsed_seconds": elapsed_seconds,
        "http_status": status,
        "content_type": content_type,
    }
    return payload, data, request_info


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


def first_present(item: dict[str, Any], names: Iterable[str]) -> str | None:
    folded = {str(key).casefold(): value for key, value in item.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def attachment_references(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_index, item in enumerate(items):
        prior_spec_id = first_present(
            item, ("bfSpecRgstNo", "priorSpecId", "prearngPrceDcsnNo")
        )
        title = first_present(
            item, ("prdctClsfcNoNm", "bfSpecNm", "prdctClsfcNoName", "bidNtceNm")
        )
        file_names = {
            str(key).casefold(): str(value).strip()
            for key, value in item.items()
            if value is not None
            and str(value).strip()
            and ("file" in str(key).casefold() or "atch" in str(key).casefold())
            and ("nm" in str(key).casefold() or "name" in str(key).casefold())
        }
        for key, value in item.items():
            key_text = str(key)
            key_folded = key_text.casefold()
            if value is None or not str(value).strip():
                continue
            url = str(value).strip()
            if not (
                url.lower().startswith(("http://", "https://"))
                and ("file" in key_folded or "atch" in key_folded)
            ):
                continue
            if url in seen:
                continue
            seen.add(url)
            suffix = "".join(character for character in key_folded if character.isdigit())
            matching_names = [
                name
                for name_key, name in file_names.items()
                if not suffix
                or suffix
                == "".join(character for character in name_key if character.isdigit())
            ]
            file_name = matching_names[0] if matching_names else None
            searchable = " ".join(filter(None, (title, file_name))).casefold()
            references.append(
                {
                    "row_index": row_index,
                    "prior_spec_id": prior_spec_id,
                    "title": title,
                    "url_field": key_text,
                    "file_name": file_name,
                    "url": url,
                    "document_keyword_match": any(
                        keyword.casefold() in searchable
                        for keyword in DOCUMENT_KEYWORDS
                    ),
                }
            )
    return references


def detected_suffix(
    payload: bytes, file_name: str | None, url: str, content_type: str
) -> str:
    if payload.startswith(b"%PDF-"):
        return ".pdf"
    if payload.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return ".hwp"
    if payload.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            names = set()
        if "mimetype" in names and any(
            name.startswith("Contents/section") for name in names
        ):
            return ".hwpx"
        if "[Content_Types].xml" in names and any(
            name.startswith("word/") for name in names
        ):
            return ".docx"
        return ".zip"

    candidates = []
    if file_name:
        candidates.append(Path(file_name).suffix)
    candidates.append(Path(urllib.parse.urlparse(url).path).suffix)
    for candidate in candidates:
        suffix = candidate.lower()
        if suffix in {".pdf", ".hwp", ".hwpx", ".doc", ".docx", ".zip"}:
            return suffix
    content_type = content_type.casefold()
    if "pdf" in content_type:
        return ".pdf"
    if "zip" in content_type:
        return ".zip"
    return ".bin"


def hwpx_preview_metrics(payload: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            preview = archive.read("Preview/PrvText.txt").decode(
                "utf-8-sig", errors="replace"
            )
    except (KeyError, zipfile.BadZipFile):
        return {
            "text_preview_available": False,
            "text_preview_characters": 0,
            "text_preview_keyword_match": False,
        }
    return {
        "text_preview_available": True,
        "text_preview_characters": len(preview),
        "text_preview_keyword_match": any(
            keyword.casefold() in preview.casefold()
            for keyword in DOCUMENT_KEYWORDS
        ),
    }


def download_attachment(
    reference: dict[str, Any], destination_dir: Path, sequence: int
) -> dict[str, Any]:
    request = urllib.request.Request(
        reference["url"],
        headers={"Accept": "*/*", "User-Agent": USER_AGENT},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        return {
            **reference,
            "download_status": "failed",
            "error_type": type(error).__name__,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }

    suffix = detected_suffix(
        payload, reference.get("file_name"), reference["url"], content_type
    )
    preview_metrics = (
        hwpx_preview_metrics(payload)
        if suffix == ".hwpx"
        else {
            "text_preview_available": None,
            "text_preview_characters": None,
            "text_preview_keyword_match": None,
        }
    )
    digest = sha256_bytes(payload)
    destination = destination_dir / f"{sequence:04d}_{digest[:16]}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return {
        **reference,
        "download_status": "success",
        "http_status": status,
        "content_type": content_type,
        "byte_size": len(payload),
        "sha256": digest,
        "local_path": destination.relative_to(REPOSITORY_DIR).as_posix(),
        "detected_suffix": suffix,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        **preview_metrics,
    }


def select_download_sample(
    references: list[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    ranked = sorted(
        references,
        key=lambda item: (
            not item["document_keyword_match"],
            item["row_index"],
            item.get("file_name") or "",
        ),
    )
    return ranked[:sample_size]


def summarize(
    items: list[dict[str, Any]],
    references: list[dict[str, Any]],
    downloads: list[dict[str, Any]],
    request_info: dict[str, Any],
    total_count: Any,
) -> dict[str, Any]:
    rows_with_attachments = {item["row_index"] for item in references}
    keyword_rows = {
        item["row_index"] for item in references if item["document_keyword_match"]
    }
    id_values = [
        first_present(item, ("bfSpecRgstNo", "priorSpecId"))
        for item in items
    ]
    unique_ids = {value for value in id_values if value}
    successful = [
        item for item in downloads if item["download_status"] == "success"
    ]
    suffix_counts: dict[str, int] = {}
    for item in successful:
        suffix = item["detected_suffix"]
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    preview_candidates = [
        item for item in successful if item["detected_suffix"] == ".hwpx"
    ]
    preview_available = [
        item for item in preview_candidates if item.get("text_preview_available")
    ]
    preview_keyword_matches = [
        item
        for item in preview_available
        if item.get("text_preview_keyword_match")
    ]
    return {
        "collected_at": utc_offset_now().isoformat(),
        "request": request_info,
        "api_total_count": total_count,
        "received_rows": len(items),
        "unique_prior_spec_ids": len(unique_ids),
        "duplicate_or_missing_id_rows": len(items) - len(unique_ids),
        "rows_with_attachment_url": len(rows_with_attachments),
        "attachment_url_references": len(references),
        "rows_with_document_keyword": len(keyword_rows),
        "attachment_url_yield": (
            round(len(rows_with_attachments) / len(items), 4) if items else 0
        ),
        "document_keyword_yield": (
            round(len(keyword_rows) / len(items), 4) if items else 0
        ),
        "download_attempts": len(downloads),
        "download_successes": len(successful),
        "download_success_rate": (
            round(len(successful) / len(downloads), 4) if downloads else None
        ),
        "downloaded_format_counts": suffix_counts,
        "hwpx_preview_candidates": len(preview_candidates),
        "hwpx_preview_available": len(preview_available),
        "hwpx_preview_keyword_matches": len(preview_keyword_matches),
        "response_fields": sorted(
            {str(key) for item in items for key in item.keys()},
            key=str.casefold,
        ),
    }


def main() -> int:
    args = parse_args()
    if not 1 <= args.target_rows <= 1000:
        print("[실패] --target-rows는 1~1000이어야 합니다.")
        return 2
    if args.lookback_days < 1 or args.download_sample < 0:
        print("[실패] 조회기간과 다운로드 표본 수를 확인하세요.")
        return 2
    if not ENV_PATH.is_file():
        print("[실패] raw_collection/.env 파일이 없습니다.")
        return 2
    service_key = load_env(ENV_PATH).get(KEY_NAME, "")
    if not service_key:
        print(f"[실패] {KEY_NAME} 값이 없습니다.")
        return 2

    run_started = utc_offset_now()
    run_id = compact_timestamp(run_started)
    page_count = (args.target_rows + 998) // 999
    page_size = (args.target_rows + page_count - 1) // page_count
    items: list[dict[str, Any]] = []
    request_pages: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    total_count: Any = None
    for page_no in range(1, page_count + 1):
        try:
            payload, data, page_info = fetch_metadata_page(
                service_key, page_no, page_size, args.lookback_days
            )
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            RuntimeError,
        ) as error:
            print(f"[실패] 목록 {page_no}페이지 수집: {type(error).__name__}")
            return 1

        result_code = str(find_value(data, "resultCode") or "")
        if result_code not in {"0", "00", "000"}:
            print(
                f"[실패] 목록 {page_no}페이지 "
                f"API 응답코드={result_code or '없음'}"
            )
            return 1
        page_items = response_items(data)
        items.extend(page_items)
        request_pages.append(page_info)
        if total_count is None:
            total_count = find_value(data, "totalCount")

        snapshot_path = (
            API_DIR / f"prior_spec_service_{run_id}_p{page_no:03d}.json"
        )
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(payload)
        snapshots.append(
            {
                "path": snapshot_path.relative_to(REPOSITORY_DIR).as_posix(),
                "byte_size": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
        if len(page_items) < page_size:
            break

    items = items[: args.target_rows]
    request_info = {
        "target_rows": args.target_rows,
        "page_size": page_size,
        "pages_requested": len(request_pages),
        "elapsed_seconds": round(
            sum(float(page["elapsed_seconds"]) for page in request_pages), 3
        ),
        "pages": request_pages,
    }

    references = attachment_references(items)
    downloads: list[dict[str, Any]] = []
    if not args.metadata_only and args.download_sample:
        sample = select_download_sample(references, args.download_sample)
        destination_dir = ATTACHMENT_DIR / run_id
        for sequence, reference in enumerate(sample, start=1):
            downloads.append(
                download_attachment(reference, destination_dir, sequence)
            )
            if sequence < len(sample) and args.request_delay:
                time.sleep(args.request_delay)

    summary = summarize(
        items, references, downloads, request_info, total_count
    )
    summary["snapshots"] = snapshots
    summary_path = RUN_DIR / f"first_hour_yield_{run_id}.summary.json"
    downloads_path = RUN_DIR / f"first_hour_yield_{run_id}.downloads.json"
    write_json(summary_path, summary)
    write_json(downloads_path, downloads)

    print(
        f"[완료] 응답 {summary['received_rows']}건, "
        f"고유 ID {summary['unique_prior_spec_ids']}건"
    )
    print(
        f"첨부 URL 보유 {summary['rows_with_attachment_url']}건 "
        f"({summary['attachment_url_yield']:.1%}), "
        f"문서 키워드 {summary['rows_with_document_keyword']}건 "
        f"({summary['document_keyword_yield']:.1%})"
    )
    if downloads:
        print(
            f"다운로드 {summary['download_successes']}/"
            f"{summary['download_attempts']}건 성공"
        )
    print(
        "요약: "
        f"{summary_path.relative_to(REPOSITORY_DIR).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
