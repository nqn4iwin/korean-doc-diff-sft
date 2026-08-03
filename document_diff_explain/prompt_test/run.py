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


TEST_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = TEST_DIR.parent.parent
CASE_ID = "R26BD00244326_R26BK01607991-001"
INPUT_DIR = TEST_DIR / "data" / CASE_ID
PROMPT_PATH = TEST_DIR / "prompt.txt"
PRIOR_SPEC_PATH = INPUT_DIR / "prior_spec.json"
BID_NOTICE_PATH = INPUT_DIR / "bid_notice.json"
SOLAR_REQUEST_PATH = REPOSITORY_DIR / "solar_request.json"
ENV_PATH = REPOSITORY_DIR / ".env"
PLACEHOLDERS = {
    "{{PRIOR_SPEC_JSON}}": PRIOR_SPEC_PATH,
    "{{BID_NOTICE_JSON}}": BID_NOTICE_PATH,
}


class SolarAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def validate_document(document: Any, expected_role: str, path: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if document.get("case_id") != CASE_ID:
        raise ValueError(f"{path}: unexpected case_id")
    metadata = document.get("document")
    if not isinstance(metadata, dict) or metadata.get("role") != expected_role:
        raise ValueError(f"{path}: document.role must be {expected_role}")
    blocks = document.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError(f"{path}: blocks must be a non-empty list")
    block_ids = [block.get("id") for block in blocks if isinstance(block, dict)]
    if len(block_ids) != len(blocks) or any(not block_id for block_id in block_ids):
        raise ValueError(f"{path}: every block must have an id")
    if len(block_ids) != len(set(block_ids)):
        raise ValueError(f"{path}: block ids must be unique")
    return document


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_prompt() -> tuple[str, str, dict[str, dict[str, Any]]]:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    for placeholder in PLACEHOLDERS:
        if template.count(placeholder) != 1:
            raise ValueError(f"{PROMPT_PATH} must contain exactly one {placeholder}")

    documents = {
        "prior_spec": validate_document(
            read_json(PRIOR_SPEC_PATH),
            "prior_spec",
            PRIOR_SPEC_PATH,
        ),
        "bid_notice": validate_document(
            read_json(BID_NOTICE_PATH),
            "bid_notice",
            BID_NOTICE_PATH,
        ),
    }
    rendered = template
    for placeholder, path in PLACEHOLDERS.items():
        role = "prior_spec" if path == PRIOR_SPEC_PATH else "bid_notice"
        compact_json = json.dumps(
            documents[role], ensure_ascii=False, separators=(",", ":")
        )
        rendered = rendered.replace(placeholder, compact_json)
    return rendered, template, documents


def load_request_options() -> dict[str, Any]:
    options = json.loads(SOLAR_REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(options, dict):
        raise ValueError(f"{SOLAR_REQUEST_PATH} must contain a JSON object")
    conflicts = sorted({"model", "messages"}.intersection(options))
    if conflicts:
        raise ValueError(f"Cannot override reserved keys: {', '.join(conflicts)}")
    return options


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
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Solar response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Solar response has no assistant message")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise ValueError("Solar assistant content is not a string")
    reasoning = message.get("reasoning")
    return content, None if reasoning is None else str(reasoning)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def safe_error(error: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(error).__name__, "message": str(error)}
    if isinstance(error, SolarAPIError):
        result["status_code"] = error.status_code
    return result


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def run(args: argparse.Namespace) -> int:
    prompt, template, documents = build_prompt()
    input_summary = {
        role: {
            "block_count": len(document["blocks"]),
            "sha256": sha256_bytes(PLACEHOLDERS[
                "{{PRIOR_SPEC_JSON}}" if role == "prior_spec" else "{{BID_NOTICE_JSON}}"
            ].read_bytes()),
        }
        for role, document in documents.items()
    }
    if args.dry_run:
        print(json.dumps({
            "case_id": CASE_ID,
            "inputs": input_summary,
            "prompt_template_sha256": sha256_text(template),
            "rendered_prompt_sha256": sha256_text(prompt),
            "rendered_prompt_chars": len(prompt),
            "gold_reference_included": False,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.runs < 1:
        raise ValueError("--runs must be at least 1")

    load_env(ENV_PATH)
    base_url = require_env("SOLAR_BASE_URL")
    model = require_env("SOLAR_MODEL")
    api_key = os.environ.get("SOLAR_API_KEY", "").strip()
    timeout_seconds = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))
    payload = request_payload(prompt)

    run_dir = TEST_DIR / "runs" / f"02_{timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "case_id": CASE_ID,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_runs": args.runs,
        "model": model,
        "generation": {
            key: payload.get(key)
            for key in ("temperature", "top_p", "max_tokens", "seed", "reasoning_effort")
        },
        "timeout_seconds": timeout_seconds,
        "max_retries": 0,
        "inputs": input_summary,
        "prompt_template_sha256": sha256_text(template),
        "rendered_prompt_sha256": sha256_text(prompt),
        "solar_request_file_sha256": sha256_bytes(SOLAR_REQUEST_PATH.read_bytes()),
        "results": [],
    }
    write_json(run_dir / "manifest.json", manifest)
    (run_dir / "rendered_prompt.txt").write_text(prompt, encoding="utf-8")

    endpoint = chat_completions_url(base_url)
    for run_number in range(1, args.runs + 1):
        started = datetime.now(timezone.utc)
        result: dict[str, Any] = {
            "run_number": run_number,
            "started_at": started.isoformat(),
        }
        try:
            response = call_solar(endpoint, api_key, payload, timeout_seconds)
            answer, reasoning = extract_message(response)
            response_file = f"response_{run_number:02d}.json"
            answer_file = f"answer_{run_number:02d}.md"
            write_json(run_dir / response_file, response)
            (run_dir / answer_file).write_text(
                answer + ("\n" if answer and not answer.endswith("\n") else ""),
                encoding="utf-8",
            )
            result.update({
                "status": "success",
                "response_file": response_file,
                "answer_file": answer_file,
                "answer_sha256": sha256_text(answer),
            })
            if reasoning is not None:
                reasoning_file = f"reasoning_{run_number:02d}.txt"
                (run_dir / reasoning_file).write_text(reasoning, encoding="utf-8")
                result["reasoning_file"] = reasoning_file
        except Exception as error:
            result.update({"status": "failed", "error": safe_error(error)})
        finished = datetime.now(timezone.utc)
        result["finished_at"] = finished.isoformat()
        result["elapsed_seconds"] = (finished - started).total_seconds()
        manifest["results"].append(result)
        write_json(run_dir / "manifest.json", manifest)
        print(f"[{run_number}/{args.runs}] {result['status']}")

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["success_count"] = sum(
        item["status"] == "success" for item in manifest["results"]
    )
    manifest["failure_count"] = args.runs - manifest["success_count"]
    write_json(run_dir / "manifest.json", manifest)
    print(f"Results: {run_dir}")
    return 0 if manifest["failure_count"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed document-diff Solar prompt test 02.")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as error:
        print(f"error: {safe_error(error)['message']}", file=sys.stderr)
        raise SystemExit(2)
