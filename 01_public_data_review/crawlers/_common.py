from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_DIR = PROJECT_DIR.parent
ENV_PATH = PROJECT_DIR / ".env"
MANIFEST_PATH = PROJECT_DIR / "manifests" / "01_public_data_review.jsonl"
RAW_DIR = REPOSITORY_DIR / "data" / "01_public_data_review" / "raw"


class CollectionError(RuntimeError):
    """Raised when a source cannot be collected safely."""


def load_project_env(path: Path = ENV_PATH) -> None:
    """Load simple KEY=VALUE entries without overwriting process variables."""
    if not path.exists():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise CollectionError(f"{path.name} {line_number}행의 형식이 잘못되었습니다.")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CollectionError(
            f"{name}이 설정되지 않았습니다. "
            f"{PROJECT_DIR / 'config.example.env'}를 참고해 "
            f"{ENV_PATH} 파일을 만드세요."
        )
    return value


def _decode_json(raw: bytes, content_type: str | None) -> Any:
    # Some official endpoints label UTF-8 JSON with a legacy charset.
    # Try UTF-8 first, then fall back to the declared charset and EUC-KR.
    charsets: list[str] = ["utf-8-sig"]
    if content_type:
        for part in content_type.split(";")[1:]:
            name, separator, value = part.strip().partition("=")
            if separator and name.lower() == "charset":
                charsets.append(value.strip("\"' "))
    charsets.append("euc-kr")

    last_error: Exception | None = None
    for charset in dict.fromkeys(charsets):
        try:
            return json.loads(raw.decode(charset))
        except (LookupError, UnicodeDecodeError, json.JSONDecodeError) as error:
            last_error = error

    raise CollectionError("응답을 JSON으로 해석할 수 없습니다.") from last_error


def fetch_json(
    endpoint: str,
    *,
    params: dict[str, str | int],
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    attempts: int = 3,
) -> tuple[bytes, Any]:
    """Fetch JSON without exposing query parameters in raised errors."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{endpoint}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "data-collect-research/0.1",
            **(headers or {}),
        },
    )

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                payload = _decode_json(raw, response.headers.get("Content-Type"))
                return raw, payload
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == attempts:
                raise CollectionError(
                    f"API가 HTTP {error.code} 오류를 반환했습니다."
                ) from None
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts:
                reason = getattr(error, "reason", "network error")
                raise CollectionError(f"API 연결에 실패했습니다: {reason}") from None

        time.sleep(0.5 * attempt)

    raise CollectionError("API 호출에 실패했습니다.")


def save_snapshot(
    raw: bytes,
    *,
    source: str,
    collection: str,
    endpoint: str,
    public_request: dict[str, str | int],
    suffix: str = ".json",
) -> tuple[Path, dict[str, Any]]:
    """Save an exact response and append a secret-free provenance record."""
    if not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
        raise CollectionError(f"잘못된 snapshot 확장자입니다: {suffix}")
    collected_at = datetime.now(timezone.utc)
    stamp = collected_at.strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = RAW_DIR / collection
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stamp}{suffix}"
    output_path.write_bytes(raw)

    digest = hashlib.sha256(raw).hexdigest()
    relative_path = output_path.relative_to(REPOSITORY_DIR).as_posix()
    manifest = {
        "source": source,
        "collection": collection,
        "endpoint": endpoint,
        "request": public_request,
        "collected_at": collected_at.isoformat(),
        "file": relative_path,
        "bytes": len(raw),
        "sha256": digest,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        stream.write("\n")

    return output_path, manifest


def nested_value(payload: Any, key: str) -> Any | None:
    """Return the first value matching a key in a nested JSON response."""
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = nested_value(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = nested_value(value, key)
            if found is not None:
                return found
    return None


def redact_payload(payload: Any, secrets: list[str]) -> Any:
    """Return a copy with secret strings removed from nested response values."""
    usable_secrets = [secret for secret in secrets if secret]
    if isinstance(payload, dict):
        return {
            key: redact_payload(value, usable_secrets)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_payload(value, usable_secrets) for value in payload]
    if isinstance(payload, str):
        for secret in usable_secrets:
            payload = payload.replace(secret, "<redacted>")
    return payload


def encode_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
