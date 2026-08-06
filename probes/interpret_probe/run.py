"""Blind label-recovery probe: give Solar only before/after text, no operator label."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import solar  # noqa: E402  -- needs REPO on the path first

solar.load_env()

LABELS = [
    "scope_expanded", "scope_reduced", "obligation_strengthened",
    "obligation_weakened", "threshold_increased", "threshold_decreased",
    "responsibility_shifted", "deadline_changed", "deliverable_added",
    "verification_added", "technology_prescribed", "ambiguity_resolved",
    "wording_only",
]

PROMPT = """당신은 두 공문서 버전의 같은 조항을 비교해 변경을 분석하는 전문가입니다.

아래는 인사혁신처 개인정보처리방침의 이전판과 최신판에서 대응하는 블록입니다.
제공된 두 텍스트만 근거로 판단하세요. 외부 지식이나 추측을 사실처럼 쓰지 마세요.

대응 관계: 1:1(수정) | 1:N(분할) | N:1(병합) | 1:0(삭제) | 0:1(신설)
변화 유형: lexical | structural | semantic
의미 변화 레이블: {labels}

설명이나 코드 펜스 없이 유효한 JSON 객체 하나만 출력하세요.

{{
  "mapping": "1:1 | 1:N | N:1 | 1:0 | 0:1",
  "diff_types": ["lexical | structural | semantic"],
  "semantic_labels": ["허용된 레이블만"],
  "changed_span": {{"before": "직접 달라진 부분", "after": "직접 달라진 부분"}},
  "direct_impact": "정보주체·담당부서·수탁자 등에 미치는 직접적인 실무 영향을 2문장 이내로",
  "confidence": "high | medium | low"
}}

[이전판 블록]
{before}

