"""Shared Solar client: settings, one HTTP call, and the small helpers around it.

Solar Open is served over an OpenAI-compatible endpoint, so a request is just a
POST of `{model, messages, ...}` to `<base>/chat/completions`. Everything that
does not depend on *which* prompt is being sent lives here, and every caller --
the interpretation and mutation roles under `training_data/`, and the frozen
experiments under `probes/` -- imports it rather than carrying its own copy.

Generation parameters come from two places on purpose. Environment variables
hold what may differ per machine (endpoint, key, model, timeout); the tracked
`solar_request.json` holds what must not drift between runs (temperature,
top_p, max_tokens, reasoning_effort), so a result can be reproduced from the
file alone. `solar_request.json` wins where both set the same key.

Secrets are read from the repository-root `.env`, which is never committed;
`solar.config.example.env` lists the variable names without values.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_DIR = Path(__file__).resolve().parent
SOLAR_REQUEST_PATH = REPOSITORY_DIR / "solar_request.json"
ENV_PATH = REPOSITORY_DIR / ".env"


class SolarAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


# ------------------------------------------------------------------- settings

def load_env(path: Path = ENV_PATH) -> None:
    """Read KEY=VALUE lines into the environment, without overwriting.

    `setdefault` rather than assignment: a variable already exported in the
    shell is the more specific instruction and must win over the file.
    """
    if not path.exists():
        return
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key:
            raise ValueError(f"{path}:{line_number}: empty variable name")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def load_request_options() -> dict[str, Any]:
    """Generation parameters pinned in `solar_request.json`.

    `model` and `messages` are rejected: those are the call itself, not a
    parameter of it, and letting the file set them would make a run's prompt
    invisible in the code that issued it.
    """
    options = json.loads(SOLAR_REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(options, dict):
        raise ValueError(f"{SOLAR_REQUEST_PATH} must contain a JSON object")
    conflicts = sorted({"model", "messages"}.intersection(options))
    if conflicts:
        raise ValueError(f"Cannot override reserved keys: {', '.join(conflicts)}")
    return options


# ----------------------------------------------------------------------- call

def chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def request_payload(prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": require_env("SOLAR_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(os.environ.get("SOLAR_TEMPERATURE", "0.7")),
        "top_p": float(os.environ.get("SOLAR_TOP_P", "1.0")),
        "max_tokens": int(os.environ.get("SOLAR_MAX_TOKENS", "4096")),
    }
    seed = os.environ.get("SOLAR_SEED", "").strip()
    if seed:
        payload["seed"] = int(seed)
    payload.update(load_request_options())
    return payload


def call_solar(
    url: str, api_key: str, payload: dict[str, Any], timeout_seconds: int
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_response = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw_error = error.read().decode("utf-8", errors="replace")
        try:
            parsed_error = json.loads(raw_error)
        except json.JSONDecodeError:
            parsed_error = {}
        detail = parsed_error.get("error", parsed_error)
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail")
        else:
            message = None
        raise SolarAPIError(error.code, message or f"HTTP {error.code}") from None
    result = json.loads(raw_response)
    if not isinstance(result, dict):
        raise ValueError("Solar response must be a JSON object")
    return result


def extract_message(response: dict[str, Any]) -> tuple[str, str | None]:
    """The assistant's text, and its reasoning trace when the model returned one."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Solar response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Solar response has no assistant message")
    content = message.get("content", "")
    # A reasoning model does not always put its answer in a plain string. Two shapes turn
    # up: `null`, when the reply went entirely into the reasoning trace, and a list of
    # content blocks. Both used to raise, losing the call -- one of 60 in the 2026-08-12
    # role B run. Coerce those two and keep the raise for anything genuinely unexpected.
    if content is None:
        content = ""
    elif isinstance(content, list):
        content = "".join(
            block.get("text", "") for block in content if isinstance(block, dict))
    if not isinstance(content, str):
        raise ValueError("Solar assistant content is not a string")
    reasoning = message.get("reasoning")
    return content, None if reasoning is None else str(reasoning)


# ---------------------------------------------------------------------- files

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def read_json(path: Path) -> Any:
    # utf-8-sig: a file saved by a Windows editor may start with a byte order
    # mark, which plain utf-8 would hand to the JSON parser as a stray char.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def safe_error(error: Exception) -> dict[str, Any]:
    """An exception reduced to what a manifest may record.

    The exception object itself is not written out: it can hold the request,
    and the request holds the API key.
    """
    result: dict[str, Any] = {"type": type(error).__name__, "message": str(error)}
    if isinstance(error, SolarAPIError):
        result["status_code"] = error.status_code
    return result


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
