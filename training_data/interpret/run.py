"""홈즈(역할 A) 프롬프트를 고정 평가 세트에 돌리고, 기계로 매길 수 있는 것만 채점한다.

프롬프트를 코드에서 떼어 `prompts/<버전>.txt`에 둔 이유는 버전끼리 diff가 나오게 하기
위해서다. 치환은 `string.Template`(`$before` 꼴)을 쓴다 -- `str.format`은 프롬프트에
들어 있는 JSON 스키마의 중괄호를 서식 지시자로 읽고 깨진다.

채점은 `rubric.md`의 AM1~AM8을 한다. AH1(재진술이 아닌지)은 사람이 읽어야 하므로 여기서
매기지 않고, 읽을 수 있게 파일로 남긴다. 다만 개정 후 원문과 너무 닮은 것은 사람이
읽기 전에 걸러낼 수 있으므로 유사도를 함께 기록한다.

같은 항목을 여러 번 돌리는 이유는 `temperature`가 0이 아니어서다. 1회 결과로 좋아졌다고
하면 노이즈를 붙잡을 수 있다.

사용:
    python training_data/interpret/run.py --prompt v1
    python training_data/interpret/run.py --prompt v1.1 --split holdout
    python training_data/interpret/run.py --prompt v2.2 --concurrency 8
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
KEYS = ("AM1", "AM2", "AM3", "AM4", "AM5", "AM6", "AM7", "AM8")
TARGETS = ["기한·시점", "수치·기준", "적용 범위", "수행 주체",
           "절차·요건", "제출물·기재사항", "명칭"]
DIRECTIONS = ["늘었다", "줄었다", "다른 값", "새로 생겼다", "없어졌다"]

# rubric.md의 기계 선별기. 이 값 이상이면 사람이 읽지 않고 AH1을 0으로 둔다. 합격 판정에는
# 쓰지 않는다 -- 유사도가 낮은 실패가 실제로 있다(v1의 terms-game-renumber가 0.31에 실패).
# 18호출에 맞춘 값이라 근거가 약하다는 것도 rubric.md에 적어 뒀다.
RESTATEMENT_THRESHOLD = 0.60


# 모델이 JSON 앞뒤에 붙인 군더더기를 걷어내고 객체 하나만 꺼낸다.
def parse_output(text: str) -> dict | None:
    """모델 출력에서 JSON 객체 하나를 꺼낸다. 코드펜스는 벗긴다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned.split("\n", 1)[1] if cleaned.startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        result = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


# labels 배열을 (대상, 방향) 튜플 목록으로 바꾼다. 모양이 어긋나면 None.
def label_pairs(labels) -> list[tuple[str, str]] | None:
    if not isinstance(labels, list):
        return None
    pairs = []
    for entry in labels:
        if not isinstance(entry, dict):
            return None
        pairs.append((str(entry.get("대상", "")), str(entry.get("방향", ""))))
    return pairs


# impacts 배열에서 주체 문자열만 꺼낸다. 모양이 어긋나면 빈 목록.
def impact_subjects(impacts) -> list[str]:
    if not isinstance(impacts, list):
        return []
    return [str(x.get("주체", "")) for x in impacts if isinstance(x, dict)]


# 허용 표기 중 하나라도 안에 들어 있으면 그 주체를 담은 것으로 본다. 표기가 흔들리기
# 때문이다 -- `연구책임자`가 `주관연구개발기관의 연구책임자`로 나와도 같은 사람이다.
def mentions(haystack: str, forms: list[str]) -> bool:
    return any(form and form in haystack for form in forms)


# AM8이 쓰는 주체 대조. 어절로 쪼개 절반 이상 남았으면 같은 주체로 본다.
SUBJECT_WORD = re.compile(r"[\s,·ㆍ()]+")
SUBJECT_KEPT = 0.5


