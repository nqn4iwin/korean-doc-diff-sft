from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _common import (
    CollectionError,
    REPOSITORY_DIR,
    load_project_env,
    require_env,
)
from data_portal import ENDPOINTS, collect_page
from law import collect_detail, collect_search, extract_law_rows


CORE_LAW_QUERIES = (
    "공공데이터의 제공 및 이용 활성화에 관한 법률",
    "개인정보 보호법",
    "저작권법",
)
STATE_PATH = (
    REPOSITORY_DIR
    / "data"
    / "01_public_data_review"
    / "state"
    / "timed_collection.json"
)


def new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "portal_pages": {endpoint: 1 for endpoint in ENDPOINTS},
        "portal_endpoint_index": 0,
        "law_search_index": 0,
        "law_detail_queue": [],
        "law_completed_msts": [],
        "next_source": "law",
        "success_count": 0,
        "failure_count": 0,
        "updated_at": None,
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return new_state()

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CollectionError(f"상태 파일을 읽을 수 없습니다: {path}") from error

    if state.get("version") != 1:
        raise CollectionError(f"지원하지 않는 상태 파일 버전입니다: {path}")

    defaults = new_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    for endpoint in ENDPOINTS:
        state["portal_pages"].setdefault(endpoint, 1)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary_path.replace(path)


def queue_law_details(state: dict[str, Any], payload: Any) -> int:
    completed = set(state["law_completed_msts"])
    queued = set(state["law_detail_queue"])
    added = 0
    for row in extract_law_rows(payload):
        mst = str(row.get("법령일련번호", "")).strip()
        if mst and mst not in completed and mst not in queued:
            state["law_detail_queue"].append(mst)
            queued.add(mst)
            added += 1
    return added


def collect_next_law(
    state: dict[str, Any],
    *,
    oc: str,
    display: int,
) -> str | None:
    if state["law_detail_queue"]:
        mst = str(state["law_detail_queue"][0])
        output_path, _ = collect_detail(oc=oc, mst=mst)
        state["law_detail_queue"].pop(0)
        state["law_completed_msts"].append(mst)
        return f"Open Law 본문 MST={mst} -> {output_path.name}"

    search_index = int(state["law_search_index"])
    if search_index >= len(CORE_LAW_QUERIES):
        return None

    query = CORE_LAW_QUERIES[search_index]
    output_path, payload = collect_search(
        oc=oc,
        query=query,
        page=1,
        display=display,
    )
    state["law_search_index"] = search_index + 1
    queued = queue_law_details(state, payload)
    return f"Open Law 검색 '{query}' ({queued}개 본문 대기) -> {output_path.name}"


