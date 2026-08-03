from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASE_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = CASE_DIR.parent.parent
PROMPT_PATH = CASE_DIR / "prompt.txt"
EVIDENCE_PATH = CASE_DIR / "data" / "evidence.json"
SOLAR_REQUEST_PATH = REPOSITORY_DIR / "solar_request.json"
ENV_PATH = REPOSITORY_DIR / ".env"
EVIDENCE_PLACEHOLDER = "{{EVIDENCE_PACK}}"


class SolarAPIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        message: str,
        error_type: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code


def load_env(path: Path) -> None:
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

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"{path}:{line_number}: empty environment variable name")

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def parse_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return int(raw_value)


def parse_float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return float(raw_value)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_prompt() -> tuple[str, dict[str, Any], str]:
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    if prompt_template.count(EVIDENCE_PLACEHOLDER) != 1:
        raise ValueError(
            f"{PROMPT_PATH} must contain exactly one {EVIDENCE_PLACEHOLDER} placeholder"
        )

    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    evidence_items = evidence.get("evidence")
    if not isinstance(evidence_items, list) or not evidence_items:
        raise ValueError(f"{EVIDENCE_PATH} must contain a non-empty evidence list")

    evidence_ids = [item.get("evidence_id") for item in evidence_items]
    if any(not evidence_id for evidence_id in evidence_ids):
        raise ValueError("Every evidence item must have an evidence_id")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence_id values must be unique")

    evidence_pack = json.dumps(
        evidence_items,
        ensure_ascii=False,
        indent=2,
    )
    rendered_prompt = prompt_template.replace(EVIDENCE_PLACEHOLDER, evidence_pack)
    return rendered_prompt, evidence, prompt_template


def chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def load_solar_request_options() -> dict[str, Any]:
    options = json.loads(SOLAR_REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(options, dict):
        raise ValueError(f"{SOLAR_REQUEST_PATH} must contain a JSON object")

    reserved_keys = {"model", "messages"}
    conflicting_keys = sorted(reserved_keys.intersection(options))
    if conflicting_keys:
        raise ValueError(
            f"{SOLAR_REQUEST_PATH} cannot override: {', '.join(conflicting_keys)}"
        )
    return options


def request_payload(prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": require_env("SOLAR_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": parse_float_env("SOLAR_TEMPERATURE", 0.7),
        "top_p": parse_float_env("SOLAR_TOP_P", 1.0),
        "max_tokens": parse_int_env("SOLAR_MAX_TOKENS", 4096),
    }

    seed = os.environ.get("SOLAR_SEED", "").strip()
    if seed:
        payload["seed"] = int(seed)
    payload.update(load_solar_request_options())
    return payload


def call_solar(
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw_body = error.read().decode("utf-8", errors="replace")
        try:
            parsed_error = json.loads(raw_body)
        except json.JSONDecodeError:
            parsed_error = {}

        api_error = (
            parsed_error.get("error", parsed_error)
            if isinstance(parsed_error, dict)
            else {}
        )
        if not isinstance(api_error, dict):
            api_error = {}
        raise SolarAPIError(
            status_code=error.code,
            message=(
                api_error.get("message")
                or api_error.get("detail")
                or f"HTTP {error.code} {error.reason}"
            ),
            error_type=api_error.get("type"),
            error_code=api_error.get("code"),
        ) from None
    parsed = json.loads(response_body)
    if not isinstance(parsed, dict):
        raise ValueError("Solar response must be a JSON object")
    return parsed


def extract_message(response: dict[str, Any]) -> tuple[str, str | None]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Solar response has no choices")

    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Solar response has no assistant message")

    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("Solar assistant content is not a string")

    reasoning = message.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, str):
        reasoning = str(reasoning)
    return content, reasoning


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def safe_error(error: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    if isinstance(error, SolarAPIError):
        result["status_code"] = error.status_code
        result["api_error_type"] = error.error_type
        result["api_error_code"] = error.error_code
    return result


def run(args: argparse.Namespace) -> int:
    prompt, evidence, prompt_template = build_prompt()

    if args.dry_run:
        print(
            json.dumps(
                {
                    "case_id": evidence.get("case_id"),
                    "evidence_count": len(evidence["evidence"]),
                    "prompt_template_sha256": sha256_text(prompt_template),
                    "evidence_file_sha256": hashlib.sha256(
                        EVIDENCE_PATH.read_bytes()
                    ).hexdigest(),
                    "rendered_prompt_sha256": sha256_text(prompt),
                    "rendered_prompt_chars": len(prompt),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    load_env(ENV_PATH)

    if args.runs < 1:
        raise ValueError("--runs must be at least 1")

    base_url = require_env("SOLAR_BASE_URL")
    model = require_env("SOLAR_MODEL")
    api_key = os.environ.get("SOLAR_API_KEY", "").strip()
    timeout_seconds = parse_int_env("SOLAR_TIMEOUT_SECONDS", 180)
    endpoint = chat_completions_url(base_url)
    payload = request_payload(prompt)

    runs_root = CASE_DIR / "runs"
    run_dir = runs_root / f"01_{timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, Any] = {
        "case_id": evidence.get("case_id"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_runs": args.runs,
        "model": model,
        "generation": {
            "temperature": payload["temperature"],
            "top_p": payload["top_p"],
            "max_tokens": payload["max_tokens"],
            "seed": payload.get("seed"),
            "reasoning_effort": payload.get("reasoning_effort"),
        },
        "solar_request_file_sha256": hashlib.sha256(
            SOLAR_REQUEST_PATH.read_bytes()
        ).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "max_retries": 0,
        "prompt_template_sha256": sha256_text(prompt_template),
        "evidence_file_sha256": hashlib.sha256(
            EVIDENCE_PATH.read_bytes()
        ).hexdigest(),
        "rendered_prompt_sha256": sha256_text(prompt),
        "results": [],
    }
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")

    for run_number in range(1, args.runs + 1):
        run_started_at = datetime.now(timezone.utc)
        result: dict[str, Any] = {
            "run_number": run_number,
            "started_at": run_started_at.isoformat(),
        }
        try:
            response = call_solar(
                url=endpoint,
                api_key=api_key,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            content, reasoning = extract_message(response)
            result.update(
                {
                    "status": "success",
                    "response_file": f"response_{run_number:02d}.json",
                    "answer_file": f"answer_{run_number:02d}.md",
                    "answer_sha256": sha256_text(content),
                }
            )
            write_json(run_dir / result["response_file"], response)
            (run_dir / result["answer_file"]).write_text(
                content + ("\n" if content and not content.endswith("\n") else ""),
                encoding="utf-8",
            )
            if reasoning is not None:
                reasoning_file = f"reasoning_{run_number:02d}.txt"
                (run_dir / reasoning_file).write_text(reasoning, encoding="utf-8")
                result["reasoning_file"] = reasoning_file
        except Exception as error:
            result.update(
                {
                    "status": "failed",
                    "error": safe_error(error),
                }
            )

        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        result["elapsed_seconds"] = (
            datetime.fromisoformat(result["finished_at"]) - run_started_at
        ).total_seconds()
        manifest["results"].append(result)
        write_json(run_dir / "manifest.json", manifest)
        print(f"[{run_number}/{args.runs}] {result['status']}")

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["success_count"] = sum(
        result["status"] == "success" for result in manifest["results"]
    )
    manifest["failure_count"] = sum(
        result["status"] == "failed" for result in manifest["results"]
    )
    write_json(run_dir / "manifest.json", manifest)
    print(f"Results: {run_dir}")
    return 0 if manifest["failure_count"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed 01 Solar prompt test."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="Number of independent calls (default: 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and hash the rendered prompt without calling Solar.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as error:
        print(f"error: {safe_error(error)['message']}", file=sys.stderr)
        raise SystemExit(2)
