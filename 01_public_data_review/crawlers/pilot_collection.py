from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from _common import (
    CollectionError,
    MANIFEST_PATH,
    REPOSITORY_DIR,
    fetch_json,
    load_project_env,
    nested_value,
    redact_payload,
    require_env,
    save_snapshot,
)
from data_portal import BASE_ENDPOINT, ENDPOINTS


SEARCH_ENDPOINT = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_ENDPOINT = "https://www.law.go.kr/DRF/lawService.do"
PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = REPOSITORY_DIR / "data" / "01_public_data_review" / "state"
STATE_PATH = STATE_DIR / "pilot_collection.json"
LOG_PATH = STATE_DIR / "pilot_collection.log"
LOCK_PATH = STATE_DIR / "pilot_collection.lock"
WARNING_PATH = PROJECT_DIR / "WARNING.md"
DETAIL_SAMPLE_PATH = (
    REPOSITORY_DIR
    / "data"
    / "01_public_data_review"
    / "interim"
    / "pilot_detail_sample.jsonl"
)

CORE_LAW_NAMES = (
    "공공데이터의 제공 및 이용 활성화에 관한 법률",
    "개인정보 보호법",
    "저작권법",
)
PORTAL_PER_PAGE = 1000
LAW_DISPLAY = 100
APPROVAL_ERROR_MARKERS = ("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_catalog_state() -> dict[str, Any]:
    return {
        "next_page": 1,
        "total_count": None,
        "rows_received": 0,
        "requests": 0,
        "complete": False,
        "blocked": False,
        "block_reason": None,
    }


def new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "status": "READY",
        "pid": None,
        "started_at": None,
        "updated_at": None,
        "completed_at": None,
        "success_count": 0,
        "failure_count": 0,
        "consecutive_failures": 0,
        "last_error": None,
        "scheduler_index": 0,
        "portal": {endpoint: new_catalog_state() for endpoint in ENDPOINTS},
        "law_catalog": new_catalog_state(),
        "admrul_catalog": new_catalog_state(),
        "anchors": {
            "relation_parser_version": 2,
            "next_search_index": 0,
            "found_exact_names": [],
            "detail_queue": [],
            "relation_queue": [],
            "completed_details": [],
            "completed_relations": [],
            "failed_items": [],
        },
        "detail_sample": {
            "built": False,
            "selected": 0,
            "queue": [],
            "completed": [],
            "failed": [],
            "manual_only": [],
        },
    }


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
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
        state["portal"].setdefault(endpoint, new_catalog_state())
    previous_relation_parser_version = int(
        state["anchors"].get("relation_parser_version", 0)
    )
    for key, value in defaults["anchors"].items():
        state["anchors"].setdefault(key, value)
    for key, value in defaults["detail_sample"].items():
        state["detail_sample"].setdefault(key, value)
    if previous_relation_parser_version < 2:
        for completed_key in state["anchors"]["completed_relations"]:
            parts = str(completed_key).split(":")
            if len(parts) == 3 and parts[0] == "law" and parts[1] == "MST":
                enqueue_unique(
                    state["anchors"]["relation_queue"],
                    {
                        "target": "law",
                        "id_kind": "MST",
                        "identifier": parts[2],
                        "name": "",
                    },
                )
        state["anchors"]["completed_relations"] = []
        state["anchors"]["relation_parser_version"] = 2
    state["anchors"]["detail_queue"] = [
        item
        for item in state["anchors"]["detail_queue"]
        if re.fullmatch(r"\d+", str(item.get("identifier", "")))
    ]
    state["anchors"]["relation_queue"] = [
        item
        for item in state["anchors"]["relation_queue"]
        if re.fullmatch(r"\d+", str(item.get("identifier", "")))
    ]
    return state


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def log(message: str, *, error: bool = False) -> None:
    timestamp = utc_now()
    line = f"{timestamp} {'ERROR' if error else 'INFO'} {message}"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(line + "\n")
    print(line, file=sys.stderr if error else sys.stdout, flush=True)


def process_is_running(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            success = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            )
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(success) and exit_code.value == 259
        except (OSError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def is_stale(state: dict[str, Any], *, seconds: int = 300) -> bool:
    updated_at = state.get("updated_at")
    if not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - updated).total_seconds() > seconds


