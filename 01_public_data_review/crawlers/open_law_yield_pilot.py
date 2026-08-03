from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _common import (
    CollectionError,
    PROJECT_DIR,
    REPOSITORY_DIR,
    fetch_json,
    load_project_env,
    require_env,
    save_snapshot,
)


SEARCH_ENDPOINT = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_ENDPOINT = "https://www.law.go.kr/DRF/lawService.do"
DATA_DIR = REPOSITORY_DIR / "data" / "01_public_data_review"
STATE_PATH = DATA_DIR / "state" / "open_law_yield_pilot.json"
LOG_PATH = DATA_DIR / "state" / "open_law_yield_pilot.log"
INDEX_PATH = DATA_DIR / "interim" / "open_law_yield_index.jsonl"
REPORT_PATH = DATA_DIR / "reports" / "open_law_yield_pilot.md"
WARNING_PATH = PROJECT_DIR / "WARNING.md"

KEYWORDS = (
    "데이터",
    "이용",
    "공공데이터",
    "개인정보",
    "저작권",
    "제3자 제공",
    "상업적 이용",
    "재배포",
    "국외 이전",
    "인공지능 학습",
)

SOURCES: dict[str, dict[str, Any]] = {
    "law": {
        "label": "현행 법령",
        "id_tags": ("법령일련번호",),
        "title_tags": ("법령명한글", "법령명_한글"),
        "detail_parameter": "MST",
    },
    "admrul": {
        "label": "현행 행정규칙",
        "id_tags": ("행정규칙일련번호",),
        "title_tags": ("행정규칙명",),
        "detail_parameter": "ID",
    },
    "prec": {
        "label": "판례",
        "id_tags": ("판례일련번호",),
        "title_tags": ("사건명",),
        "detail_parameter": "ID",
    },
    "detc": {
        "label": "헌재결정례",
        "id_tags": ("헌재결정례일련번호",),
        "title_tags": ("사건명",),
        "detail_parameter": "ID",
    },
    "expc": {
        "label": "법령해석례",
        "id_tags": ("법령해석례일련번호",),
        "title_tags": ("안건명",),
        "detail_parameter": "ID",
    },
    "decc": {
        "label": "행정심판례",
        "id_tags": ("행정심판재결례일련번호", "행정심판례일련번호"),
        "title_tags": ("사건명",),
        "detail_parameter": "ID",
    },
    "ppc": {
        "label": "개인정보보호위원회 결정문",
        "id_tags": ("결정문일련번호",),
        "title_tags": ("안건명", "민원표시"),
        "detail_parameter": "ID",
    },
    "moisCgmExpc": {
        "label": "행정안전부 법령해석",
        "id_tags": ("법령해석일련번호",),
        "title_tags": ("안건명",),
        "detail_parameter": "ID",
    },
    "mcstCgmExpc": {
        "label": "문화체육관광부 법령해석",
        "id_tags": ("법령해석일련번호",),
        "title_tags": ("안건명",),
        "detail_parameter": "ID",
    },
}

AI_SOURCES: dict[str, dict[str, Any]] = {
    "aiSearch": {
        "label": "지능형 법령검색",
        "variants": {
            0: {
                "label": "법령 조문",
                "rows_key": "법령조문",
                "stable_fields": ("조문일련번호", "법령ID", "조문번호", "조문가지번호"),
                "title_fields": ("법령명", "조문제목"),
            },
            2: {
                "label": "행정규칙 조문",
                "rows_key": "행정규칙조문",
                "stable_fields": (
                    "조문일련번호",
                    "행정규칙ID",
                    "조문번호",
                    "조문가지번호",
                ),
                "title_fields": ("행정규칙명", "조문제목"),
            },
        },
    },
    "aiRltLs": {
        "label": "지능형 연관법령",
        "variants": {
            0: {
                "label": "법령 조문",
                "rows_key": "법령조문",
                "stable_fields": ("법령ID", "조문번호", "조문가지번호"),
                "title_fields": ("법령명", "조문제목"),
            },
            1: {
                "label": "행정규칙 조문",
                "rows_key": "행정규칙조문",
                "stable_fields": ("행정규칙ID", "조문번호", "조문가지번호"),
                "title_fields": ("행정규칙명", "조문제목"),
            },
        },
    },
}

