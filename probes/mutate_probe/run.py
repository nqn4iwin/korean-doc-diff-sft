"""Role B probe: make Solar write a realistic revision for a named operator.

Pipeline per item:
  1. generate  - real block + operator definition -> revised block (temperature 0.9)
  2. check     - mechanical checks on locality and diversity
  3. roundtrip - blind role A recovers the operator from before/after alone
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
import solar  # noqa: E402  -- needs REPO on the path first

solar.load_env()

ENDPOINT = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
MODEL = solar.require_env("SOLAR_MODEL")
API_KEY = os.environ.get("SOLAR_API_KEY", "").strip()
TIMEOUT = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))

SOURCE = "인사혁신처 개인정보처리방침 (privacyOld15)"

# Operator name -> judgement criterion. The blind probe showed that a bare label
# list is not enough: without a criterion both the model and the human key drift.
OPERATORS = {
    "threshold_increased": "수치·기간·횟수·비율 기준이 커지거나 길어진다.",
    "obligation_strengthened": "의무 수준이 높아진다. 재량이 의무가 되거나, 조건·절차·요건이 추가된다.",
    "obligation_weakened": "의무 수준이 낮아진다. 의무가 재량이 되거나, 예외·면책 사유가 신설된다.",
    "scope_expanded": "적용 대상·항목·범위·수단이 넓어진다.",
    "scope_reduced": "적용 대상·항목·범위·수단이 좁아진다.",
    "responsibility_shifted": "수행 주체 또는 책임 주체가 다른 주체로 바뀐다.",
    "deadline_changed": "기한·시점·주기가 다른 값으로 바뀐다.",
    "verification_added": "확인·점검·증빙·기록 절차가 새로 요구된다.",
}

# Real revisions observed in privacyOld14 -> privacyOld15. Grounding the model in
# actual amendment register, not an invented one.
FEWSHOT = """[실제 개정 사례 1] operator=obligation_strengthened
before: (해당 조항 없음)
after: ③ 「개인정보 보호법」 제26조 제6항에 따라 수탁자가 당사의 개인정보 처리업무를 재위탁하는 경우 인사혁신처의 동의를 받고 있습니다.

[실제 개정 사례 2] operator=scope_expanded
before: ① 인사혁신처는 쿠키(Cookie)를 사용한 개인정보 수집을 하고 있지 않습니다.
after: ① 인사혁신처는 이용자 웹사이트 방문기록 파악을 위해 이용정보를 저장하고 불러오는 ‘쿠키(cookie)’를 사용합니다."""

GEN_PROMPT = """당신은 공공기관의 개인정보처리방침을 개정하는 실무 담당자입니다.

아래 조항은 {source}의 실제 원문입니다. 이 조항에 지정된 유형의 개정 하나를 적용해
개정 후 조항을 쓰세요.

[적용할 개정 유형] {operator}
{operator_definition}

[작성 규칙]
1. 원문의 문체, 항 번호(①②③), 존댓말 어미, 법령 인용 방식을 그대로 유지하세요.
2. 지정된 유형의 개정 하나만 적용하세요. 다른 부분은 글자 하나도 바꾸지 마세요.
3. 실제 공공기관이 개정할 법한 내용이어야 합니다. 과장되거나 비현실적인 수치·의무를
   넣지 마세요.
4. 조항 전체를 새로 쓰지 말고, 바뀌어야 할 최소 범위만 고치세요.
5. 개정 유형의 이름이나 분류 용어를 조항 본문에 쓰지 마세요.

{fewshot}

[출력 형식] 설명이나 코드 펜스 없이 유효한 JSON 객체 하나만 출력하세요.
{{
  "after": "개정 후 조항 전문",
  "changed_span_before": "원문에서 직접 바뀐 부분만 그대로 발췌 (신설이면 빈 문자열)",
  "changed_span_after": "개정문에서 직접 바뀐 부분만 그대로 발췌"
}}

[개정 대상 원문]
{before}
"""

BLIND_PROMPT = """당신은 두 공문서 버전의 같은 조항을 비교해 변경을 분석하는 전문가입니다.

제공된 두 텍스트만 근거로 판단하세요. 외부 지식이나 추측을 사실처럼 쓰지 마세요.

의미 변화 레이블과 판정 기준:
{operator_table}

설명이나 코드 펜스 없이 유효한 JSON 객체 하나만 출력하세요.
{{"semantic_labels": ["허용된 레이블만"], "direct_impact": "직접적인 실무 영향을 2문장 이내로"}}

[이전판 조항]
{before}

