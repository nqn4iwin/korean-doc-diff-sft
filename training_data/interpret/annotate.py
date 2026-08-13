"""실제 pair의 실질 변경에 역할 A(홈즈)의 해석을 붙인다. `PLAN.md`가 A-2라 부르는 일이다.

`run.py`는 고정 평가 세트 9건으로 프롬프트를 깎는 도구다. 이쪽은 그렇게 깎은 프롬프트를
**`classify_diff.py`가 뽑아 둔 실질 변경 전체**에 적용한다. 산출은 학습 레코드가 된다 --
`학습데이터_생성_프로세스.md` 3-0절대로 학습의 정답은 역할 A의 해석이다.

**채점을 run.py에서 가져오지 않는다.** run.py의 `score()`는 `evalset.json`의 정답키
(`item["judgement"]`, `item["labels"]`, `reference_impacts`)를 전제한다. 원천 697건에는
사람이 붙인 정답이 없으므로 AM4·AM5·AM7은 여기서 잴 수 없다. **정답 없이 되는 것만
매긴다.**

    AM1 JSON 파싱 · AM2 어휘 준수 · AM3 중복 없음        그대로 된다
    AM6s · AM8s                                          자기 일관성으로 바꿔 매긴다
    restatement_ratio                                    그대로 된다

`s`가 붙은 둘은 정답키 대신 **모델 자기 판정**을 기준으로 삼는다. AM6은 "스스로 negative
라 해놓고 impacts를 채웠나", AM8은 "자기가 낸 주체를 자기 문장에서 흘렸나"를 본다.
rubric.md의 AM6·AM8과 이름이 다른 이유가 이것이다 -- **같은 잣대가 아니므로 평가 세트의
값과 나란히 놓으면 안 된다.**

**표본은 계열별로 뽑는다.** 697건의 61%가 처리방침 한 계열이라 앞에서부터 자르거나
무작위로 뽑으면 그 계열만 나온다. 계열을 돌아가며 하나씩 뽑고, 계열 안에서는 문서
전체에 퍼지도록 간격을 두고 고른다 -- 앞에서부터 자르면 문서 앞머리의 표제부·날짜만
걸린다.

**입력은 블록쌍만 준다.** 상위 제목이나 인접 조항을 붙이는 것은 모델이 받는 정보를
바꾸는 major 판올림이라 별도 라운드로 남아 있다. v2.2를 잰 조건을 그대로 유지한다.

사용:
    python training_data/interpret/annotate.py --prompt v2.2 --limit 100 --dry-run
    python training_data/interpret/annotate.py --prompt v2.2 --limit 100 --concurrency 16
    python training_data/interpret/annotate.py --prompt v2.2 --limit 0   # 0 = 전체
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from string import Template

REPOSITORY_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_DIR))

import solar  # noqa: E402

# 스크립트를 직접 실행하면 이 폴더가 sys.path 맨 앞에 오므로 그대로 가져온다.
# 파싱과 어휘 목록을 두 벌 두면 한쪽만 고쳐지는 일이 생긴다.
import run as _run  # noqa: E402

HERE = Path(__file__).resolve().parent
COLLECTION_DIR = REPOSITORY_DIR / "data" / "raw_collection"

# 판정은 흔들리면 안 된다(`학습데이터_생성_프로세스.md` 3-2절). solar_request.json이
# 온도를 고정하므로 페이로드를 받은 뒤 덮어쓴다 -- mutate/run.py의 call()과 같은 이유다.
INTERPRET_TEMPERATURE = 0.2


# ------------------------------------------------------------------ 원천 읽기

def load_items() -> list[dict]:
    """`classify.json` 23개에서 실질 변경을 꺼낸다. 묶음 하나가 1건이다.

    한 묶음은 같은 치환이 일어난 블록들을 모은 것이라 어느 블록을 보내도 치환은 같다.
    대표로 첫 블록을 보내고 묶인 개수는 `group_size`에 남긴다.
    """
    items = []
    for path in sorted(COLLECTION_DIR.glob("**/*.classify.json")):
        series = path.relative_to(COLLECTION_DIR).parts[0]
        data = solar.read_json(path)
        for order, group in enumerate(data["real_change"]["items"]):
            blocks = group["blocks"]
            if not blocks:
                continue
            head = blocks[0]
            items.append({
                "id": f"{series}:{head['before_id']}",
                "series": series,
                "pair": path.name,
                "before_id": head["before_id"], "before": head["before"],
                "after_id": head["after_id"], "after": head["after"],
                "group_size": len(blocks),
                "substitutions": group.get("substitutions", []),
                "order": order,
            })
    return items


def spread(pool: list[dict], count: int) -> list[dict]:
    """한 계열에서 `count`건을 문서 전체에 퍼지도록 고른다.

    앞에서부터 자르면 안 된다. 블록은 문서 순서대로 들어 있고 문서 앞머리에는
    제·개정일자와 표제부가 몰려 있어, 앞 30건을 뽑으면 30건이 전부 날짜가 된다.
    """
    if count >= len(pool):
        return list(pool)
    return [pool[(i * len(pool)) // count] for i in range(count)]


def sample(items: list[dict], limit: int) -> list[dict]:
    """계열을 돌아가며 하나씩 뽑는다. 계열 수가 적은 쪽이 먼저 바닥난다."""
    by_series: dict[str, list[dict]] = {}
    for item in items:
        by_series.setdefault(item["series"], []).append(item)
    if limit <= 0 or limit >= len(items):
        return items

    # 계열마다 몇 건을 가져갈지 먼저 정한다. 한 바퀴에 하나씩 배분하므로 작은 계열이
    # 먼저 차고, 남는 몫이 큰 계열로 흘러간다.
    quota = {name: 0 for name in by_series}
    while sum(quota.values()) < limit:
        moved = False
        for name, pool in by_series.items():
            if sum(quota.values()) >= limit:
                break
            if quota[name] < len(pool):
                quota[name] += 1
                moved = True
        if not moved:
            break

    picked = [x for name, pool in by_series.items() for x in spread(pool, quota[name])]
    return sorted(picked, key=lambda x: (x["series"], x["order"]))


# -------------------------------------------------------------------- 채점

def score_blind(raw: str) -> dict:
    """정답키 없이 되는 것만 매긴다. AM4·AM5·AM7은 사람 라벨이 있어야 하므로 없다."""
    result = {"AM1": 0, "AM2": 0, "AM3": 0, "AM6s": 0, "AM8s": 0}
    parsed = _run.parse_output(raw)
    if parsed is None:
        return {**result, "parsed": None}
    result["AM1"] = 1

    pairs = _run.label_pairs(parsed.get("labels", []))
    if pairs is None:
        return {**result, "parsed": parsed}
    result["AM2"] = int(all(t in _run.TARGETS and d in _run.DIRECTIONS for t, d in pairs))
    result["AM3"] = int(len(pairs) == len(set(pairs)))

    judgement = str(parsed.get("judgement", "")).strip()
    subjects = _run.impact_subjects(parsed.get("impacts"))
    sentence = str(parsed.get("direct_impact") or "")

    # AM6s -- 스스로 negative라 해놓고 impacts나 문장을 채웠으면 자기모순이다.
    if judgement == "negative":
        result["AM6s"] = int(not subjects and not sentence.strip())
    else:
        result["AM6s"] = 1

    # AM8s -- 자기가 낸 주체를 자기 문장에서 흘리지 않았나. positive인데 배열이 비면
    # 검사할 것이 없어 공짜 점수가 되므로 0으로 막는다(run.py의 AM8과 같은 이유).
    if judgement == "positive" and not subjects:
        result["AM8s"] = 0
    else:
        result["AM8s"] = int(all(_run.subject_survives(s, sentence)
                                 for s in subjects if s))
    return {**result, "parsed": parsed}


def quantiles(values: list[float]) -> dict[str, float]:
    """유사도 분포. 문턱값을 다시 그을 때 재실행 없이 어디를 그을지 보려는 것이다."""
    if not values:
        return {}
    ordered = sorted(values)
    return {f"p{p}": ordered[min(len(ordered) - 1, (p * len(ordered)) // 100)]
            for p in (10, 25, 50, 75, 90)}


def restatement_ratio(after: str, sentence: str) -> float | None:
    """해설이 개정문을 그대로 옮긴 것인지 보는 선별기. 합격 판정이 아니라 걸러내기다."""
    if not sentence.strip():
        return None
    return round(difflib.SequenceMatcher(
        None, sentence, after, autojunk=False).ratio(), 3)


# --------------------------------------------------------------------- 실행

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", default="v2.2", help="prompts/<이 값>.txt")
    ap.add_argument("--limit", type=int, default=100,
                    help="해석을 붙일 건수. 0이면 전체")
    ap.add_argument("--exclude-series", action="append", default=[],
                    help="평가용으로 빼둘 계열. 여러 번 줄 수 있다")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="동시에 띄울 요청 수. 한 건씩 보내면 서버가 논다")
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 표본 구성만 출력")
    args = ap.parse_args()

    items = load_items()
    if args.exclude_series:
        items = [x for x in items if x["series"] not in args.exclude_series]
    plan = sample(items, args.limit)

    print(f"실질 변경 {len(items)}건 중 {len(plan)}건에 해석을 붙입니다"
          f"{'  (평가용 제외: ' + ', '.join(args.exclude_series) + ')' if args.exclude_series else ''}")
    picked = Counter(x["series"] for x in plan)
    whole = Counter(x["series"] for x in items)
    print(f"  {'계열':<34}{'표본':>6}{'전체':>7}{'비중':>7}")
    for name, count in picked.most_common():
        print(f"  {name:<34}{count:>6}{whole[name]:>7}{count / len(plan):>6.0%}")
    if args.dry_run:
        print("\n--dry-run 이므로 호출하지 않았습니다.")
        return
    if not plan:
        raise SystemExit("붙일 것이 없습니다.")

    template = Template((HERE / "prompts" / f"{args.prompt}.txt").read_text(encoding="utf-8"))
    solar.load_env()
    url = solar.chat_completions_url(solar.require_env("SOLAR_BASE_URL"))
    api_key = os.environ.get("SOLAR_API_KEY", "")
    timeout = int(os.environ.get("SOLAR_TIMEOUT_SECONDS", "180"))

    out_dir = HERE / "runs" / f"{solar.timestamp()}__annotate__{args.prompt}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 무엇으로 뽑았는지를 통째로 남긴다. 모델 이름만으로는 부족하다 -- 2026-08-11 하루에
    # 조건이 세 번 바뀌었고(모델 교체, reasoning_effort 끔, 다시 켬), 그중 추론을 끈
    # 조건에서는 negative 판정이 24호출 전부 positive로 무너졌다. 어느 조건에서 뽑은
    # 데이터인지 못 가리면 산출물을 해석할 수 없다.
    sent = {k: v for k, v in solar.request_payload("").items() if k != "messages"}
    sent["temperature"] = INTERPRET_TEMPERATURE

    # 끝난 것부터 곧바로 한 줄씩 적는다. 697건이면 20분 넘게 도는데, 그동안 프로세스가
    # 죽으면(키 만료, 터미널 닫힘, 끊긴 연결) 마지막에 한꺼번에 쓰는 방식으로는 **한 건도
    # 안 남는다.** 이미 돈을 쓴 호출이라 그것부터 지켜야 한다. JSONL(한 줄에 JSON 하나)로
    # 두는 이유는 배열과 달리 닫는 괄호가 없어, 중간에 끊겨도 앞부분이 그대로 읽히기
    # 때문이다. 스레드가 여럿이므로 자물쇠로 줄이 섞이는 것을 막는다.
    stream = (out_dir / "records.jsonl").open("w", encoding="utf-8")
    stream_lock = threading.Lock()

    def emit(record: dict) -> dict:
        with stream_lock:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
        return record

    def work(numbered: tuple[int, dict]) -> dict:
        index, item = numbered
        # v2.2가 쓰는 자리는 넷뿐이다. given_labels는 v0.3 전용이라 여기서는 주지 않는다
        # -- 라벨을 알려주면 판정이 아니라 받아쓰기가 된다.
        prompt = template.substitute(
            before_id=item["before_id"], before=item["before"],
            after_id=item["after_id"], after=item["after"])
        payload = solar.request_payload(prompt)
        payload["temperature"] = INTERPRET_TEMPERATURE
        try:
            response = solar.call_solar(url, api_key, payload, timeout)
            raw, _ = solar.extract_message(response)
        except Exception as error:
            print(f"  [{index}/{len(plan)}] x 실패  {item['id']}")
            return emit({**item, "error": solar.safe_error(error)})

        marked = score_blind(raw)
        parsed = marked.pop("parsed") or {}
        sentence = parsed.get("direct_impact") or ""
        ratio = restatement_ratio(item["after"], sentence)
        judgement = str(parsed.get("judgement", "")).strip()
        print(f"  [{index}/{len(plan)}] {sum(marked.values())}/5  {judgement or '?':<9}"
              f" {item['id']}")
        return emit({**item, "judgement": judgement,
                     "labels": parsed.get("labels"), "impacts": parsed.get("impacts"),
                     "direct_impact": parsed.get("direct_impact"),
                     "scores": marked, "restatement_ratio": ratio,
                     # True면 개정문을 그대로 옮긴 것에 가까워 사람이 읽기 전에 걸러낸다.
                     "ah1_screen": bool(ratio is not None
                                        and ratio >= _run.RESTATEMENT_THRESHOLD),
                     "raw": raw})

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            records = list(pool.map(work, enumerate(plan, 1)))
    finally:
        stream.close()

    graded = [r for r in records if "scores" in r]
    keys = ("AM1", "AM2", "AM3", "AM6s", "AM8s")
    verdicts = Counter(r["judgement"] or "(파싱 실패)" for r in graded)
    summary = {
        "prompt": args.prompt,
        "request": sent,
        "population": len(items), "planned": len(plan),
        "annotated": len(graded), "failures": len(records) - len(graded),
        "excluded_series": args.exclude_series,
        "concurrency": args.concurrency,
        "series": dict(picked),
        "judgements": dict(verdicts),
        "AM_rates": {k: round(sum(r["scores"][k] for r in graded) / len(graded), 3)
                     for k in keys} if graded else {},
        "ah1_screened_out": sum(1 for r in graded if r["ah1_screen"]),
        "restatement_threshold": _run.RESTATEMENT_THRESHOLD,
        # 문턱값 0.60은 18호출에 맞춘 값이라 근거가 약하고, 짧은 블록에서 구조적으로
        # 오탐이 난다 -- 프롬프트가 "주체는 원문의 말을 그대로 쓰라"고 시키므로 시킨
        # 대로 할수록 원문과 닮는다. 문턱을 다시 그으려면 분포가 있어야 하므로,
        # 원값은 레코드에 그대로 두고 여기에 분위수만 옮겨 둔다.
        "restatement_quantiles": quantiles(
            [r["restatement_ratio"] for r in graded if r["restatement_ratio"] is not None]),
    }
    solar.write_json(out_dir / "summary.json", summary)
    solar.write_json(out_dir / "records.json", records)

    print()
    for key, rate in summary["AM_rates"].items():
        print(f"  {key} {rate:>6.1%}")
    print(f"  실패 {summary['failures']}건")
    print()
    for verdict, count in verdicts.most_common():
        print(f"  {verdict:<14} {count}건")
    positives = verdicts.get("positive", 0)
    if graded:
        print(f"\n  학습 레코드가 될 수 있는 것: {positives}건"
              f"  (해석을 붙인 {len(graded)}건의 {positives / len(graded):.0%})")
    print(f"\n저장: {out_dir.relative_to(REPOSITORY_DIR)}")
    print("AM4·AM5·AM7은 사람 라벨이 있어야 잽니다. records.json을 읽고 붙이세요.")


if __name__ == "__main__":
    main()