HIGH_SIGNAL_TERMS = (
    "개인정보",
    "저작권",
    "제3자",
    "상업적",
    "재배포",
    "재이용",
    "국외",
    "인공지능",
    "기계학습",
    "목적 외",
    "제공받은",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_state() -> dict[str, Any]:
    return {
        "version": 1,
        "status": "READY",
        "pid": None,
        "started_at": None,
        "deadline_at": None,
        "heartbeat_at": None,
        "finished_at": None,
        "next_action": "search",
        "requests": 0,
        "successes": 0,
        "failures": 0,
        "last_error": None,
        "search_done": {source: [] for source in SOURCES},
        "search_failures": {source: {} for source in SOURCES},
        "search_totals": {source: {} for source in SOURCES},
        "candidates": {source: [] for source in SOURCES},
        "details_done": {source: [] for source in SOURCES},
        "detail_failures": {source: {} for source in SOURCES},
        "ai_search_done": {source: [] for source in AI_SOURCES},
        "ai_search_failures": {source: {} for source in AI_SOURCES},
        "ai_search_totals": {source: {} for source in AI_SOURCES},
        "ai_candidates": {source: [] for source in AI_SOURCES},
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
    for key in (
        "search_done",
        "search_failures",
        "search_totals",
        "candidates",
        "details_done",
        "detail_failures",
    ):
        for source, value in defaults[key].items():
            state[key].setdefault(source, value)
    for key in (
        "ai_search_done",
        "ai_search_failures",
        "ai_search_totals",
        "ai_candidates",
    ):
        for source, value in defaults[key].items():
            state[key].setdefault(source, value)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["heartbeat_at"] = utc_now().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def log(message: str, *, error: bool = False) -> None:
    line = f"{utc_now().isoformat()} {message}"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(line + "\n")
    print(line, file=sys.stderr if error else sys.stdout, flush=True)


def strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element: ET.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part.strip())


def fetch_xml(
    endpoint: str,
    *,
    params: dict[str, str | int],
    timeout: float = 40,
    attempts: int = 3,
) -> tuple[bytes, ET.Element]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{endpoint}?{query}",
        headers={
            "Accept": "application/xml,text/xml",
            "User-Agent": "data-collect-research/0.2",
        },
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
            try:
                return raw, ET.fromstring(raw)
            except ET.ParseError as error:
                raise CollectionError("API 응답을 XML로 해석할 수 없습니다.") from error
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == attempts:
                raise CollectionError(f"API가 HTTP {error.code} 오류를 반환했습니다.") from None
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts:
                reason = getattr(error, "reason", "network error")
                raise CollectionError(f"API 연결에 실패했습니다: {reason}") from None
        time.sleep(1.0 * attempt)
    raise CollectionError("API 호출에 실패했습니다.")


def child_values(element: ET.Element) -> dict[str, str]:
    return {
        strip_namespace(child.tag): element_text(child)
        for child in element
        if element_text(child)
    }


def find_first(root: ET.Element, names: tuple[str, ...]) -> str:
    for element in root.iter():
        if strip_namespace(element.tag) in names:
            value = element_text(element)
            if value:
                return value
    return ""


def extract_candidates(root: ET.Element, source: str) -> list[dict[str, Any]]:
    config = SOURCES[source]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in root.iter():
        values = child_values(element)
        identifier = next(
            (values.get(tag, "").strip() for tag in config["id_tags"] if values.get(tag)),
            "",
        )
        if not identifier or identifier in seen:
            continue
        title = next(
            (values.get(tag, "").strip() for tag in config["title_tags"] if values.get(tag)),
            "",
        )
        seen.add(identifier)
        rows.append(
            {
                "id": identifier,
                "title": title,
                "metadata": values,
                "keywords": [],
            }
        )
    return rows


def candidate_map(state: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in state["candidates"][source]}


def ai_task_key(keyword: str, variant: int) -> str:
    return f"{keyword}|{variant}"


def next_search_task(
    state: dict[str, Any],
) -> tuple[str, str, str, int | None] | None:
    for keyword in KEYWORDS:
        for source in SOURCES:
            if keyword not in state["search_done"][source]:
                return "document", source, keyword, None
        for source, config in AI_SOURCES.items():
            for variant in config["variants"]:
                if ai_task_key(keyword, variant) not in state["ai_search_done"][source]:
                    return "ai", source, keyword, variant
    return None


def details_available(state: dict[str, Any], source: str) -> list[dict[str, Any]]:
    completed = set(map(str, state["details_done"][source]))
    failures = state["detail_failures"][source]
    return [
        item
        for item in state["candidates"][source]
        if str(item["id"]) not in completed
        and int(failures.get(str(item["id"]), 0)) < 2
    ]


def next_detail_task(
    state: dict[str, Any],
    *,
    preferred_per_source: int,
    total_detail_budget: int,
) -> tuple[str, dict[str, Any]] | None:
    completed_total = sum(len(items) for items in state["details_done"].values())
    if completed_total >= total_detail_budget:
        return None

    available = {
        source: details_available(state, source)
        for source in SOURCES
    }
    eligible = [
        source
        for source in SOURCES
        if available[source]
        and len(state["details_done"][source]) < preferred_per_source
    ]
    if not eligible:
        eligible = [source for source in SOURCES if available[source]]
    if not eligible:
        return None

    source = min(
        eligible,
        key=lambda item: (
            len(state["details_done"][item]),
            list(SOURCES).index(item),
        ),
    )
    return source, available[source][0]


def collect_search(
    state: dict[str, Any],
    *,
    oc: str,
    source: str,
    keyword: str,
    display: int,
    per_keyword: int,
    candidate_target: int,
) -> str:
    params: dict[str, str | int] = {
        "OC": oc,
        "target": source,
        "type": "XML",
        "search": 2,
        "query": keyword,
        "display": display,
        "page": 1,
    }
    raw, root = fetch_xml(SEARCH_ENDPOINT, params=params)
    output_path, _ = save_snapshot(
        raw,
        source="국가법령정보 공동활용",
        collection=f"open_law_yield_search_{source}",
        endpoint=SEARCH_ENDPOINT,
        public_request={key: value for key, value in params.items() if key != "OC"},
        suffix=".xml",
    )

    total_text = find_first(root, ("totalCnt", "totalCnts"))
    try:
        total = int(total_text.replace(",", "")) if total_text else 0
    except ValueError:
        total = 0
    state["search_totals"][source][keyword] = total

    existing = candidate_map(state, source)
    added = 0
    for item in extract_candidates(root, source):
        identifier = str(item["id"])
        if identifier in existing:
            if keyword not in existing[identifier]["keywords"]:
                existing[identifier]["keywords"].append(keyword)
            continue
        if added >= per_keyword or len(existing) >= candidate_target:
            continue
        item["keywords"].append(keyword)
        state["candidates"][source].append(item)
        existing[identifier] = item
        added += 1

    state["search_done"][source].append(keyword)
    return (
        f"[검색] {SOURCES[source]['label']} / {keyword}: "
        f"전체 {total}건, 후보 +{added}건, {output_path.name}"
    )


def nested_dict(payload: Any, key: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        for child in payload.values():
            found = nested_dict(child, key)
            if found:
                return found
    return {}


def collect_ai_search(
    state: dict[str, Any],
    *,
    oc: str,
    source: str,
    keyword: str,
    variant: int,
    display: int,
    per_keyword: int,
    candidate_target: int,
) -> str:
    config = AI_SOURCES[source]
    variant_config = config["variants"][variant]
    params: dict[str, str | int] = {
        "OC": oc,
        "target": source,
        "type": "JSON",
        "search": variant,
        "query": keyword,
    }
    if source == "aiSearch":
        params.update({"display": display, "page": 1})
    raw, payload = fetch_json(SEARCH_ENDPOINT, params=params, timeout=40)
    output_path, manifest = save_snapshot(
        raw,
        source="국가법령정보 공동활용",
        collection=f"open_law_yield_search_{source}",
        endpoint=SEARCH_ENDPOINT,
        public_request={key: value for key, value in params.items() if key != "OC"},
    )

    root_key = "aiSearch" if source == "aiSearch" else "aiRltLsSearch"
    response = nested_dict(payload, root_key)
    total_text = str(response.get("검색결과개수", "0")).replace(",", "")
    try:
        total = int(total_text)
    except ValueError:
        total = 0
    task_key = ai_task_key(keyword, variant)
    state["ai_search_totals"][source][task_key] = total

    rows = response.get(variant_config["rows_key"], [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        rows = []
    existing = {str(item["id"]): item for item in state["ai_candidates"][source]}
    added = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        stable_parts = [
            str(row.get(field, "")).strip()
            for field in variant_config["stable_fields"]
            if str(row.get(field, "")).strip()
        ]
        if not stable_parts:
            continue
        identifier = f"{variant}:" + ":".join(stable_parts)
        title = " / ".join(
            str(row.get(field, "")).strip()
            for field in variant_config["title_fields"]
            if str(row.get(field, "")).strip()
        )
        if identifier in existing:
            if keyword not in existing[identifier]["keywords"]:
                existing[identifier]["keywords"].append(keyword)
            continue
        if added >= per_keyword or len(existing) >= candidate_target:
            continue
        text = " ".join(str(value) for value in row.values() if value is not None)
        matched_terms = [term for term in HIGH_SIGNAL_TERMS if term in text]
        item = {
            "id": identifier,
            "title": title,
            "variant": variant,
            "variant_label": variant_config["label"],
            "metadata": row,
            "keywords": [keyword],
        }
        state["ai_candidates"][source].append(item)
        existing[identifier] = item
        append_index(
            {
                "source": source,
                "source_label": config["label"],
                "record_kind": (
                    "intelligent_search_result"
                    if source == "aiSearch"
                    else "related_law_result"
                ),
                "id": identifier,
                "title": title,
                "search_keywords": [keyword],
                "matched_high_signal_terms": matched_terms,
                "text_chars": len(text),
                "file": manifest["file"],
                "sha256": manifest["sha256"],
                "collected_at": manifest["collected_at"],
            }
        )
        added += 1
    state["ai_search_done"][source].append(task_key)
    return (
        f"[지능형] {config['label']} {variant_config['label']} / {keyword}: "
        f"전체 {total}건, 후보 +{added}건, {output_path.name}"
    )


def append_index(record: dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def collect_detail(
    state: dict[str, Any],
    *,
    oc: str,
    source: str,
    candidate: dict[str, Any],
) -> str:
    identifier = str(candidate["id"])
    detail_parameter = SOURCES[source]["detail_parameter"]
    params: dict[str, str | int] = {
        "OC": oc,
        "target": source,
        "type": "XML",
        detail_parameter: identifier,
    }
    raw, root = fetch_xml(DETAIL_ENDPOINT, params=params)
    text = element_text(root)
    if len(text) < 20:
        raise CollectionError("본문 응답이 비어 있거나 너무 짧습니다.")
    output_path, manifest = save_snapshot(
        raw,
        source="국가법령정보 공동활용",
        collection=f"open_law_yield_detail_{source}",
        endpoint=DETAIL_ENDPOINT,
        public_request={key: value for key, value in params.items() if key != "OC"},
        suffix=".xml",
    )
    matched_terms = [term for term in HIGH_SIGNAL_TERMS if term in text]
    append_index(
        {
            "source": source,
            "source_label": SOURCES[source]["label"],
            "id": identifier,
            "title": candidate.get("title", ""),
            "search_keywords": candidate.get("keywords", []),
            "matched_high_signal_terms": matched_terms,
            "text_chars": len(text),
            "file": manifest["file"],
            "sha256": manifest["sha256"],
            "collected_at": manifest["collected_at"],
        }
    )
    state["details_done"][source].append(identifier)
    return (
        f"[본문] {SOURCES[source]['label']} ID={identifier}: "
        f"{len(text):,}자, 신호 {len(matched_terms)}개, {output_path.name}"
    )


def read_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        unique[(str(record.get("source")), str(record.get("id")))] = record
    return list(unique.values())


def write_report(state: dict[str, Any]) -> None:
    records = read_index()
    by_source: dict[str, list[dict[str, Any]]] = {
        source: [] for source in (*SOURCES, *AI_SOURCES)
    }
    for record in records:
        source = str(record.get("source"))
        if source in by_source:
            by_source[source].append(record)

    lines = [
        "# Open Law 키워드 수율 탐색",
        "",
        f"- 상태: **{state['status']}**",
        f"- 시작: `{state.get('started_at') or '-'}`",
        f"- 마지막 heartbeat: `{state.get('heartbeat_at') or '-'}`",
        f"- 요청 성공/실패: {state['successes']}/{state['failures']}",
        f"- 키워드: {', '.join(KEYWORDS)}",
        "",
        "## 원천별 결과",
        "",
        "| 원천 | 검색 완료 | 검색 후보 | 본문 | 고신호 본문 | 본문 글자수 중앙값 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source, config in SOURCES.items():
        source_records = by_source[source]
        high_signal = sum(
            1
            for record in source_records
            if len(record.get("matched_high_signal_terms", [])) >= 2
        )
        lengths = [
            int(record.get("text_chars", 0))
            for record in source_records
            if int(record.get("text_chars", 0)) > 0
        ]
        median = int(statistics.median(lengths)) if lengths else 0
        lines.append(
            f"| {config['label']} (`{source}`) | "
            f"{len(state['search_done'][source])}/{len(KEYWORDS)} | "
            f"{len(state['candidates'][source])} | "
            f"{len(state['details_done'][source])} | "
            f"{high_signal} | {median:,} |"
        )

    lines.extend(
        [
            "",
            "## 지능형 검색·연관법령 결과",
            "",
            "| 원천 | 검색 완료 | 고유 결과 | 고신호 결과 |",
            "|---|---:|---:|---:|",
        ]
    )
    ai_task_count = len(KEYWORDS) * 2
    for source, config in AI_SOURCES.items():
        source_records = by_source[source]
        high_signal = sum(
            1
            for record in source_records
            if len(record.get("matched_high_signal_terms", [])) >= 2
        )
        lines.append(
            f"| {config['label']} (`{source}`) | "
            f"{len(state['ai_search_done'][source])}/{ai_task_count} | "
            f"{len(state['ai_candidates'][source])} | {high_signal} |"
        )

    lines.extend(["", "## 키워드별 검색 결과 수", ""])
    for source, config in SOURCES.items():
        totals = state["search_totals"][source]
        rendered = ", ".join(f"{keyword}={totals.get(keyword, '-')}" for keyword in KEYWORDS)
        lines.append(f"- {config['label']}: {rendered}")
    for source, config in AI_SOURCES.items():
        totals = state["ai_search_totals"][source]
        rendered_parts = []
        for variant, variant_config in config["variants"].items():
            values = ", ".join(
                f"{keyword}={totals.get(ai_task_key(keyword, variant), '-')}"
                for keyword in KEYWORDS
            )
            rendered_parts.append(f"{variant_config['label']}({values})")
        lines.append(f"- {config['label']}: {'; '.join(rendered_parts)}")

    term_counts: Counter[str] = Counter()
    for record in records:
        term_counts.update(record.get("matched_high_signal_terms", []))
    lines.extend(
        [
            "",
            "## 판정 참고",
            "",
            "- `고신호 본문`은 고위험 관련어가 2개 이상 나타난 문서의 수다. 최종 관련성 판정이 아니라 원천 비교용 휴리스틱이다.",
            "- 본문 수와 신호 밀도, 구조화된 사실관계·판단·조치의 존재를 함께 보고 후속 본수집 원천을 정한다.",
            f"- 전체 고위험 관련어 출현: {dict(term_counts)}",
            "",
        ]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_warning(state: dict[str, Any]) -> None:
    status = state["status"]
    if status == "RUNNING":
        headline = "**RUNNING** — Open Law 키워드 수율 탐색 수집기가 실행 중입니다."
    elif status == "COMPLETED":
        headline = "**COMPLETED** — 20시간 탐색 수집이 정상 종료되었습니다."
    else:
        headline = f"**WARNING** — 탐색 수집 상태가 `{status}`입니다."
    progress = []
    for source, config in SOURCES.items():
        progress.append(
            f"- {config['label']}: 검색 {len(state['search_done'][source])}/"
            f"{len(KEYWORDS)}, 후보 {len(state['candidates'][source])}, "
            f"본문 {len(state['details_done'][source])}"
        )
    for source, config in AI_SOURCES.items():
        progress.append(
            f"- {config['label']}: 검색 {len(state['ai_search_done'][source])}/"
            f"{len(KEYWORDS) * 2}, 고유 결과 {len(state['ai_candidates'][source])}"
        )
    content = "\n".join(
        [
            "# 수집 상태",
            "",
            headline,
            "",
            f"- 시작: `{state.get('started_at') or '-'}`",
            f"- 종료 예정: `{state.get('deadline_at') or '-'}`",
            f"- 마지막 heartbeat: `{state.get('heartbeat_at') or '-'}`",
            f"- PID: `{state.get('pid') or '-'}`",
            f"- 요청 성공/실패: `{state['successes']}/{state['failures']}`",
            f"- 마지막 오류: `{state.get('last_error') or '-'}`",
            "",
            "## 진행률",
            "",
            *progress,
            "",
            "## 확인 위치",
            "",
            "- 상태: `data/01_public_data_review/state/open_law_yield_pilot.json`",
            "- 로그: `data/01_public_data_review/state/open_law_yield_pilot.log`",
            "- 중간 보고서: `data/01_public_data_review/reports/open_law_yield_pilot.md`",
            "- 명령: `python .\\01_public_data_review\\crawlers\\open_law_yield_pilot.py --status`",
            "",
            "heartbeat가 5분 이상 갱신되지 않으면 프로세스가 중단됐을 수 있습니다.",
            "",
        ]
    )
    WARNING_PATH.write_text(content, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Law 원천별 키워드 검색 수율과 본문 활용도를 균형 표본으로 탐색합니다."
    )
    parser.add_argument("--duration-hours", type=float, default=20)
    parser.add_argument("--interval-seconds", type=float, default=90)
    parser.add_argument("--jitter-seconds", type=float, default=15)
    parser.add_argument("--display", type=int, default=100)
    parser.add_argument("--per-keyword", type=int, default=10)
    parser.add_argument("--candidate-target", type=int, default=100)
    parser.add_argument("--preferred-details-per-source", type=int, default=65)
    parser.add_argument("--total-detail-budget", type=int, default=590)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reset-window",
        action="store_true",
        help="기존 표본은 유지하고 실행 시작·종료 시각만 지금부터 다시 계산",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.duration_hours <= 0:
        raise CollectionError("--duration-hours는 0보다 커야 합니다.")
    if args.interval_seconds < 10:
        raise CollectionError("--interval-seconds는 10 이상이어야 합니다.")
    if args.jitter_seconds < 0:
        raise CollectionError("--jitter-seconds는 0 이상이어야 합니다.")
    if not 1 <= args.display <= 100:
        raise CollectionError("--display는 1~100이어야 합니다.")
    if not 1 <= args.per_keyword <= args.display:
        raise CollectionError("--per-keyword는 1 이상 display 이하여야 합니다.")
    if args.candidate_target < 1:
        raise CollectionError("--candidate-target은 1 이상이어야 합니다.")
    if args.preferred_details_per_source < 1 or args.total_detail_budget < 1:
        raise CollectionError("본문 목표는 1 이상이어야 합니다.")
    if args.max_requests is not None and args.max_requests < 1:
        raise CollectionError("--max-requests는 1 이상이어야 합니다.")


def status_text(state: dict[str, Any]) -> str:
    lines = [
        f"상태: {state['status']}",
        f"PID: {state.get('pid') or '-'}",
        f"heartbeat: {state.get('heartbeat_at') or '-'}",
        f"성공/실패: {state['successes']}/{state['failures']}",
    ]
    for source, config in SOURCES.items():
        lines.append(
            f"{config['label']}: 검색 {len(state['search_done'][source])}/"
            f"{len(KEYWORDS)}, 후보 {len(state['candidates'][source])}, "
            f"본문 {len(state['details_done'][source])}"
        )
    for source, config in AI_SOURCES.items():
        lines.append(
            f"{config['label']}: 검색 {len(state['ai_search_done'][source])}/"
            f"{len(KEYWORDS) * 2}, 고유 결과 {len(state['ai_candidates'][source])}"
        )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    validate_args(args)
    state_path = args.state_path.resolve()
    state = load_state(state_path)
    if args.status or args.dry_run:
        print(status_text(state))
        return 0

    load_project_env()
    oc = require_env("LAW_OPEN_API_OC")
    now = utc_now()
    if args.reset_window or not state.get("started_at"):
        state["started_at"] = now.isoformat()
        state["deadline_at"] = (now + timedelta(hours=args.duration_hours)).isoformat()
        state["finished_at"] = None
    deadline = datetime.fromisoformat(state["deadline_at"])
    if deadline <= now:
        state["status"] = "COMPLETED"
        state["finished_at"] = now.isoformat()
        save_state(state_path, state)
        write_report(state)
        write_warning(state)
        return 0

    import os

    state["status"] = "RUNNING"
    state["pid"] = os.getpid()
    state["last_error"] = None
    save_state(state_path, state)
    write_report(state)
    write_warning(state)
    log(
        f"탐색 수집 시작: 문서 9개·지능형 2개 원천 × 10개 키워드, "
        f"후보 최대 {args.candidate_target}건/원천, "
        f"본문 우선 {args.preferred_details_per_source}건/원천"
    )

    requests_this_run = 0
    try:
        while utc_now() < deadline:
            if args.max_requests is not None and requests_this_run >= args.max_requests:
                break

            search_task = next_search_task(state)
            detail_task = next_detail_task(
                state,
                preferred_per_source=args.preferred_details_per_source,
                total_detail_budget=args.total_detail_budget,
            )
            action = state["next_action"]
            if action == "search" and search_task is None:
                action = "detail"
            elif action == "detail" and detail_task is None:
                action = "search"

            if action == "search" and search_task is not None:
                search_kind, source, keyword, variant = search_task
                if search_kind == "document":
                    task_label = f"검색 {source}/{keyword}"
                    operation = lambda: collect_search(
                        state,
                        oc=oc,
                        source=source,
                        keyword=keyword,
                        display=args.display,
                        per_keyword=args.per_keyword,
                        candidate_target=args.candidate_target,
                    )
                else:
                    assert variant is not None
                    task_label = f"지능형 검색 {source}/{variant}/{keyword}"
                    operation = lambda: collect_ai_search(
                        state,
                        oc=oc,
                        source=source,
                        keyword=keyword,
                        variant=variant,
                        display=args.display,
                        per_keyword=args.per_keyword,
                        candidate_target=args.candidate_target,
                    )
                state["next_action"] = "detail"
            elif action == "detail" and detail_task is not None:
                source, candidate = detail_task
                identifier = str(candidate["id"])
                task_label = f"본문 {source}/{identifier}"
                operation = lambda: collect_detail(
                    state,
                    oc=oc,
                    source=source,
                    candidate=candidate,
                )
                state["next_action"] = "search"
            else:
                state["status"] = "COMPLETED"
                break

            try:
                message = operation()
                state["successes"] += 1
                state["last_error"] = None
                log(message)
            except CollectionError as error:
                state["failures"] += 1
                state["last_error"] = f"{task_label}: {error}"
                if action == "search" and search_task is not None:
                    search_kind, source, keyword, variant = search_task
                    if search_kind == "document":
                        failures = state["search_failures"][source]
                        failures[keyword] = int(failures.get(keyword, 0)) + 1
                        if (
                            failures[keyword] >= 2
                            and keyword not in state["search_done"][source]
                        ):
                            state["search_done"][source].append(keyword)
                    else:
                        assert variant is not None
                        task_key = ai_task_key(keyword, variant)
                        failures = state["ai_search_failures"][source]
                        failures[task_key] = int(failures.get(task_key, 0)) + 1
                        if (
                            failures[task_key] >= 2
                            and task_key not in state["ai_search_done"][source]
                        ):
                            state["ai_search_done"][source].append(task_key)
                elif action == "detail" and detail_task is not None:
                    source, candidate = detail_task
                    identifier = str(candidate["id"])
                    failures = state["detail_failures"][source]
                    failures[identifier] = int(failures.get(identifier, 0)) + 1
                log(f"[실패] {state['last_error']}", error=True)
            finally:
                state["requests"] += 1
                requests_this_run += 1
                save_state(state_path, state)
                write_report(state)
                write_warning(state)

            if args.max_requests is not None and requests_this_run >= args.max_requests:
                break
            delay = args.interval_seconds + random.uniform(0, args.jitter_seconds)
            if utc_now() + timedelta(seconds=delay) >= deadline:
                break
            time.sleep(delay)
    except KeyboardInterrupt:
        state["status"] = "STOPPED"
        state["last_error"] = "사용자가 수집을 중단했습니다."
        raise
    except Exception as error:
        state["status"] = "ERROR"
        state["last_error"] = f"{type(error).__name__}: {error}"
        log(f"[치명적 오류] {state['last_error']}", error=True)
        raise
    finally:
        if state["status"] == "RUNNING":
            if utc_now() >= deadline:
                state["status"] = "COMPLETED"
            elif args.max_requests is not None:
                state["status"] = "PAUSED"
            else:
                state["status"] = "STOPPED"
        if state["status"] in {"COMPLETED", "STOPPED", "ERROR"}:
            state["finished_at"] = utc_now().isoformat()
        state["pid"] = None
        save_state(state_path, state)
        write_report(state)
        write_warning(state)
        log(
            f"탐색 수집 종료: 상태={state['status']}, "
            f"이번 실행 요청={requests_this_run}, 누적 성공/실패="
            f"{state['successes']}/{state['failures']}"
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
        print("사용자 중단", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