def progress_lines(state: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for endpoint in ENDPOINTS:
        item = state["portal"][endpoint]
        total = item["total_count"] if item["total_count"] is not None else "?"
        lines.append(
            f"- 공공데이터 `{endpoint}`: {item['rows_received']}/{total}행, "
            f"다음 {item['next_page']}페이지, "
            f"{'완료' if item['complete'] else '진행 중'}"
        )
    for label, key in (
        ("Open Law 현행 법령 목록", "law_catalog"),
        ("Open Law 행정규칙 목록", "admrul_catalog"),
    ):
        item = state[key]
        total = item["total_count"] if item["total_count"] is not None else "?"
        if item["blocked"]:
            condition = f"제한됨 — {item['block_reason']}"
        else:
            condition = "완료" if item["complete"] else "진행 중"
        lines.append(
            f"- {label}: {item['rows_received']}/{total}행, "
            f"다음 {item['next_page']}페이지, {condition}"
        )
    anchors = state["anchors"]
    lines.append(
        f"- 기준 법령: 정확 일치 {len(anchors['found_exact_names'])}/"
        f"{len(CORE_LAW_NAMES)}, 본문 {len(anchors['completed_details'])}건, "
        f"공식 관계 {len(anchors['completed_relations'])}건"
    )
    sample = state["detail_sample"]
    lines.append(
        f"- 상세 판독 표본: 선정 {sample['selected']}건, "
        f"상세 raw {len(sample['completed'])}건, "
        f"수동 판독 {len(sample['manual_only'])}건, 실패 {len(sample['failed'])}건"
    )
    return lines


def write_warning(state: dict[str, Any], status: str, message: str) -> None:
    state_status = status.upper()
    content = [
        "# 수집 상태",
        "",
        f"**{state_status}** — {message}",
        "",
        f"- 마지막 heartbeat: `{state.get('updated_at') or utc_now()}`",
        f"- PID: `{state.get('pid') or '-'}`",
        f"- 누적 성공/실패: `{state.get('success_count', 0)}/"
        f"{state.get('failure_count', 0)}`",
        f"- 마지막 오류: `{state.get('last_error') or '-'}`",
        "",
        "## 진행률",
        "",
        *progress_lines(state),
        "",
        "## 확인 위치",
        "",
        "- 상태: `data/01_public_data_review/state/pilot_collection.json`",
        "- 로그: `data/01_public_data_review/state/pilot_collection.log`",
        (
            "- 명령: "
            "`python .\\01_public_data_review\\crawlers\\pilot_collection.py --status`"
        ),
        "",
        "상태가 `RUNNING`이어도 heartbeat가 5분 이상 갱신되지 않으면 "
        "프로세스 중단 여부를 확인해야 합니다.",
        "",
    ]
    temporary = WARNING_PATH.with_suffix(".tmp")
    temporary.write_text("\n".join(content), encoding="utf-8", newline="\n")
    temporary.replace(WARNING_PATH)


def acquire_lock() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if process_is_running(pid):
            raise CollectionError(f"수집기가 이미 실행 중입니다(PID={pid}).")
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8", newline="\n")


def release_lock() -> None:
    try:
        if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(
            os.getpid()
        ):
            LOCK_PATH.unlink()
    except OSError:
        pass


def collect_portal_page(
    *,
    service_key: str,
    endpoint_name: str,
    page: int,
) -> Any:
    endpoint = f"{BASE_ENDPOINT}/{endpoint_name}"
    public_request = {
        "endpoint": endpoint_name,
        "page": page,
        "perPage": PORTAL_PER_PAGE,
        "returnType": "JSON",
    }
    raw, payload = fetch_json(
        endpoint,
        params={key: value for key, value in public_request.items() if key != "endpoint"},
        headers={"Authorization": f"Infuser {service_key}"},
        timeout=90,
        attempts=4,
    )
    save_snapshot(
        raw,
        source="공공데이터포털 목록조회서비스",
        collection="data_portal_inventory",
        endpoint=endpoint,
        public_request=public_request,
    )
    return payload


def collect_open_law_list(
    *,
    oc: str,
    target: str,
    page: int,
    query: str | None = None,
    collection: str,
) -> Any:
    public_request: dict[str, str | int] = {
        "target": target,
        "type": "JSON",
        "display": LAW_DISPLAY,
        "page": page,
    }
    if query:
        public_request.update({"search": 1, "query": query})
    _, payload = fetch_json(
        SEARCH_ENDPOINT,
        params={"OC": oc, **public_request},
        timeout=90,
        attempts=4,
    )
    safe_payload = redact_payload(payload, [oc])
    save_snapshot(
        json.dumps(
            safe_payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
        source="국가법령정보 공동활용",
        collection=collection,
        endpoint=SEARCH_ENDPOINT,
        public_request=public_request,
    )
    return safe_payload


def collect_open_law_detail(
    *,
    oc: str,
    target: str,
    identifier: str,
    id_kind: str,
) -> Any:
    public_request: dict[str, str | int] = {
        "target": target,
        "type": "JSON",
        id_kind: identifier,
    }
    _, payload = fetch_json(
        DETAIL_ENDPOINT,
        params={"OC": oc, **public_request},
        timeout=90,
        attempts=4,
    )
    safe_payload = redact_payload(payload, [oc])
    save_snapshot(
        json.dumps(
            safe_payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
        source="국가법령정보 공동활용",
        collection=f"{target}_pilot_detail",
        endpoint=DETAIL_ENDPOINT,
        public_request=public_request,
    )
    return safe_payload


def collect_law_relations(*, oc: str, mst: str) -> Any:
    public_request: dict[str, str | int] = {
        "target": "lsDelegated",
        "type": "JSON",
        "MST": mst,
    }
    _, payload = fetch_json(
        DETAIL_ENDPOINT,
        params={"OC": oc, **public_request},
        timeout=90,
        attempts=4,
    )
    safe_payload = redact_payload(payload, [oc])
    save_snapshot(
        json.dumps(
            safe_payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
        source="국가법령정보 공동활용",
        collection="law_relations",
        endpoint=DETAIL_ENDPOINT,
        public_request=public_request,
    )
    return safe_payload


def collect_portal_detail(*, url: str, candidate_id: str, tier: str) -> Any:
    raw, payload = fetch_json(url, params={}, timeout=90, attempts=4)
    save_snapshot(
        raw,
        source="공공데이터포털 상세 메타데이터",
        collection="data_portal_detail_sample",
        endpoint=url,
        public_request={"candidate_id": candidate_id, "tier": tier},
    )
    return payload


def nested_dicts(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from nested_dicts(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from nested_dicts(value)


def extract_rows(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        rows = nested_value(payload, key)
        if isinstance(rows, dict):
            return [rows]
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def normalized_name(row: dict[str, Any]) -> str:
    for key in ("법령명한글", "법령명_한글", "행정규칙명"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def enqueue_unique(queue: list[dict[str, str]], item: dict[str, str]) -> bool:
    identity = (item.get("target"), item.get("id_kind"), item.get("identifier"))
    if not all(identity):
        return False
    if any(
        (row.get("target"), row.get("id_kind"), row.get("identifier")) == identity
        for row in queue
    ):
        return False
    queue.append(item)
    return True


def queue_anchor_rows(state: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    anchors = state["anchors"]
    completed_details = set(anchors["completed_details"])
    completed_relations = set(anchors["completed_relations"])
    for row in rows:
        name = normalized_name(row)
        if name in CORE_LAW_NAMES and name not in anchors["found_exact_names"]:
            anchors["found_exact_names"].append(name)
        mst = str(row.get("법령일련번호", "")).strip()
        law_id = str(row.get("법령ID", "")).strip()
        identifier = mst or law_id
        id_kind = "MST" if mst else "ID"
        key = f"law:{id_kind}:{identifier}"
        if identifier and key not in completed_details:
            enqueue_unique(
                anchors["detail_queue"],
                {
                    "target": "law",
                    "id_kind": id_kind,
                    "identifier": identifier,
                    "name": name,
                },
            )
        relation_key = f"law:MST:{mst}"
        if mst and relation_key not in completed_relations:
            enqueue_unique(
                anchors["relation_queue"],
                {
                    "target": "law",
                    "id_kind": "MST",
                    "identifier": mst,
                    "name": name,
                },
            )


def queue_relation_targets(state: dict[str, Any], payload: Any) -> int:
    anchors = state["anchors"]
    completed = set(anchors["completed_details"])
    added = 0
    for row in nested_dicts(payload):
        admrul_values = (
            row.get("위임행정규칙일련번호"),
            row.get("행정규칙일련번호"),
            row.get("행정규칙ID"),
        )
        for target, id_kind, values in (
            ("admrul", "ID", admrul_values),
            ("law", "MST", (row.get("위임법령일련번호"),)),
            ("law", "ID", (row.get("위임법령ID"),)),
        ):
            for value in values:
                if isinstance(value, (dict, list)) or value is None:
                    continue
                for identifier in re.findall(r"\d+", str(value)):
                    item = {
                        "target": target,
                        "id_kind": id_kind,
                        "identifier": identifier,
                        "name": "",
                    }
                    key = f"{target}:{id_kind}:{identifier}"
                    if key not in completed:
                        if enqueue_unique(anchors["detail_queue"], item):
                            added += 1
    return added


def update_catalog_progress(
    catalog: dict[str, Any],
    *,
    page: int,
    row_count: int,
    total_count: int,
    per_page: int,
) -> None:
    catalog["requests"] += 1
    catalog["rows_received"] += row_count
    catalog["total_count"] = total_count
    catalog["next_page"] = page + 1
    if row_count == 0 or page * per_page >= total_count:
        catalog["complete"] = True


def text_value(record: dict[str, Any]) -> str:
    values = []
    for key in (
        "title",
        "list_title",
        "desc",
        "keywords",
        "etc",
        "data_limit",
        "ownership_grounds",
        "share_scope_nm",
        "share_scope_reason",
        "response_param_nm",
    ):
        value = record.get(key)
        if value not in (None, "", "-", " "):
            values.append(str(value))
    return " ".join(values).lower()


def risk_score(record: dict[str, Any]) -> tuple[int, list[str]]:
    text = text_value(record)
    score = 0
    reasons: list[str] = []
    keyword_groups = {
        "personal_information": (
            "개인정보",
            "주민등록",
            "생년월일",
            "전화번호",
            "이메일",
            "민감정보",
            "건강정보",
            "환자",
            "아동",
            "장애인",
            "노인",
            "위치정보",
        ),
        "rights_and_commercial_use": (
            "저작권",
            "제3자 권리",
            "상업적 이용",
            "재배포",
            "이용허락",
            "출처표시",
            "소유권",
        ),
        "external_transfer": (
            "국외",
            "해외",
            "외부 전송",
            "외부전송",
            "제3자 제공",
        ),
    }
    for reason, keywords in keyword_groups.items():
        matches = sum(keyword in text for keyword in keywords)
        if matches:
            score += min(6, matches * 2)
            reasons.append(reason)

    third_party = str(record.get("is_third_party_copyrighted", "")).strip()
    if third_party and third_party not in {"N", "없음", "-", "해당없음"}:
        score += 5
        reasons.append("third_party_rights_field")
    if str(record.get("is_copyrighted", "")).strip() == "Y":
        score += 2
        reasons.append("copyright_field")
    charged = str(record.get("is_charged", "")).strip()
    if charged and charged not in {"N", "무료", "-", "없음"}:
        score += 3
        reasons.append("charged_use")
    if not str(record.get("ownership_grounds", "") or "").strip():
        reasons.append("ownership_ground_missing")
    if str(record.get("data_limit", "") or "").strip():
        score += 2
        reasons.append("data_limit")
    return score, sorted(set(reasons))


def stable_order_key(record: dict[str, Any]) -> str:
    return hashlib.sha256(str(record["candidate_id"]).encode("utf-8")).hexdigest()


def load_portal_candidates() -> list[dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        raise CollectionError("manifest가 없어 상세 판독 표본을 만들 수 없습니다.")
    manifest_rows = []
    for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("collection") == "data_portal_inventory":
            manifest_rows.append(row)

    candidates: dict[str, dict[str, Any]] = {}
    for manifest in manifest_rows:
        path = REPOSITORY_DIR / manifest["file"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        endpoint = str(manifest["request"]["endpoint"])
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            candidate_id = str(
                raw_row.get("list_id") or raw_row.get("id") or ""
            ).strip()
            if not candidate_id:
                continue
            current = candidates.setdefault(
                candidate_id,
                {
                    "candidate_id": candidate_id,
                    "sources": [],
                },
            )
            if endpoint not in current["sources"]:
                current["sources"].append(endpoint)
            for key, value in raw_row.items():
                if value not in (None, "", "-", " ") and current.get(key) in (
                    None,
                    "",
                    "-",
                    " ",
                ):
                    current[key] = value
                elif key not in current:
                    current[key] = value

    output = []
    for candidate in candidates.values():
        score, reasons = risk_score(candidate)
        candidate["risk_score"] = score
        candidate["risk_reasons"] = reasons
        detail_url = str(candidate.get("meta_url", "") or "").strip()
        candidate["detail_url"] = (
            detail_url
            if detail_url.startswith("https://www.data.go.kr/catalog/")
            and detail_url.endswith(".json")
            else None
        )
        output.append(candidate)
    return output


def take_stratified(
    pool: list[dict[str, Any]],
    count: int,
    *,
    used: set[str],
) -> list[dict[str, Any]]:
    available = [
        row for row in pool if str(row["candidate_id"]) not in used
    ]
    available.sort(
        key=lambda row: (
            0 if row.get("detail_url") else 1,
            -int(row["risk_score"]),
            stable_order_key(row),
        )
    )
    selected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    while available and len(selected) < count:
        available.sort(
            key=lambda row: (
                min(source_counts.get(source, 0) for source in row["sources"]),
                0 if row.get("detail_url") else 1,
                -int(row["risk_score"]),
                stable_order_key(row),
            )
        )
        row = available.pop(0)
        selected.append(row)
        used.add(str(row["candidate_id"]))
        for source in row["sources"]:
            source_counts[source] = source_counts.get(source, 0) + 1
    return selected


def prepare_detail_sample(state: dict[str, Any]) -> str:
    candidates = load_portal_candidates()
    high = [row for row in candidates if int(row["risk_score"]) >= 5]
    boundary = [row for row in candidates if 1 <= int(row["risk_score"]) < 5]
    control = [row for row in candidates if int(row["risk_score"]) == 0]
    used: set[str] = set()
    selected: list[dict[str, Any]] = []
    for tier, pool, count in (
        ("priority", high, 60),
        ("boundary", boundary, 20),
        ("control", control, 20),
    ):
        tier_rows = take_stratified(pool, count, used=used)
        for row in tier_rows:
            row["tier"] = tier
            selected.append(row)

    if len(selected) < 100:
        remainder = [row for row in candidates if row["candidate_id"] not in used]
        for row in take_stratified(remainder, 100 - len(selected), used=used):
            row["tier"] = "fill"
            selected.append(row)

    DETAIL_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DETAIL_SAMPLE_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    sample_state = state["detail_sample"]
    sample_state["selected"] = len(selected)
    sample_state["queue"] = [
        {
            "candidate_id": str(row["candidate_id"]),
            "tier": str(row["tier"]),
            "url": str(row["detail_url"]),
            "attempts": 0,
        }
        for row in selected
        if row.get("detail_url")
    ]
    sample_state["manual_only"] = [
        str(row["candidate_id"]) for row in selected if not row.get("detail_url")
    ]
    sample_state["built"] = True
    return (
        f"상세 판독 표본 {len(selected)}건 선정, "
        f"상세 API {len(sample_state['queue'])}건, "
        f"목록 기반 수동 판독 {len(sample_state['manual_only'])}건"
    )


def catalog_task_names(state: dict[str, Any]) -> list[str]:
    tasks: list[str] = []
    for endpoint in ENDPOINTS:
        if not state["portal"][endpoint]["complete"]:
            tasks.append(f"portal:{endpoint}")
    if not state["law_catalog"]["complete"] and not state["law_catalog"]["blocked"]:
        tasks.append("law_catalog")
    if (
        not state["admrul_catalog"]["complete"]
        and not state["admrul_catalog"]["blocked"]
    ):
        tasks.append("admrul_catalog")
    anchors = state["anchors"]
    if anchors["next_search_index"] < len(CORE_LAW_NAMES):
        tasks.append("anchor_search")
    if anchors["detail_queue"]:
        tasks.append("anchor_detail")
    if anchors["relation_queue"]:
        tasks.append("anchor_relation")
    if all(state["portal"][endpoint]["complete"] for endpoint in ENDPOINTS):
        sample = state["detail_sample"]
        if not sample["built"]:
            tasks.append("prepare_detail_sample")
        elif sample["queue"]:
            tasks.append("portal_detail")
    return tasks


def choose_task(state: dict[str, Any]) -> str | None:
    tasks = catalog_task_names(state)
    if not tasks:
        return None
    index = int(state["scheduler_index"]) % len(tasks)
    state["scheduler_index"] = index + 1
    return tasks[index]


def perform_task(
    state: dict[str, Any],
    task: str,
    *,
    oc: str,
    service_key: str,
) -> str:
    if task.startswith("portal:"):
        endpoint = task.split(":", 1)[1]
        catalog = state["portal"][endpoint]
        page = int(catalog["next_page"])
        payload = collect_portal_page(
            service_key=service_key,
            endpoint_name=endpoint,
            page=page,
        )
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        total = int(payload.get("totalCount", 0)) if isinstance(payload, dict) else 0
        current = (
            int(payload.get("currentCount", len(rows)))
            if isinstance(payload, dict)
            else len(rows)
        )
        if page == 1 and total > PORTAL_PER_PAGE and current != PORTAL_PER_PAGE:
            raise CollectionError(
                f"{endpoint} 1,000행 시험 실패: currentCount={current}"
            )
        update_catalog_progress(
            catalog,
            page=page,
            row_count=len(rows),
            total_count=total,
            per_page=PORTAL_PER_PAGE,
        )
        return f"공공데이터 {endpoint} page={page} {len(rows)}/{total}행"

    if task in {"law_catalog", "admrul_catalog"}:
        target = "law" if task == "law_catalog" else "admrul"
        catalog = state[task]
        page = int(catalog["next_page"])
        payload = collect_open_law_list(
            oc=oc,
            target=target,
            page=page,
            collection=f"{target}_inventory",
        )
        row_keys = ("law", "법령", "admrul", "행정규칙")
        rows = extract_rows(payload, row_keys)
        total_value = nested_value(payload, "totalCnt")
        total = int(total_value or 0)
        if page == 1 and total > LAW_DISPLAY and len(rows) != LAW_DISPLAY:
            raise CollectionError(
                f"{target} 100행 목록 시험 실패: rows={len(rows)}, total={total}"
            )
        update_catalog_progress(
            catalog,
            page=page,
            row_count=len(rows),
            total_count=total,
            per_page=LAW_DISPLAY,
        )
        return f"Open Law {target} 목록 page={page} {len(rows)}/{total}행"

    anchors = state["anchors"]
    if task == "anchor_search":
        index = int(anchors["next_search_index"])
        query = CORE_LAW_NAMES[index]
        payload = collect_open_law_list(
            oc=oc,
            target="law",
            page=1,
            query=query,
            collection="law_anchor_search",
        )
        rows = extract_rows(payload, ("law", "법령"))
        queue_anchor_rows(state, rows)
        anchors["next_search_index"] = index + 1
        return f"기준 법령 검색 '{query}' 결과 {len(rows)}건"

    if task == "anchor_detail":
        item = anchors["detail_queue"][0]
        collect_open_law_detail(
            oc=oc,
            target=item["target"],
            identifier=item["identifier"],
            id_kind=item["id_kind"],
        )
        key = f"{item['target']}:{item['id_kind']}:{item['identifier']}"
        anchors["detail_queue"].pop(0)
        if key not in anchors["completed_details"]:
            anchors["completed_details"].append(key)
        return f"후보 본문 {key} {item.get('name', '')}".rstrip()

    if task == "anchor_relation":
        item = anchors["relation_queue"][0]
        payload = collect_law_relations(oc=oc, mst=item["identifier"])
        added = queue_relation_targets(state, payload)
        key = f"law:MST:{item['identifier']}"
        anchors["relation_queue"].pop(0)
        if key not in anchors["completed_relations"]:
            anchors["completed_relations"].append(key)
        return f"공식 관계 {key}, 본문 후보 {added}건 추가"

    if task == "prepare_detail_sample":
        return prepare_detail_sample(state)

    if task == "portal_detail":
        item = state["detail_sample"]["queue"][0]
        collect_portal_detail(
            url=item["url"],
            candidate_id=item["candidate_id"],
            tier=item["tier"],
        )
        state["detail_sample"]["queue"].pop(0)
        state["detail_sample"]["completed"].append(item["candidate_id"])
        return (
            f"공공데이터 상세 {item['candidate_id']} "
            f"tier={item['tier']}"
        )

    raise CollectionError(f"알 수 없는 작업입니다: {task}")


def mark_approval_block(state: dict[str, Any], task: str, reason: str) -> bool:
    if not any(marker in reason for marker in APPROVAL_ERROR_MARKERS):
        return False
    if task == "admrul_catalog":
        state["admrul_catalog"]["blocked"] = True
        state["admrul_catalog"]["block_reason"] = reason
        return True
    if task == "anchor_detail":
        item = state["anchors"]["detail_queue"][0]
        if item.get("target") == "admrul":
            state["anchors"]["failed_items"].append({**item, "reason": reason})
            state["anchors"]["detail_queue"].pop(0)
            return True
    return False


def has_partial_completion(state: dict[str, Any]) -> bool:
    if state["admrul_catalog"]["blocked"]:
        return True
    if state["anchors"]["failed_items"]:
        return True
    return bool(state["detail_sample"]["failed"])


def validate_args(args: argparse.Namespace) -> None:
    if args.interval_seconds < 10:
        raise CollectionError("--interval-seconds는 10 이상이어야 합니다.")
    if args.jitter_seconds < 0:
        raise CollectionError("--jitter-seconds는 0 이상이어야 합니다.")
    if args.max_requests is not None and args.max_requests < 1:
        raise CollectionError("--max-requests는 1 이상이어야 합니다.")


def print_status(state: dict[str, Any]) -> int:
    running = process_is_running(state.get("pid"))
    stale = state.get("status") == "RUNNING" and is_stale(state)
    print(f"상태: {state.get('status')}")
    print(f"PID: {state.get('pid') or '-'} ({'실행 중' if running else '없음'})")
    print(f"마지막 heartbeat: {state.get('updated_at') or '-'}")
    for line in progress_lines(state):
        print(line)
    if state.get("last_error"):
        print(f"마지막 오류: {state['last_error']}")
    if stale or (state.get("status") == "RUNNING" and not running):
        message = "heartbeat 또는 PID 확인 결과 수집기가 중단된 것으로 보입니다."
        state["status"] = "WARNING"
        state["last_error"] = message
        save_state(state)
        write_warning(state, "WARNING", message)
        print(f"WARNING: {message}")
        return 2
    return 0


def run(args: argparse.Namespace) -> int:
    validate_args(args)
    state = load_state()
    if args.status:
        return print_status(state)

    acquire_lock()
    try:
        load_project_env()
        oc = require_env("LAW_OPEN_API_OC")
        service_key = require_env("DATA_GO_KR_SERVICE_KEY")
        if not state["started_at"]:
            state["started_at"] = utc_now()
        state["status"] = "RUNNING"
        state["pid"] = os.getpid()
        state["last_error"] = None
        save_state(state)
        write_warning(state, "RUNNING", "파일럿 전체 목록 수집이 진행 중입니다.")
        log(
            f"수집 시작 PID={os.getpid()}, 간격 "
            f"{args.interval_seconds:g}~"
            f"{args.interval_seconds + args.jitter_seconds:g}초"
        )

        requests_this_run = 0
        while True:
            task = choose_task(state)
            if task is None:
                break
            if (
                args.max_requests is not None
                and requests_this_run >= args.max_requests
            ):
                state["status"] = "PAUSED"
                state["pid"] = None
                save_state(state)
                write_warning(state, "PAUSED", "시험 요청 한도에서 정상 정지했습니다.")
                log(f"시험 요청 한도 {args.max_requests}회에서 정지")
                return 0

            try:
                message = perform_task(
                    state,
                    task,
                    oc=oc,
                    service_key=service_key,
                )
                state["success_count"] += 1
                state["consecutive_failures"] = 0
                state["last_error"] = None
                state["status"] = "RUNNING"
                log(f"[성공] {message}")
            except CollectionError as error:
                reason = str(error)
                state["failure_count"] += 1
                state["consecutive_failures"] += 1
                state["last_error"] = f"{task}: {reason}"
                state["status"] = "WARNING"
                blocked = mark_approval_block(state, task, reason)
                if task == "portal_detail":
                    item = state["detail_sample"]["queue"][0]
                    item["attempts"] = int(item.get("attempts", 0)) + 1
                    if item["attempts"] >= 3:
                        state["detail_sample"]["failed"].append(
                            {**item, "reason": reason}
                        )
                        state["detail_sample"]["queue"].pop(0)
                        blocked = True
                log(
                    f"[{'제한' if blocked else '실패'}] {task}: {reason}",
                    error=True,
                )
            finally:
                requests_this_run += 1
                save_state(state)
                warning_active = has_partial_completion(state) or bool(
                    state["last_error"]
                )
                status_message = (
                    "일부 API 승인 제한이 있지만 나머지 수집을 계속합니다."
                    if has_partial_completion(state)
                    else (
                        "일시 오류 후 재시도 대기 중입니다."
                        if state["last_error"]
                        else "파일럿 전체 목록 수집이 진행 중입니다."
                    )
                )
                write_warning(
                    state,
                    "WARNING" if warning_active else "RUNNING",
                    status_message,
                )

            delay = args.interval_seconds + random.uniform(0, args.jitter_seconds)
            if state["consecutive_failures"]:
                delay = max(
                    delay,
                    min(300.0, 30.0 * 2 ** min(state["consecutive_failures"], 4)),
                )
            log(f"다음 요청까지 {delay:.1f}초 대기")
            time.sleep(delay)

        state["completed_at"] = utc_now()
        state["pid"] = None
        if has_partial_completion(state):
            state["status"] = "WARNING"
            message = "승인 제한 또는 실패 항목을 제외한 수집이 완료됐습니다."
            exit_code = 2
        else:
            state["status"] = "COMPLETED"
            message = "설정한 파일럿 전체 목록 수집 목표를 완료했습니다."
            exit_code = 0
        save_state(state)
        write_warning(state, state["status"], message)
        log(message, error=exit_code != 0)
        return exit_code
    finally:
        release_lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="파일럿 기준 인벤토리와 핵심 법령 근거를 완료까지 수집합니다."
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=90,
        help="요청 사이 최소 대기 시간(기본 90초)",
    )
    parser.add_argument(
        "--jitter-seconds",
        type=float,
        default=15,
        help="요청 간격에 더할 무작위 대기 상한(기본 15초)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        help="시험 실행용 최대 요청 수",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="API를 호출하지 않고 체크포인트와 프로세스 상태만 확인",
    )
    return parser.parse_args()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        return run(args)
    except CollectionError as error:
        try:
            state = load_state()
            state["status"] = "WARNING"
            state["pid"] = None
            state["last_error"] = str(error)
            save_state(state)
            write_warning(state, "WARNING", "수집기를 시작하거나 계속할 수 없습니다.")
        except Exception:
            pass
        print(f"오류: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        state = load_state()
        state["status"] = "PAUSED"
        state["pid"] = None
        state["last_error"] = "사용자 중단"
        save_state(state)
        write_warning(state, "PAUSED", "사용자가 수집기를 중단했습니다.")
        print("사용자 중단", file=sys.stderr)
        return 130
    except Exception as error:
        try:
            state = load_state()
            state["status"] = "WARNING"
            state["pid"] = None
            state["last_error"] = f"{type(error).__name__}: {error}"
            save_state(state)
            write_warning(state, "WARNING", "예상하지 못한 오류로 수집기가 중단됐습니다.")
        finally:
            print(f"예상하지 못한 오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
