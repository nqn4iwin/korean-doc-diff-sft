from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from _common import (
    CollectionError,
    encode_json,
    fetch_json,
    load_project_env,
    nested_value,
    redact_payload,
    require_env,
    save_snapshot,
)


SEARCH_ENDPOINT = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_ENDPOINT = "https://www.law.go.kr/DRF/lawService.do"


def collect_search(
    *,
    oc: str,
    query: str,
    page: int,
    display: int,
) -> tuple[Path, Any]:
    public_request = {
        "target": "law",
        "type": "JSON",
        "search": 1,
        "query": query,
        "display": display,
        "page": page,
    }
    _, payload = fetch_json(
        SEARCH_ENDPOINT,
        params={"OC": oc, **public_request},
    )
    safe_payload = redact_payload(payload, [oc])
    output_path, _ = save_snapshot(
        encode_json(safe_payload),
        source="국가법령정보 공동활용",
        collection="law",
        endpoint=SEARCH_ENDPOINT,
        public_request=public_request,
    )
    return output_path, safe_payload


def collect_detail(*, oc: str, mst: str) -> tuple[Path, Any]:
    public_request = {
        "target": "law",
        "type": "JSON",
        "MST": mst,
    }
    _, payload = fetch_json(
        DETAIL_ENDPOINT,
        params={"OC": oc, **public_request},
    )
    safe_payload = redact_payload(payload, [oc])
    output_path, _ = save_snapshot(
        encode_json(safe_payload),
        source="국가법령정보 공동활용",
        collection="law_detail",
        endpoint=DETAIL_ENDPOINT,
        public_request=public_request,
    )
    return output_path, safe_payload


def extract_law_rows(payload: Any) -> list[dict[str, Any]]:
    rows = nested_value(payload, "law")
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="국가법령정보 공동활용 API의 현행법령 목록을 수집합니다."
    )
    parser.add_argument("--query", default="개인정보 보호법", help="검색할 법령명")
    parser.add_argument("--page", type=int, default=1, help="결과 페이지")
    parser.add_argument(
        "--display",
        type=int,
        default=5,
        help="페이지당 결과 수(1~100)",
    )
    parser.add_argument(
        "--mst",
        help="검색 대신 법령일련번호(MST)로 현행법령 본문을 조회",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page < 1:
        raise CollectionError("--page는 1 이상이어야 합니다.")
    if not 1 <= args.display <= 100:
        raise CollectionError("--display는 1~100이어야 합니다.")

    load_project_env()
    oc = require_env("LAW_OPEN_API_OC")
    if args.mst:
        output_path, _ = collect_detail(oc=oc, mst=args.mst)
        print(f"저장 완료: {output_path}")
        return 0

    output_path, payload = collect_search(
        oc=oc,
        query=args.query,
        page=args.page,
        display=args.display,
    )
    total = nested_value(payload, "totalCnt")
    print(f"저장 완료: {output_path}")
    if total is not None:
        print(f"검색 결과 수: {total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectionError as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from None