def subject_survives(subject: str, sentence: str) -> bool:
    """주체가 문장에 남아 있는가. 통째로 있으면 참, 줄여 썼으면 어절 비율로 본다.

    **글자 그대로 대조하면 흘린 것과 줄여 쓴 것이 구별되지 않는다.** 모델이 배열에
    `연구개발성과의 활용 촉진을 수행하는 기관`이라 적고 문장에서 `촉진을 수행하는
    기관`으로 줄이면 같은 주체인데도 실패로 잡힌다. 697건에서 엄격 대조 실패 109건 중
    56건이 이 종류였다. AM8이 잡으려는 것은 주체를 **빠뜨린** 출력이지 짧게 쓴 출력이
    아니다.

    문턱을 절반으로 둔 대가는 재봤다. 56건 중 `사람`·`기관` 같은 흔한 낱말 하나로만
    통과하는 것이 3건이다. 그 정도는 감수한다.
    """
    if not subject:
        return True
    if subject in sentence:
        return True
    words = [w for w in SUBJECT_WORD.split(subject) if len(w) >= 2]
    if not words:
        return False
    return sum(1 for w in words if w in sentence) / len(words) >= SUBJECT_KEPT


# 호출 하나를 rubric.md의 AM1~AM8로 채점한다. 각 항목 0 또는 1.
def score(item: dict, raw: str) -> dict:
    """rubric.md의 AM1~AM8. AH1(재진술 아님)은 사람 몫이라 매기지 않는다."""
    result = {k: 0 for k in KEYS}
    parsed = parse_output(raw)
    if parsed is None:
        return {**result, "parsed": None}
    result["AM1"] = 1

    pairs = label_pairs(parsed.get("labels", []))
    if pairs is None:
        return {**result, "parsed": parsed}
    result["AM2"] = int(all(t in TARGETS and d in DIRECTIONS for t, d in pairs))
    result["AM3"] = int(len(pairs) == len(set(pairs)))
    result["AM4"] = int(str(parsed.get("judgement", "")).strip() == item["judgement"])
    expected = {(x["대상"], x["방향"]) for x in item["labels"]}
    result["AM5"] = int(set(pairs) == expected)

    subjects = impact_subjects(parsed.get("impacts"))
    sentence = str(parsed.get("direct_impact") or "")

    # AM6 -- negative면 둘 다 비어 있어야 한다. positive면 이 항목은 자동 1점이라,
    # negative 항목에서만 실제로 걸린다.
    if item["judgement"] == "negative":
        result["AM6"] = int(not subjects and not sentence.strip())
    else:
        result["AM6"] = 1

    # AM7 -- 정답 주체를 다 담았나. 포함 관계로만 보고 여분은 깎지 않는다(rubric.md).
    # 정답이 빈 목록이면(negative) 자동으로 참이 된다.
    blob = " ".join(subjects)
    result["AM7"] = int(all(mentions(blob, ref["주체"])
                           for ref in item.get("reference_impacts", [])))

    # AM8 -- 자기가 낸 주체를 문장에서 흘리지 않았나. positive인데 배열이 비어 있으면
    # 검사할 것이 없어 자동으로 참이 되므로, 그 경우는 0으로 막는다. 안 그러면 배열을
    # 통째로 빼먹은 출력이 이 점수를 공짜로 받는다.
    if item["judgement"] == "positive" and not subjects:
        result["AM8"] = 0
    else:
        result["AM8"] = int(all(subject_survives(s, sentence) for s in subjects if s))
    return {**result, "parsed": parsed}


# AH1을 사람이 읽기 전에 명백한 복사를 걸러낸다. 합격 판정이 아니라 걸러내기다.
def restatement_ratio(item: dict, sentence: str) -> float | None:
    if not sentence.strip():
        return None
    return round(difflib.SequenceMatcher(
        None, sentence, item["after"], autojunk=False).ratio(), 3)


