from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from _common import (
    CollectionError,
    fetch_json,
    load_project_env,
    nested_value,
    require_env,
    save_snapshot,
)


BASE_ENDPOINT = "https://api.odcloud.kr/api/15077093/v1"
ENDPOINTS = (
    "dataset",
    "file-data-list",
    "open-data-list",
    "standard-data-list",
)


def collect_page(
    *,
    service_key: str,
    endpoint_name: str,
    page: int,
    per_page: int,
) -> tuple[Path, Any]:
    if endpoint_name not in ENDPOINTS:
        raise CollectionError(f"지원하지 않는 목록 종류입니다: {endpoint_name}")

    endpoint = f"{BASE_ENDPOINT}/{endpoint_name}"
    public_request = {
        "page": page,
        "perPage": per_page,
        "returnType": "JSON",
    }
    raw, payload = fetch_json(
        endpoint,
        params=public_request,
        headers={"Authorization": f"Infuser {service_key}"},
    )
    output_path, _ = save_snapshot(
        raw,
        source="공공데이터포털 목록조회서비스",
        collection="data_portal",
        endpoint=endpoint,
        public_request={"endpoint": endpoint_name, **public_request},
    )
    return output_path, payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="공공데이터포털 목록조회서비스의 목록을 수집합니다."
    )
    parser.add_argument(
        "--endpoint",
        choices=ENDPOINTS,
        default="dataset",
        help="조회할 목록 종류",
    )
    parser.add_argument("--page", type=int, default=1, help="결과 페이지")
    parser.add_argument(
        "--per-page",
        type=int,
        default=5,
        help="페이지당 결과 수(1~1000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page < 1:
        raise CollectionError("--page는 1 이상이어야 합니다.")
    if not 1 <= args.per_page <= 1000:
        raise CollectionError("--per-page는 1~1000이어야 합니다.")

    load_project_env()
    service_key = require_env("DATA_GO_KR_SERVICE_KEY")
    output_path, payload = collect_page(
        service_key=service_key,
        endpoint_name=args.endpoint,
        page=args.page,
        per_page=args.per_page,
    )

    current_count = nested_value(payload, "currentCount")
    total_count = nested_value(payload, "totalCount")
    print(f"저장 완료: {output_path}")
    if current_count is not None:
        print(f"현재 페이지 결과 수: {current_count}")
    if total_count is not None:
        print(f"전체 결과 수: {total_count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CollectionError as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from None
