"""Test the two G2B API credentials without printing or storing secrets."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_DIR / ".env"
TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class ApiProbe:
    name: str
    endpoint: str
    key_name: str


PROBES = (
    ApiProbe(
        name="사전규격정보서비스",
        endpoint=(
            "https://apis.data.go.kr/1230000/ao/"
            "HrcspSsstndrdInfoService/getPublicPrcureThngInfoServc"
        ),
        key_name="G2B_PRIOR_SPEC_SERVICE_KEY",
    ),
    ApiProbe(
        name="입찰공고정보서비스",
        endpoint=(
            "https://apis.data.go.kr/1230000/ad/"
            "BidPublicInfoService/getBidPblancListInfoServc"
        ),
        key_name="G2B_BID_NOTICE_SERVICE_KEY",
    ),
)


def load_env(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE entries without exposing their values."""
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def parse_result(
    payload: bytes, content_type: str
) -> tuple[str, str, int | None, list[str]]:
    text = payload.decode("utf-8-sig", errors="replace")
    if "json" in content_type.lower() or text.lstrip().startswith("{"):
        data = json.loads(text)
        response = _mapping_get(data, "response") or data
        header = _find_named_mapping(response, "header") or {}
        body = _find_named_mapping(response, "body") or {}
        return (
            str(_mapping_get(header, "resultCode") or ""),
            str(_mapping_get(header, "resultMsg") or ""),
            _as_int(_mapping_get(body, "totalCount")),
            _json_key_paths(data),
        )

    root = ET.fromstring(text)
    result_code = root.findtext(".//resultCode", default="")
    result_message = root.findtext(".//resultMsg", default="")
    total_count = _as_int(root.findtext(".//totalCount"))
    return result_code, result_message, total_count, []


def _mapping_get(value: object, key: str) -> object | None:
    if not isinstance(value, dict):
        return None
    wanted = key.casefold()
    for candidate, item in value.items():
        if str(candidate).casefold() == wanted:
            return item
    return None


def _find_named_mapping(value: object, key: str) -> dict[object, object] | None:
    if not isinstance(value, dict):
        return None
    direct = _mapping_get(value, key)
    if isinstance(direct, dict):
        return direct
    for item in value.values():
        found = _find_named_mapping(item, key)
        if found is not None:
            return found
    return None


def _json_key_paths(value: object, prefix: str = "", depth: int = 0) -> list[str]:
    """Return public response field names only, never their values."""
    if depth > 3 or not isinstance(value, dict):
        return []
    paths: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.append(path)
        paths.extend(_json_key_paths(item, path, depth + 1))
    return paths


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def probe_api(probe: ApiProbe, service_key: str) -> bool:
    # 공공데이터포털의 Encoding 키와 Decoding 키를 모두 동일하게 처리한다.
    # 값 자체는 출력하거나 저장하지 않는다.
    normalized_service_key = urllib.parse.unquote(service_key)
    query_end = datetime.now()
    query_start = query_end - timedelta(days=1)
    query = urllib.parse.urlencode(
        {
            "serviceKey": normalized_service_key,
            "pageNo": 1,
            "numOfRows": 1,
            "inqryDiv": 1,
            "inqryBgnDt": query_start.strftime("%Y%m%d%H%M"),
            "inqryEndDt": query_end.strftime("%Y%m%d%H%M"),
            "type": "json",
        }
    )
    request = urllib.request.Request(
        f"{probe.endpoint}?{query}",
        headers={"Accept": "application/json", "User-Agent": "data-collect/connection-test"},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        payload = error.read()
        status = error.code
        content_type = error.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError):
        print(f"[실패] {probe.name}: 네트워크 연결 또는 시간 초과")
        return False

    try:
        result_code, result_message, total_count, key_paths = parse_result(
            payload, content_type
        )
    except (json.JSONDecodeError, ET.ParseError, UnicodeError):
        print(f"[실패] {probe.name}: HTTP {status}, 응답 형식을 해석할 수 없음")
        return False

    success = status == 200 and result_code in {"0", "00", "000"}
    state = "성공" if success else "실패"
    count_text = "확인 불가" if total_count is None else str(total_count)
    print(
        f"[{state}] {probe.name}: HTTP {status}, "
        f"응답코드={result_code or '없음'}, 전체항목={count_text}"
    )
    if result_message:
        print(f"  응답메시지: {result_message}")
    if status == 200 and not result_code and key_paths:
        print(f"  응답 필드(값 제외): {', '.join(key_paths)}")
    return success


def main() -> int:
    if not ENV_PATH.is_file():
        print("[실패] raw_collection/.env 파일이 없습니다.")
        return 2

    env = load_env(ENV_PATH)
    missing = [probe.key_name for probe in PROBES if not env.get(probe.key_name)]
    if missing:
        print(f"[실패] 값이 없는 환경변수: {', '.join(missing)}")
        return 2

    results = [probe_api(probe, env[probe.key_name]) for probe in PROBES]
    print(f"호출량: 사전규격 1건, 입찰공고 1건 (재시도 없음)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
