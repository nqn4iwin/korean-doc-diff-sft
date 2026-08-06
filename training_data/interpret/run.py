"""홈즈(역할 A) 프롬프트를 고정 평가 세트에 돌리고, 기계로 매길 수 있는 것만 채점한다.

프롬프트를 코드에서 떼어 `prompts/<버전>.txt`에 둔 이유는 버전끼리 diff가 나오게 하기
위해서다. 치환은 `string.Template`(`$before` 꼴)을 쓴다 -- `str.format`은 프롬프트에
들어 있는 JSON 스키마의 중괄호를 서식 지시자로 읽고 깨진다.

채점은 `rubric.md`의 A1~A5만 한다. B1·B2(`direct_impact`가 영향 주체를 짚었는지,
재진술이 아닌지)는 사람이 읽어야 하므로 여기서 매기지 않고, 읽을 수 있게 파일로 남긴다.

같은 항목을 여러 번 돌리는 이유는 `temperature`가 0이 아니어서다. 1회 결과로 좋아졌다고
하면 노이즈를 붙잡을 수 있다.

사용:
    python training_data/interpret/run.py --prompt v1
    python training_data/interpret/run.py --prompt v1.1 --split holdout
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from string import Template

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = ["기한·시점", "수치·기준", "적용 범위", "수행 주체",
           "절차·요건", "제출물·기재사항", "명칭"]
DIRECTIONS = ["늘었다", "줄었다", "다른 값", "새로 생겼다", "없어졌다"]


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


# 호출 하나를 rubric.md의 A1~A5로 채점한다. 각 항목 0 또는 1.
def score(item: dict, raw: str) -> dict:
    """rubric.md의 A1~A5. B1·B2는 사람 몫이라 매기지 않는다."""
    result = {k: 0 for k in ("A1", "A2", "A3", "A4", "A5")}
    parsed = parse_output(raw)
    if parsed is None:
        return {**result, "parsed": None}
    result["A1"] = 1

    pairs = label_pairs(parsed.get("labels", []))
    if pairs is None:
        return {**result, "parsed": parsed}
    result["A2"] = int(all(t in TARGETS and d in DIRECTIONS for t, d in pairs))
    result["A3"] = int(len(pairs) == len(set(pairs)))
    result["A4"] = int(str(parsed.get("judgement", "")).strip() == item["judgement"])
    expected = {(x["대상"], x["방향"]) for x in item["labels"]}
    result["A5"] = int(set(pairs) == expected)
    return {**result, "parsed": parsed}


# 프롬프트 하나를 고른 split에 repeat회씩 돌리고, 채점 결과를 runs/ 아래에 남긴다.
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", required=True, help="prompts/<이 값>.txt")
    ap.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    ap.add_argument("--repeat", type=int, default=3)
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

    records, failures = [], 0
    print(f"프롬프트 {args.prompt} · {args.split} {len(items)}건 × {args.repeat}회")
    for item in items:
        # given_labels는 v0.3(라벨 값을 준 조건)만 쓴다. 나머지 프롬프트에는 그 자리가
        # 없으므로 넘겨도 무시된다 -- 빠지면 substitute가 KeyError로 터진다.
        prompt = template.substitute(
            before_id=item["before_id"], before=item["before"],
            after_id=item["after_id"], after=item["after"],
            given_labels="\n".join(
                f"- ({x['대상']}, {x['방향']})" for x in item["labels"]) or "- (없음)",
        )
        marks = []
        for turn in range(1, args.repeat + 1):
            try:
                response = solar.call_solar(
                    url, api_key, solar.request_payload(prompt), timeout)
                raw, _ = solar.extract_message(response)
            except Exception as error:
                failures += 1
                marks.append("x")
                records.append({"item": item["id"], "turn": turn,
                                "error": solar.safe_error(error)})
                continue
            marked = score(item, raw)
            parsed = marked.pop("parsed")
            record = {"item": item["id"], "turn": turn, "scores": marked,
                      "labels": (parsed or {}).get("labels"),
                      "direct_impact": (parsed or {}).get("direct_impact"),
                      "raw": raw}
            records.append(record)
            marks.append(str(sum(marked.values())))
        print(f"  {item['id']:<22} {item['split']:<8} A점수 {' '.join(marks)} / 5")

    graded = [r for r in records if "scores" in r]
    totals = {k: sum(r["scores"][k] for r in graded) for k in ("A1", "A2", "A3", "A4", "A5")}
    summary = {
        "prompt": args.prompt, "split": args.split, "repeat": args.repeat,
        "calls": len(records), "failures": failures,
        "A_rates": {k: round(v / len(graded), 3) for k, v in totals.items()} if graded else {},
        "A_mean": round(sum(totals.values()) / (5 * len(graded)), 3) if graded else 0,
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "records.json", records)

    print()
    for key, rate in summary["A_rates"].items():
        print(f"  {key} {rate:>6.1%}")
    print(f"  A 평균 {summary['A_mean']:.1%}   실패 {failures}건")
    print(f"\n저장: {out_dir.relative_to(REPOSITORY_DIR)}")
    print("B1·B2는 records.json의 direct_impact를 읽고 사람이 매깁니다.")


if __name__ == "__main__":
    main()