[최신판 블록]
{after}
"""

CASES = [
    {
        "id": "C1",
        "note": "쿠키 미사용 -> 사용",
        "before": "① 인사혁신처는 쿠키(Cookie)를 사용한 개인정보 수집을 하고 있지 않습니다.",
        "after": (
            "① 인사혁신처는 이용자 웹사이트 방문기록 파악을 위해 이용정보를 저장하고 불러오는 "
            "‘쿠키(cookie)’를 사용합니다.\n"
            "② 쿠키는 웹사이트를 운영하는데 이용되는 서버(http)가 이용자의 컴퓨터 브라우저에게 "
            "보내는 소량의 정보이며 이용자들의 PC내의 하드디스크에 저장되기도 합니다.\n"
            "③ 정보주체는 웹 브라우저 옵션 설정을 통해 쿠키 허용, 차단 등의 설정을 할 수 있습니다. "
            "다만, 쿠키 저장을 거부할 경우 맞춤형 서비스 이용에 어려움이 발생할 수 있습니다."
        ),
        "key": {"mapping": "1:N", "labels": ["scope_expanded"]},
    },
    {
        "id": "C2",
        "note": "재위탁 시 위탁자 동의 조항 신설",
        "before": "(이전판에 대응하는 조항 없음)",
        "after": (
            "③ 「개인정보 보호법」 제26조 제6항에 따라 수탁자가 당사의 개인정보 처리업무를 "
            "재위탁하는 경우 인사혁신처의 동의를 받고 있습니다."
        ),
        "key": {"mapping": "0:1", "labels": ["obligation_strengthened"]},
    },
    {
        "id": "C3",
        "note": "자동화된 결정 거부권 제한 신설",
        "before": (
            "⑥ 인사혁신처는 정보주체 권리에 따른 열람의 요구, 정정ㆍ삭제의 요구, 처리정지 요구 또는 "
            "동의 철회 시 열람 등 요구를 한 자가 본인이거나 정당한 대리인인지를 확인합니다."
        ),
        "after": (
            "⑥ 자동화된 결정이 이루어진다는 사실에 대해 정보주체의 동의를 받았거나, 계약 등을 통해 "
            "미리 알린 경우, 법률에 명확히 규정이 있는 경우에는 자동화된 결정에 대한 거부는 "
            "인정되지 않으며 설명 및 검토 요구만 가능합니다.\n"
            "또한, 자동화된 결정에 대한 거부·설명 요구는 다른 사람의 생명·신체·재산과 그 밖의 이익을 "
            "부당하게 침해할 우려가 있는 등 정당한 사유가 있는 경우에는 그 요구가 거절될 수 있습니다."
        ),
        "key": {"mapping": "0:1", "labels": ["scope_expanded", "obligation_weakened"]},
    },
    {
        "id": "C4",
        "note": "관리수준 진단 -> 평가, 근거조항 제11조 -> 제11조의2",
        "before": (
            "① 인사혁신처는 정보주체의 개인정보를 안전하게 관리하기 위해 「개인정보 보호법」제11조에 "
            "따라 매년 개인정보보호위원회에서 실시하는 “공공기관 개인정보 관리수준 진단”을 받고 있습니다."
        ),
        "after": (
            "① 인사혁신처는 정보주체의 개인정보를 안전하게 관리하기 위해 「개인정보보호법」 제11조의2 및 "
            "「개인정보보호법 시행령」 제13조의2에 따라 매년 개인정보보호위원회에서 실시하는 "
            "“공공기관 개인정보 관리수준 평가(구 공공기관 개인정보 관리수준 진단)”을 받고 있습니다."
        ),
        "key": {"mapping": "1:1", "labels": ["wording_only", "verification_added"]},
    },
    {
        "id": "C5",
        "note": "동의 철회 -> 동의 정지 (미묘/애매)",
        "before": "개인정보(열람, 정정ㆍ삭제, 처리정지, 동의 철회) 요구서 다운로드",
        "after": "개인정보(열람,정정·삭제,처리정지,동의정지)요구서 다운로드",
        "key": {"mapping": "1:1", "labels": ["wording_only"]},
    },
    {
        "id": "C6",
        "note": "처리 목적 조항 1:N 분할 + 최소수집/목적외이용 금지 명시",
        "before": "① 인사혁신처는 다음과 같이 정보주체의 개인정보를 처리합니다.",
        "after": (
            "① 인사혁신처는 다음의 목적을 위하여 최소한의 개인정보를 수집하여 처리합니다. "
            "처리하고 있는 개인정보는 다음 목적 이외의 용도로는 이용되지 않으며, 이용 목적이 "
            "변경되는 경우에는 「개인정보 보호법」제18조에 따라 별도의 동의를 받는 등 필요한 "
            "조치를 이행할 예정입니다.\n"
            "② 인사혁신처는 법령에 따른 개인정보 보유·이용기간 또는 정보주체로부터 개인정보를 "
            "수집 시에 동의 받은 개인정보 보유·이용기간 내에서 개인정보를 처리·보유합니다.\n"
            "③ 인사혁신처에서 처리하는 개인정보의 처리목적, 개인정보의 처리 및 보유기간, 처리항목은 "
            "업무별로 별도로 지정하여 운영하고 있으며 세부사항은 아래와 같습니다."
        ),
        "key": {"mapping": "1:N", "labels": ["obligation_strengthened", "scope_reduced"]},
    },
]

endpoint = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
api_key = os.environ.get("SOLAR_API_KEY", "").strip()
model = solar.require_env("SOLAR_MODEL")
timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))


def ask(case: dict) -> dict:
    prompt = PROMPT.format(
        labels=" | ".join(LABELS), before=case["before"], after=case["after"]
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "top_p": 1.0,
        "max_tokens": 2048,
        "reasoning_effort": "low",
    }
    try:
        resp = solar.call_solar(endpoint, api_key, payload, timeout)
        content, _ = solar.extract_message(resp)
        usage = resp.get("usage", {})
    except Exception as exc:  # noqa: BLE001
        return {"id": case["id"], "error": f"{type(exc).__name__}: {exc}"}
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return {"id": case["id"], "error": "invalid JSON", "raw": content[:400]}
    return {"id": case["id"], "note": case["note"], "key": case["key"],
            "answer": parsed, "usage": usage}


with ThreadPoolExecutor(max_workers=6) as pool:
    results = list(pool.map(ask, CASES))

out = Path(__file__).with_name("interpret_probe_result.json")
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"saved: {out}\n")

for r in results:
    print("=" * 70)
    print(f"[{r['id']}] {r.get('note', '')}")
    if "error" in r:
        print("  ERROR:", r["error"])
        print("  raw:", r.get("raw", "")[:300])
        continue
    a, k = r["answer"], r["key"]
    ok_map = a.get("mapping") == k["mapping"]
    got = set(a.get("semantic_labels") or [])
    hit = got & set(k["labels"])
    print(f"  mapping  key={k['mapping']:>3}  solar={a.get('mapping'):>3}  {'O' if ok_map else 'X'}")
    print(f"  labels   key={k['labels']}")
    print(f"           solar={a.get('semantic_labels')}  {'O' if hit else 'X'}")
    print(f"  types    {a.get('diff_types')}   conf={a.get('confidence')}")
    print(f"  impact   {a.get('direct_impact')}")