def collect_next_portal(
    state: dict[str, Any],
    *,
    service_key: str,
    per_page: int,
) -> str:
    endpoint_index = int(state["portal_endpoint_index"]) % len(ENDPOINTS)
    endpoint_name = ENDPOINTS[endpoint_index]
    page = int(state["portal_pages"][endpoint_name])
    output_path, payload = collect_page(
        service_key=service_key,
        endpoint_name=endpoint_name,
        page=page,
        per_page=per_page,
    )
    current_count = payload.get("currentCount") if isinstance(payload, dict) else None
    total_count = payload.get("totalCount") if isinstance(payload, dict) else None
    state["portal_pages"][endpoint_name] = page + 1
    state["portal_endpoint_index"] = (endpoint_index + 1) % len(ENDPOINTS)
    return (
        f"공공데이터포털 {endpoint_name} page={page} "
        f"count={current_count}/{total_count} -> {output_path.name}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="두 공식 API를 낮은 빈도로 번갈아 호출하며 표본 raw를 수집합니다."
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=60,
        help="최대 실행 시간(분, 기본 60)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=90,
        help="요청 사이 최소 대기 시간(초, 기본 90)",
    )
    parser.add_argument(
        "--jitter-seconds",
        type=float,
        default=15,
        help="요청 간격에 더할 무작위 대기 상한(초, 기본 15)",
    )
    parser.add_argument(
        "--portal-per-page",
        type=int,
        default=20,
        help="공공데이터포털 요청당 결과 수(기본 20)",
    )
    parser.add_argument(
        "--law-display",
        type=int,
        default=10,
        help="Open Law 검색당 결과 수(기본 10)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        help="시험 실행용 최대 요청 수",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=STATE_PATH,
        help="재개 상태 파일 경로",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API를 호출하지 않고 현재 상태와 설정만 확인",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.duration_minutes <= 0:
        raise CollectionError("--duration-minutes는 0보다 커야 합니다.")
    if args.interval_seconds < 10:
        raise CollectionError("--interval-seconds는 차단 방지를 위해 10 이상이어야 합니다.")
    if args.jitter_seconds < 0:
        raise CollectionError("--jitter-seconds는 0 이상이어야 합니다.")
    if not 1 <= args.portal_per_page <= 1000:
        raise CollectionError("--portal-per-page는 1~1000이어야 합니다.")
    if not 1 <= args.law_display <= 100:
        raise CollectionError("--law-display는 1~100이어야 합니다.")
    if args.max_requests is not None and args.max_requests < 1:
        raise CollectionError("--max-requests는 1 이상이어야 합니다.")


def run(args: argparse.Namespace) -> int:
    validate_args(args)
    state_path = args.state_path.resolve()
    state = load_state(state_path)

    if args.dry_run:
        print(f"상태 파일: {state_path}")
        print(f"다음 원천: {state['next_source']}")
        print(f"법령 검색 진행: {state['law_search_index']}/{len(CORE_LAW_QUERIES)}")
        print(f"법령 본문 대기: {len(state['law_detail_queue'])}건")
        print(f"포털 다음 페이지: {state['portal_pages']}")
        return 0

    load_project_env()
    oc = require_env("LAW_OPEN_API_OC")
    service_key = require_env("DATA_GO_KR_SERVICE_KEY")
    started = time.monotonic()
    deadline = started + args.duration_minutes * 60
    requests_this_run = 0

    print(
        f"수집 시작: 최대 {args.duration_minutes:g}분, "
        f"간격 {args.interval_seconds:g}~"
        f"{args.interval_seconds + args.jitter_seconds:g}초"
    )

    while time.monotonic() < deadline:
        if args.max_requests is not None and requests_this_run >= args.max_requests:
            break

        preferred_source = state["next_source"]
        try:
            message: str | None = None
            if preferred_source == "law":
                message = collect_next_law(
                    state,
                    oc=oc,
                    display=args.law_display,
                )
                state["next_source"] = "portal"
            if message is None:
                message = collect_next_portal(
                    state,
                    service_key=service_key,
                    per_page=args.portal_per_page,
                )
                state["next_source"] = "law"

            state["success_count"] += 1
            print(f"[성공] {message}", flush=True)
        except CollectionError as error:
            state["failure_count"] += 1
            state["next_source"] = "portal" if preferred_source == "law" else "law"
            print(f"[실패] {preferred_source}: {error}", file=sys.stderr, flush=True)
        finally:
            requests_this_run += 1
            save_state(state_path, state)

        if args.max_requests is not None and requests_this_run >= args.max_requests:
            break

        remaining = deadline - time.monotonic()
        delay = args.interval_seconds + random.uniform(0, args.jitter_seconds)
        if remaining <= delay:
            break
        print(f"다음 요청까지 {delay:.1f}초 대기", flush=True)
        time.sleep(delay)

    elapsed = time.monotonic() - started
    print(
        f"수집 종료: 이번 실행 {requests_this_run}회, {elapsed:.1f}초 / "
        f"누적 성공 {state['success_count']}회, 실패 {state['failure_count']}회"
    )
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    args = parse_args()
    try:
        return run(args)
    except CollectionError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n사용자 중단", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