[최신판 조항]
{after}
"""

BLOCKS = {
    "B-파기": "① 인사혁신처는 개인정보 보유기간의 경과, 처리목적 달성, 가명정보의 처리 기간 경과 등 개인정보가 불필요하게 되었을 때에는 해당 개인정보를 지체 없이 파기합니다.",
    "B-위탁": "② 인사혁신처는 위탁계약 체결 시, 「개인정보 보호법」 제26조에 따라 위탁업무 수행목적 외 개인정보 처리금지, 기술적·관리적 보호조치, 재위탁 제한, 수탁자에 대한 관리·감독, 손해배상 등 책임에 관한 사항을 계약서 등 문서에 명시하고, 수탁자가 개인정보를 안전하게 처리하는지를 감독하고 있습니다.",
    "B-권리행사": "② 권리 행사는 인사혁신처에 대해 「개인정보 보호법」시행령 제41조 제1항에 따라 서면, 전자우편, 모사전송(FAX) 등을 통하여 할 수 있으며, 인사혁신처는 이에 대해 지체 없이 조치하겠습니다.",
    "B-대리인": "③ 권리 행사는 정보주체의 법정대리인이나 위임을 받은 자 등 대리인을 통하여 할 수도 있습니다. 이 경우 “개인정보 처리방법에 관한 고시” 별지 제11호 서식에 따른 위임장을 제출하여야 합니다.",
}

COMBOS = [
    ("B-파기", "deadline_changed"),
    ("B-파기", "obligation_weakened"),
    ("B-파기", "verification_added"),
    ("B-위탁", "scope_expanded"),
    ("B-위탁", "scope_reduced"),
    ("B-위탁", "responsibility_shifted"),
    ("B-권리행사", "scope_expanded"),
    ("B-권리행사", "deadline_changed"),
    ("B-권리행사", "obligation_weakened"),
    ("B-대리인", "obligation_strengthened"),
    ("B-대리인", "threshold_increased"),
    ("B-대리인", "responsibility_shifted"),
]
VARIANTS = 3


def call(prompt: str, temperature: float, seed: int | None) -> tuple[dict | None, str, dict]:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": 1.0,
        "max_tokens": 2048,
        "reasoning_effort": "low",
    }
    if seed is not None:
        payload["seed"] = seed
    resp = solar.call_solar(ENDPOINT, API_KEY, payload, TIMEOUT)
    content, _ = solar.extract_message(resp)
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    try:
        return json.loads(text.strip()), content, resp.get("usage", {})
    except json.JSONDecodeError:
        return None, content, resp.get("usage", {})


def seed_for(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def generate(job: tuple[str, str, int]) -> dict:
    block_id, operator, variant = job
    before = BLOCKS[block_id]
    prompt = GEN_PROMPT.format(
        source=SOURCE,
        operator=operator,
        operator_definition=OPERATORS[operator],
        fewshot=FEWSHOT,
        before=before,
    )
    item = {"block_id": block_id, "operator": operator, "variant": variant,
            "before": before}
    try:
        parsed, raw, usage = call(prompt, 0.9, seed_for(block_id, operator, str(variant)))
    except Exception as exc:  # noqa: BLE001
        return {**item, "error": f"{type(exc).__name__}: {exc}"}
    if parsed is None:
        return {**item, "error": "invalid JSON", "raw": raw[:300]}
    return {**item, "gen": parsed, "gen_usage": usage}


def mechanical_checks(item: dict) -> dict:
    before = item["before"]
    g = item.get("gen") or {}
    after = (g.get("after") or "").strip()
    sb = (g.get("changed_span_before") or "").strip()
    sa = (g.get("changed_span_after") or "").strip()
    checks = {
        "after_differs": bool(after) and after != before,
        "span_before_in_before": sb in before if sb else True,
        "span_after_in_after": sa in after if sa else False,
        # strict locality: replacing the declared span must reproduce `after`
        "locality_exact": (before.replace(sb, sa, 1) == after) if sb else False,
        "operator_name_leaked": item["operator"] in after,
    }
    checks["all_pass"] = all(
        checks[k] for k in ("after_differs", "span_before_in_before", "span_after_in_after")
    ) and not checks["operator_name_leaked"]
    return checks


def roundtrip(item: dict) -> dict:
    g = item.get("gen") or {}
    after = (g.get("after") or "").strip()
    if not after:
        return {"error": "no after text"}
    table = "\n".join(f"- {k}: {v}" for k, v in OPERATORS.items())
    prompt = BLIND_PROMPT.format(
        operator_table=table, before=item["before"], after=after
    )
    try:
        parsed, raw, usage = call(prompt, 0.2, seed_for("blind", item["block_id"],
                                                        item["operator"], str(item["variant"])))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if parsed is None:
        return {"error": "invalid JSON", "raw": raw[:300]}
    got = set(parsed.get("semantic_labels") or [])
    return {"labels": sorted(got), "recovered": item["operator"] in got,
            "direct_impact": parsed.get("direct_impact"), "usage": usage}


def main(workers: int) -> None:
    jobs = [(b, o, v) for b, o in COMBOS for v in range(1, VARIANTS + 1)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        items = list(pool.map(generate, jobs))
    for item in items:
        item["checks"] = mechanical_checks(item)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        trips = list(pool.map(roundtrip, items))
    for item, trip in zip(items, trips):
        item["roundtrip"] = trip

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = HERE / "runs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"result_{stamp}.json"
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = [i for i in items if "error" not in i]
    print(f"generated {len(ok)}/{len(items)}")
    print(f"  mechanical all_pass : {sum(i['checks']['all_pass'] for i in ok)}/{len(ok)}")
    print(f"  locality_exact      : {sum(i['checks']['locality_exact'] for i in ok)}/{len(ok)}")
    print(f"  operator leaked     : {sum(i['checks']['operator_name_leaked'] for i in ok)}/{len(ok)}")
    rt = [i for i in ok if "error" not in i.get("roundtrip", {})]
    print(f"  roundtrip recovered : {sum(i['roundtrip']['recovered'] for i in rt)}/{len(rt)}")
    uniq = {}
    for i in ok:
        uniq.setdefault((i["block_id"], i["operator"]), set()).add(
            (i.get("gen") or {}).get("after", "")
        )
    tot_variants = sum(len(v) for v in uniq.values())
    print(f"  distinct variants   : {tot_variants}/{len(ok)} ({len(uniq)} combos x {VARIANTS})")
    print(f"saved: {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=8)
    main(p.parse_args().workers)
