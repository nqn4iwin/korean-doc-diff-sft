from __future__ import annotations

import argparse
import sys

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


ENDPOINT = "https://www.law.go.kr/DRF/lawSearch.do"


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.page < 1:
        raise CollectionError("--page는 1 이상이어야 합니다.")
    if not 1 <= args.display <= 100:
        raise CollectionError("--display는 1~100이어야 합니다.")

    load_project_env()
    oc = require_env("LAW_OPEN_API_OC")
    public_request = {
        "target": "law",
        "type": "JSON",
        "search": 1,
        "query": args.query,
        "display": args.display,
        "page": args.page,
    }
    raw, payload = fetch_json(
        ENDPOINT,
        params={"OC": oc, **public_request},
    )
    safe_payload = redact_payload(payload, [oc])
    safe_raw = encode_json(safe_payload)
    output_path, _ = save_snapshot(
        safe_raw,
        source="국가법령정보 공동활용",
        collection="law",
        endpoint=ENDPOINT,
        public_request=public_request,
    )

    total = nested_value(safe_payload, "totalCnt")
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
