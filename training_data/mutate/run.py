"""모리아티(역할 B) 프롬프트를 고정 평가 세트에 돌리고, 왕복 검증까지 한 번에 매긴다.

역할 A(`../interpret/run.py`)와 다른 점이 둘이다.

첫째, **정답이 하나가 아니다.** "이 조항에 이 변경을 넣은 개정문"은 여럿이므로 문자열
대조로 채점할 수 없다. 그래서 B가 쓴 개정문을 원문과 짝지어 **역할 A에게 blind로 넣고**,
A가 지시받은 `(대상, 방향)`을 짚는지로 판정한다(BM5). A는 B가 무슨 지시를 받았는지 모른다.

둘째, **호출이 두 번이다.** 생성은 다양성이 필요해 temperature를 올리고, 검증은 흔들리면
안 되므로 내린다. `solar_request.json`이 온도를 고정하고 있어 페이로드를 만든 뒤 덮어쓴다.

한 번 실행으로 여러 프롬프트를 돌 수 있다. v0 사전 탐색처럼 조건을 나란히 비교할 때
사람이 명령을 세 번 치지 않아도 되게 한 것이다.

사용:
    python training_data/mutate/run.py --prompt v0.1 v0.2 v0.3
    python training_data/mutate/run.py --prompt v1 --split holdout --repeat 3
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
sys.path.insert(0, str(REPOSITORY_DIR / "source_data"))

import solar  # noqa: E402
import classify_diff  # noqa: E402

HERE = Path(__file__).resolve().parent
INTERPRET = HERE.parent / "interpret"

# 검증에 쓰는 역할 A의 판본. B의 점수가 A를 거쳐 나오므로, 이 값이 바뀌면 같은 B 출력의
# 점수도 달라진다. 기록에 남기고 CHANGELOG에도 적는다(`rubric.md`).
JUDGE_PROMPT = "v2.2"
GENERATE_TEMPERATURE = 0.9   # 같은 조합 3회가 서로 달라야 표본이 는다
JUDGE_TEMPERATURE = 0.2      # 판정은 흔들리면 안 된다

# `docs/학습데이터_생성_프로세스.md` 2절. 프롬프트에 정의를 넣어줄 때 쓴다.
TARGET_DEF = {
    "기한·시점": "조항이 요구하는 날짜, 기간, 처리 기한이 바뀐다",
    "수치·기준": "금액, 비율, 개수, 등급이 바뀐다",
    "적용 범위": "규정이 미치는 대상·경우의 폭이 바뀐다",
    "수행 주체": "일을 하거나 책임지는 쪽이 바뀐다",
    "절차·요건": "밟아야 할 단계나 갖춰야 할 조건이 바뀐다",
    "제출물·기재사항": "내야 하거나 적어야 하는 항목이 바뀐다",
    "명칭": "무언가를 가리키는 이름이나 연락 지점이 바뀐다. 가리켜지는 것 자체는 그대로다",
}
DIRECTION_DEF = {
    "늘었다": "대상의 폭·크기·개수가 커졌다. 개정 전에도 그 대상이 있었다",
    "줄었다": "대상의 폭·크기·개수가 작아졌다. 개정 전에도 그 대상이 있었다",
    "다른 값": "커지지도 작아지지도 않고 다른 값이 됐다",
    "새로 생겼다": "개정 전 조항에 그 대상이 아예 없었다",
    "없어졌다": "개정 후 조항에 그 대상이 남지 않았다",
}


def call(url: str, api_key: str, prompt: str, temperature: float, timeout: int) -> str:
    # request_payload는 solar_request.json을 마지막에 덮어쓰므로 온도가 고정된다.
    # 생성과 검증이 다른 온도를 써야 하니 페이로드를 받은 뒤에 다시 덮는다.
    payload = solar.request_payload(prompt)
    payload["temperature"] = temperature
    response = solar.call_solar(url, api_key, payload, timeout)
    raw, _ = solar.extract_message(response)
    return raw


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
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def changed_ratio(before: str, after: str) -> float:
    """두 조항이 서로 얼마나 다른가. 국소 수정 여부(BM4)를 재는 데 쓴다.

    보존된 글자를 원문 길이로 나누면 안 된다. 그러면 **삽입만 하는 개정이 0으로 나온다**
    -- 원문이 통째로 살아 있기 때문이다. `전문기관의 장은` -> `전문기관의 장과
    총괄담당관은`이 정확히 그 경우이고, 국소 수정이긴 하나 0은 아니다.

    `SequenceMatcher.ratio()`는 양쪽 길이의 합으로 나누므로 삽입과 삭제를 둘 다 센다.
    그 여집합을 쓴다.
    """
    import difflib
    return round(
        1 - difflib.SequenceMatcher(None, before, after, autojunk=False).ratio(), 3)


def score_generation(item: dict, raw: str) -> dict:
    """A를 부르기 전에 매길 수 있는 것들. BM1~BM4."""
    result = {k: 0 for k in ("BM1", "BM2", "BM3", "BM4")}
    parsed = parse_output(raw)
    if parsed is None:
        return {**result, "after": None, "changed_ratio": None}
    after = str(parsed.get("after") or "").strip()
    if not after:
        return {**result, "after": None, "changed_ratio": None}
    result["BM1"] = 1

    before = item["clause"]
    # BM2 -- 실제로 달라졌나. 글자가 다른 것만으로는 부족하다. classify_diff의 정규화
    # 규칙에 걸리면 서식 차이일 뿐이라 실질 변경이 아니다(`실질 변경 없음` negative로
    # 따로 쓸 수는 있으나 지시한 변경을 넣은 것은 아니다).
    result["BM2"] = int(classify_diff.classify(before, after) is None)

    # BM3 -- 분류 어휘가 본문에 새어 들어가면 왕복 검증이 무의미해진다.
    leaked = [w for w in (item["instruct"]["대상"], item["instruct"]["방향"]) if w in after]
    result["BM3"] = int(not leaked)

    # BM4 -- 국소 수정. 문턱값은 아직 근거가 없다(`rubric.md`). 지금은 재서 기록만 하고,
    # 라운드가 쌓이면 통과·실패 분포를 보고 정한다.
    ratio = changed_ratio(before, after)
    result["BM4"] = int(ratio <= 0.5)
    return {**result, "after": after, "changed_ratio": ratio, "leaked": leaked}


def round_trip(url: str, api_key: str, timeout: int, judge: Template,
               item: dict, after: str) -> dict:
    """B의 개정문을 A에게 blind로 넣고 지시받은 라벨이 나오는지 본다. BM5."""
    prompt = judge.substitute(
        before_id=f'{item["block_id"]}(원문)', before=item["clause"],
        after_id=f'{item["block_id"]}(개정)', after=after, given_labels="- (없음)")
    raw = call(url, api_key, prompt, JUDGE_TEMPERATURE, timeout)
    parsed = parse_output(raw)
    labels = (parsed or {}).get("labels") or []
    got = {(str(x.get("대상")), str(x.get("방향"))) for x in labels if isinstance(x, dict)}
    want = (item["instruct"]["대상"], item["instruct"]["방향"])
    return {
        # 완전일치가 아니라 포함으로 본다. 한 군데를 고쳐도 두 성격을 함께 띠는 일이
        # 흔하므로, A가 라벨을 더 붙이는 것은 벌하지 않는다(`rubric.md`).
        "BM5": int(want in got),
        # BM5a -- 대상만 본다. 대상을 짚는 일과 방향을 정하는 일은 다른 능력인데 BM5가
        # 한 칸에 뭉쳐 재고 있었다. 2026-08-12 재판정에서 판정 모델을 바꾸자 대상 일치는
        # 68.4%에서 73.7%로 올랐는데 BM5는 54.4%에서 52.6%로 내렸다 -- 둘이 서로 지워
        # "변화 없음"으로 보였다. 나눠 두면 프롬프트를 고쳤을 때 어느 쪽이 움직였는지
        # 보이고, 대상이 맞고 방향만 다른 건은 A의 라벨로 갈아 끼워도 안전하다.
        "BM5a": int(want[0] in {target for target, _ in got}),
        "judge_judgement": (parsed or {}).get("judgement"),
        "judge_labels": labels,
        "judge_raw": raw,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", required=True, nargs="+", help="prompts/<이 값>.txt")
    ap.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    evalset = solar.read_json(HERE / "evalset.json")
    items = [x for x in evalset["items"]
             if args.split == "all" or x["split"] == args.split]
    if not items:
        raise SystemExit(f"{args.split}에 해당하는 항목이 없습니다")
    judge = Template((INTERPRET / "prompts" / f"{JUDGE_PROMPT}.txt").read_text(encoding="utf-8"))

    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))
    keys = ("BM1", "BM2", "BM3", "BM4", "BM5")

    for name in args.prompt:
        template = Template((HERE / "prompts" / f"{name}.txt").read_text(encoding="utf-8"))
        out_dir = HERE / "runs" / f"{solar.timestamp()}__{name}__{args.split}"
        out_dir.mkdir(parents=True, exist_ok=True)
        records, failures = [], 0
        print(f"\n프롬프트 {name} · {args.split} {len(items)}건 × {args.repeat}회"
              f"  (판정 = 역할 A {JUDGE_PROMPT})")

        for item in items:
            target, direction = item["instruct"]["대상"], item["instruct"]["방향"]
            prompt = template.substitute(
                clause=item["clause"], target=target, direction=direction,
                target_def=TARGET_DEF[target], direction_def=DIRECTION_DEF[direction])
            marks, afters = [], []
            for turn in range(1, args.repeat + 1):
                try:
                    raw = call(url, api_key, prompt, GENERATE_TEMPERATURE, timeout)
                except Exception as error:
                    failures += 1
                    marks.append("x")
                    records.append({"item": item["id"], "turn": turn,
                                    "error": solar.safe_error(error)})
                    continue
                marked = score_generation(item, raw)
                after = marked.pop("after")
                trip = {"BM5": 0, "BM5a": 0, "judge_judgement": None,
                        "judge_labels": None, "judge_raw": None}
                # 개정문이 안 나왔거나 서식 차이뿐이면 A를 부를 이유가 없다.
                if after and marked["BM2"]:
                    try:
                        trip = round_trip(url, api_key, timeout, judge, item, after)
                    except Exception as error:
                        failures += 1
                        trip["judge_error"] = solar.safe_error(error)
                scores = {k: marked.get(k, 0) for k in ("BM1", "BM2", "BM3", "BM4")}
                scores["BM5"] = trip.pop("BM5")
                scores["BM5a"] = trip.pop("BM5a")
                if after:
                    afters.append(after)
                records.append({"item": item["id"], "turn": turn, "scores": scores,
                                "instruct": item["instruct"], "after": after,
                                "changed_ratio": marked.get("changed_ratio"),
                                "leaked": marked.get("leaked"), **trip, "raw": raw})
                # BM5a는 게이트가 아니라 BM5를 갈라 보는 칸이므로 합계에 넣지 않는다.
                marks.append(str(sum(scores[k] for k in keys)))
            # BM6은 회차끼리 비교해야 나오므로 항목이 끝난 뒤에 매긴다.
            distinct = len(set(afters))
            for record in records[-args.repeat:]:
                if "scores" in record:
                    record["scores"]["BM6"] = int(distinct == len(afters) and len(afters) > 1)
            print(f"  {item['id']:<24} ({target}, {direction})"
                  f"  M점수 {' '.join(marks)} / {len(keys)}   서로 다른 개정문 {distinct}/{len(afters)}")

        graded = [r for r in records if "scores" in r]
        all_keys = keys + ("BM5a", "BM6")
        totals = {k: sum(r["scores"].get(k, 0) for r in graded) for k in all_keys}
        summary = {
            "prompt": name, "judge_prompt": JUDGE_PROMPT, "split": args.split,
            "repeat": args.repeat, "calls": len(records), "failures": failures,
            "generate_temperature": GENERATE_TEMPERATURE,
            "judge_temperature": JUDGE_TEMPERATURE,
            "BM_rates": {k: round(v / len(graded), 3) for k, v in totals.items()} if graded else {},
        }
        solar.write_json(out_dir / "summary.json", summary)
        solar.write_json(out_dir / "records.json", records)
        print()
        for key, rate in summary["BM_rates"].items():
            print(f"  {key} {rate:>6.1%}")
        print(f"  실패 {failures}건    저장: {out_dir.relative_to(REPOSITORY_DIR)}")
    print("\nH1(개정문다움)은 records.json의 after를 읽고 사람이 매깁니다.")


if __name__ == "__main__":
    main()
