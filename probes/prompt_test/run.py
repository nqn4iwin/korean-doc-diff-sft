from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = TEST_DIR.parents[1]
sys.path.insert(0, str(REPOSITORY_DIR))
from solar import (  # noqa: E402  -- needs REPOSITORY_DIR on the path first
    SOLAR_REQUEST_PATH, call_solar, chat_completions_url, extract_message,
    load_env, read_json, request_payload, require_env, safe_error,
    sha256_bytes, sha256_text, timestamp, write_json,
)

CASE_ID = "R26BD00244326_R26BK01607991-001"
INPUT_DIR = TEST_DIR / "data" / CASE_ID
PROMPT_PATH = TEST_DIR / "prompt.txt"
PRIOR_SPEC_PATH = INPUT_DIR / "prior_spec.json"
BID_NOTICE_PATH = INPUT_DIR / "bid_notice.json"
PLACEHOLDERS = {
    "{{PRIOR_SPEC_JSON}}": PRIOR_SPEC_PATH,
    "{{BID_NOTICE_JSON}}": BID_NOTICE_PATH,
}


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

    load_env()
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