# 프롬프트 하나를 고른 split에 repeat회씩 돌리고, 채점 결과를 runs/ 아래에 남긴다.
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", required=True, help="prompts/<이 값>.txt")
    ap.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=8,
                    help="동시에 띄울 요청 수. 한 건씩 보내면 서버에 요청이 항상 하나만 "
                         "떠 있어 GPU가 논다(generate.py와 같은 이유)")
    args = ap.parse_args()

    template = Template((HERE / "prompts" / f"{args.prompt}.txt").read_text(encoding="utf-8"))
    evalset = solar.read_json(HERE / "evalset.json")
    items = [x for x in evalset["items"]
             if args.split == "all" or x["split"] == args.split]
    if not items:
        raise SystemExit(f"{args.split}에 해당하는 항목이 없습니다")

    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))

    out_dir = HERE / "runs" / f"{solar.timestamp()}__{args.prompt}__{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # (항목, 회차)를 미리 펼쳐 두고 동시에 띄운다. 한 건씩 보내면 24호출에 몇 분이 걸린다.
    # ThreadPoolExecutor.map은 입력 순서대로 결과를 돌려주므로 기록 순서는 전과 같다.
    jobs = []
    for item in items:
        # given_labels는 v0.3(라벨 값을 준 조건)만 쓴다. 나머지 프롬프트에는 그 자리가
        # 없으므로 넘겨도 무시된다 -- 빠지면 substitute가 KeyError로 터진다.
        prompt = template.substitute(
            before_id=item["before_id"], before=item["before"],
            after_id=item["after_id"], after=item["after"],
            given_labels="\n".join(
                f"- ({x['대상']}, {x['방향']})" for x in item["labels"]) or "- (없음)",
        )
        jobs.extend((item, turn, prompt) for turn in range(1, args.repeat + 1))

    def work(job: tuple) -> dict:
        item, turn, prompt = job
        try:
            response = solar.call_solar(
                url, api_key, solar.request_payload(prompt), timeout)
            raw, _ = solar.extract_message(response)
        except Exception as error:
            return {"item": item["id"], "turn": turn,
                    "error": solar.safe_error(error)}
        marked = score(item, raw)
        parsed = marked.pop("parsed")
        sentence = (parsed or {}).get("direct_impact") or ""
        ratio = restatement_ratio(item, sentence)
        # impacts는 v2부터 나온다. v1 이하에는 없으므로 None으로 남는다.
        # ah1_screen이 True면 사람이 읽지 않고 AH1을 0으로 둔다(rubric.md).
        return {"item": item["id"], "turn": turn, "scores": marked,
                "labels": (parsed or {}).get("labels"),
                "impacts": (parsed or {}).get("impacts"),
                "direct_impact": (parsed or {}).get("direct_impact"),
                "restatement_ratio": ratio,
                "ah1_screen": bool(ratio is not None
                                   and ratio >= RESTATEMENT_THRESHOLD),
                "raw": raw}

    print(f"프롬프트 {args.prompt} · {args.split} {len(items)}건 × {args.repeat}회"
          f" = {len(jobs)}호출 (동시 {args.concurrency})")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        records = list(pool.map(work, jobs))
    failures = sum(1 for r in records if "error" in r)

    for item in items:
        marks = [str(sum(r["scores"].values())) if "scores" in r else "x"
                 for r in records if r["item"] == item["id"]]
        print(f"  {item['id']:<22} {item['split']:<8} A점수 {' '.join(marks)} / {len(KEYS)}")

    graded = [r for r in records if "scores" in r]
    totals = {k: sum(r["scores"][k] for r in graded) for k in KEYS}
    screened = sum(1 for r in graded if r["ah1_screen"])
    summary = {
        "prompt": args.prompt, "split": args.split, "repeat": args.repeat,
        "calls": len(records), "failures": failures,
        "AM_rates": {k: round(v / len(graded), 3) for k, v in totals.items()} if graded else {},
        "AM_mean": round(sum(totals.values()) / (len(KEYS) * len(graded)), 3) if graded else 0,
        "ah1_screened_out": screened,
        "restatement_threshold": RESTATEMENT_THRESHOLD,
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "records.json", records)

    print()
    for key, rate in summary["AM_rates"].items():
        print(f"  {key} {rate:>6.1%}")
    print(f"  A 평균 {summary['AM_mean']:.1%}   실패 {failures}건")
    print(f"\n저장: {out_dir.relative_to(REPOSITORY_DIR)}")
    print(f"AH1은 records.json의 impacts·direct_impact를 읽고 사람이 매깁니다.")
    print(f"  유사도 {RESTATEMENT_THRESHOLD} 이상이라 안 읽어도 되는 것: {screened}건"
          f" (ah1_screen이 true)")


if __name__ == "__main__":
    main()
