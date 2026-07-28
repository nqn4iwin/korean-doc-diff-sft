from __future__ import annotations

import hashlib
import json
import sys

from _common import (
    CollectionError,
    MANIFEST_PATH,
    RAW_DIR,
    REPOSITORY_DIR,
    encode_json,
    load_project_env,
    redact_payload,
    require_env,
)


def main() -> int:
    load_project_env()
    oc = require_env("LAW_OPEN_API_OC")
    updated: dict[str, tuple[int, str]] = {}

    for path in (RAW_DIR / "law").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        safe_raw = encode_json(redact_payload(payload, [oc]))
        path.write_bytes(safe_raw)
        relative_path = path.relative_to(REPOSITORY_DIR).as_posix()
        updated[relative_path] = (
            len(safe_raw),
            hashlib.sha256(safe_raw).hexdigest(),
        )

    if MANIFEST_PATH.exists() and updated:
        records = []
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("file") in updated:
                record["bytes"], record["sha256"] = updated[record["file"]]
            records.append(record)
        content = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        )
        MANIFEST_PATH.write_text(content, encoding="utf-8", newline="\n")

    print(f"마스킹 완료: {len(updated)}개 파일")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CollectionError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        raise SystemExit(1) from None
