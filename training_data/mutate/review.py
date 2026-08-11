"""`generate.py`의 산출물을 사람이 채점할 수 있는 HTML 한 장으로 묶는다.

기계 게이트 BM1~BM7은 `generate.py`가 매기지만 **BH1(개정문다움)은 사람이 읽어야 한다.**
`rubric.md`가 BH1을 채점 항목으로 두고도 지금까지 아무도 안 매긴 이유가 도구가 없어서다.
`pairs.json`을 그대로 읽으면 한 건이 수십 줄이라 100건을 훑을 수 없다.

그래서 이 스크립트가 하는 일은 셋이다.

- **바뀐 곳만 눈에 띄게 한다.** 개정 전·후를 글자 단위로 비교해 지워진 곳과 들어간 곳에
  색을 입힌다. 변경 폭 중앙값이 0.074라 색이 없으면 어디가 바뀌었는지 못 찾는다.
- **역할 A의 해석을 접어 둔다.** BH1은 개정문만 보고 매기는 항목이라 먼저 보이면 안 된다.
  필요할 때만 펼친다.
- **점수를 `localStorage`에 남긴다.** 100건을 한 번에 앉아서 볼 수 없으므로, 창을 닫아도
  이어서 할 수 있어야 한다.

결과는 페이지 맨 아래에 탭 구분 표로 쌓인다. 그대로 복사해 집계하면 된다.

사용:
    python3 training_data/mutate/review.py <runs 디렉터리>
    python3 training_data/mutate/review.py <runs 디렉터리> --limit 160 --bucket all
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
from pathlib import Path

# 사람이 읽을 순서. 학습에 실제로 들어갈 것과 BM7이 짚어 확인이 필요한 것이 앞에 온다.
BUCKET_ORDER = ["학습 후보", "사람 확인 필요", "라벨 교체 후보", "negative", "폐기"]
DEFAULT_BUCKETS = ("학습 후보", "사람 확인 필요")


def diff_html(before: str, after: str) -> tuple[str, str]:
    """두 조항을 글자 단위로 비교해 바뀐 곳만 태그로 감싼다.

    `autojunk=False`는 `changed_ratio`를 재는 `run.py`와 같은 이유다 -- 자동 정크 판정이
    켜져 있으면 자주 나오는 글자를 비교에서 빼버려서, 조사가 반복되는 한국어 조항에서
    엉뚱한 구간이 같다고 나온다.
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    left, right = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        removed, added = html.escape(before[i1:i2]), html.escape(after[j1:j2])
        if tag == "equal":
            left.append(removed)
            right.append(added)
        elif tag == "delete":
            left.append(f"<del>{removed}</del>")
        elif tag == "insert":
            right.append(f"<ins>{added}</ins>")
        else:
            left.append(f"<del>{removed}</del>")
            right.append(f"<ins>{added}</ins>")
    return "".join(left), "".join(right)


def parse_judge(raw: str | None) -> dict:
    """역할 A의 원출력에서 JSON 하나를 꺼낸다. `run.py`의 `parse_output`과 같은 규칙이다."""
    if not raw:
        return {}
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned.split("\n", 1)[1] if cleaned.startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build(run_dir: Path, limit: int, buckets: tuple[str, ...]) -> tuple[str, int]:
    pairs = json.loads((run_dir / "pairs.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    # 개정문이 안 나온 건은 읽을 것이 없다.
    graded = [p for p in pairs if "scores" in p and p.get("after")]
    graded.sort(key=lambda p: (
        BUCKET_ORDER.index(p["bucket"]) if p["bucket"] in BUCKET_ORDER else len(BUCKET_ORDER),
        p["block_id"]))
    picked = [p for p in graded if p["bucket"] in buckets][:limit]
    if not picked:
        raise SystemExit(f"고를 항목이 없습니다. 버킷: {', '.join(buckets)}")

    items = []
    for index, pair in enumerate(picked):
        before_html, after_html = diff_html(pair["clause"], pair["after"])
        judge = parse_judge(pair.get("judge_raw"))
        items.append({
            "i": index,
            "id": pair["block_id"],
            "target": pair["instruct"]["대상"],
            "direction": pair["instruct"]["방향"],
            "bucket": pair["bucket"],
            "scores": pair["scores"],
            "ratio": pair.get("changed_ratio"),
            "notes": pair.get("inspect") or [],
            "beforeHtml": before_html,
            "afterHtml": after_html,
            "judgement": judge.get("judgement"),
            "labels": judge.get("labels") or [],
            "impacts": judge.get("impacts") or [],
            "directImpact": judge.get("direct_impact") or "",
        })

    payload = json.dumps({
        "run": run_dir.name,
        "doc": summary.get("document", ""),
        "prompt": summary.get("prompt"),
        "judge": summary.get("judge_prompt"),
        "items": items,
    }, ensure_ascii=False)
    return TEMPLATE.replace("__DATA__", payload), len(items)


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>역할 B 산출물 검수</title>
<style>
  :root{
    --bg:#f6f7f9; --card:#fff; --ink:#16191d; --muted:#666e7a; --line:#dfe3e8;
    --del:#fdecec; --delink:#a02020; --ins:#e8f6ec; --insink:#12692e;
    --warn:#fff6e0; --warnline:#e0b34d; --accent:#2a5bd7;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.65 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
  header{position:sticky;top:0;z-index:10;background:var(--card);
         border-bottom:1px solid var(--line);padding:12px 20px;
         display:flex;gap:18px;align-items:center;flex-wrap:wrap}
  h1{font-size:15px;margin:0;font-weight:700}
  .meta{color:var(--muted);font-size:12.5px}
  .prog{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:700}
  button{font:inherit;padding:5px 12px;border:1px solid var(--line);background:#fff;
         border-radius:6px;cursor:pointer}
  button:hover{border-color:var(--accent);color:var(--accent)}
  main{max-width:1080px;margin:0 auto;padding:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;
        padding:16px 18px;margin-bottom:14px}
  .card.done{border-left:4px solid var(--insink)}
  .card.cur{box-shadow:0 0 0 2px var(--accent)}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
  .tag{font-size:12px;padding:2px 9px;border-radius:20px;background:#eef1f5;color:var(--muted)}
  .tag.inst{background:#e7edfb;color:var(--accent);font-weight:600}
  .tag.warn{background:var(--warn);color:#8a6100;border:1px solid var(--warnline)}
  .tag.bad{background:var(--del);color:var(--delink)}
  .num{color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums}
  .txt{font:14px/1.85 ui-monospace,"D2Coding",Consolas,monospace;
       white-space:pre-wrap;word-break:break-word;background:#fbfbfc;
       border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin:4px 0 10px}
  .lbl{font-size:12px;color:var(--muted);margin-bottom:2px}
  del{background:var(--del);color:var(--delink);text-decoration:line-through}
  ins{background:var(--ins);color:var(--insink);text-decoration:none;font-weight:600}
  details{margin:6px 0 10px}
  summary{cursor:pointer;color:var(--muted);font-size:13px}
  .judge{font-size:13.5px;background:#fbfbfc;border:1px solid var(--line);
         border-radius:6px;padding:10px 12px;margin-top:6px}
  .judge b{font-weight:600}
  .score{display:flex;gap:8px;align-items:center;flex-wrap:wrap;
         border-top:1px dashed var(--line);padding-top:12px;margin-top:4px}
  .score .g{display:flex;gap:4px}
  .score button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
  .score button.no.on{background:#a02020;border-color:#a02020}
  select,input[type=text]{font:inherit;padding:5px 8px;border:1px solid var(--line);
         border-radius:6px;background:#fff}
  input[type=text]{flex:1;min-width:200px}
  #out{width:100%;height:230px;font:12px/1.5 ui-monospace,monospace;margin-top:10px}
  .hint{color:var(--muted);font-size:12.5px}
  kbd{background:#eef1f5;border:1px solid var(--line);border-radius:4px;
      padding:1px 5px;font:12px ui-monospace,monospace}
</style>
</head>
<body>
<header>
  <h1>역할 B 산출물 검수</h1>
  <span class="meta" id="meta"></span>
  <span class="hint"><kbd>1</kbd> 통과 <kbd>0</kbd> 실패 <kbd>j</kbd>/<kbd>k</kbd> 이동</span>
  <button id="export">내보내기</button>
  <span class="prog" id="prog"></span>
</header>
<main>
  <div id="list"></div>
  <div class="card">
    <b>결과 내보내기</b>
    <div class="hint">아래 상자의 내용을 복사하면 된다. 점수는 브라우저에 자동
      저장되므로 창을 닫았다 열어도 남아 있다.</div>
    <textarea id="out" readonly></textarea>
    <div class="row" style="margin-top:8px">
      <button id="tsv">표로 보기</button>
      <button id="json">JSON으로 보기</button>
      <button id="reset">점수 전부 지우기</button>
    </div>
  </div>
</main>
<script>
const DATA = __DATA__;
const KEY = "role-b-review-" + DATA.run;
let marks = JSON.parse(localStorage.getItem(KEY) || "{}");
let cur = 0;
let mode = "tsv";

// BH1이 0일 때 무엇이 문제였는지. `CHANGELOG.md`의 사람 검수에서 실제로 나온 종류다.
const PROBLEM = ["", "비문", "지어낸 사실", "지시 초과", "라벨 의심", "문체 안 맞음", "기타"];

document.getElementById("meta").textContent =
  DATA.doc.split("/").pop() + " · 역할 B " + DATA.prompt + " · 판정 역할 A " + DATA.judge;

function esc(s){
  return (s == null ? "" : String(s)).replace(/[&<>]/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}
// 속성값에 들어가는 문자열은 따옴표까지 막아야 한다. 메모에 " 를 치면 태그가 깨진다.
function attr(s){ return esc(s).replace(/"/g, "&quot;"); }

function render(){
  document.getElementById("list").innerHTML = DATA.items.map(it => {
    const m = marks[it.id] || {};
    const gates = ["BM1","BM2","BM3","BM4","BM5"].map(k =>
      `<span class="tag ${it.scores[k] ? "" : "bad"}">${k} ${it.scores[k] ? 1 : 0}</span>`).join("");
    const notes = it.notes.length
      ? `<div class="row">${it.notes.map(n => `<span class="tag warn">${esc(n)}</span>`).join("")}</div>`
      : "";
    const labels = it.labels.map(l =>
      `<div>· <b>(${esc(l["대상"])}, ${esc(l["방향"])})</b> — ${esc(l["근거"])}</div>`).join("");
    const impacts = it.impacts.map(x =>
      `<div>· <b>${esc(x["주체"])}</b> — ${esc(x["영향"])}</div>`).join("");
    return `
    <div class="card ${m.h1 !== undefined ? "done" : ""} ${it.i === cur ? "cur" : ""}" id="c${it.i}">
      <div class="row">
        <span class="num">#${it.i + 1}</span>
        <span class="tag inst">(${esc(it.target)}, ${esc(it.direction)})</span>
        <span class="tag">${esc(it.bucket)}</span>
        ${gates}
        <span class="tag ${it.scores.BM7 ? "" : "warn"}">BM7 ${it.scores.BM7 ? 1 : 0}</span>
        <span class="num">변경폭 ${it.ratio}</span>
        <span class="num">${esc(it.id)}</span>
      </div>
      ${notes}
      <div class="lbl">개정 전</div><div class="txt">${it.beforeHtml}</div>
      <div class="lbl">개정 후</div><div class="txt">${it.afterHtml}</div>
      <details>
        <summary>역할 A의 해석 보기</summary>
        <div class="judge">
          <div><b>judgement</b> ${esc(it.judgement)}</div>
          <div style="margin-top:6px"><b>labels</b>${labels || " —"}</div>
          <div style="margin-top:6px"><b>impacts</b>${impacts || " —"}</div>
          <div style="margin-top:6px"><b>direct_impact</b><br>${esc(it.directImpact)}</div>
        </div>
      </details>
      <div class="score">
        <span class="lbl" style="margin:0">BH1 개정문다움</span>
        <span class="g">
          <button class="yes ${m.h1 === 1 ? "on" : ""}" data-id="${attr(it.id)}" data-v="1">1 통과</button>
          <button class="no ${m.h1 === 0 ? "on" : ""}" data-id="${attr(it.id)}" data-v="0">0 실패</button>
        </span>
        <select data-id="${attr(it.id)}" class="prob">
          ${PROBLEM.map(p =>
            `<option value="${attr(p)}" ${m.problem === p ? "selected" : ""}>${esc(p) || "문제 유형 —"}</option>`
          ).join("")}
        </select>
        <input type="text" data-id="${attr(it.id)}" class="memo" placeholder="메모"
               value="${attr(m.memo || "")}">
      </div>
    </div>`;
  }).join("");

  const scored = Object.values(marks).filter(m => m.h1 !== undefined);
  const passed = scored.filter(m => m.h1 === 1).length;
  document.getElementById("prog").textContent =
    `채점 ${scored.length} / ${DATA.items.length}` +
    (scored.length ? `  ·  통과 ${passed} (${Math.round(passed / scored.length * 100)}%)` : "");
  dump();
}

function save(){ localStorage.setItem(KEY, JSON.stringify(marks)); }
function set(id, patch){ marks[id] = Object.assign({}, marks[id], patch); save(); render(); }
function goto(i){
  cur = Math.max(0, Math.min(DATA.items.length - 1, i));
  document.getElementById("c" + cur)?.scrollIntoView({block: "center", behavior: "smooth"});
}

document.addEventListener("click", e => {
  const button = e.target.closest("button[data-id]");
  if (!button) return;
  const item = DATA.items.find(x => x.id === button.dataset.id);
  set(button.dataset.id, {h1: Number(button.dataset.v)});
  goto(item.i + 1);
});
document.addEventListener("change", e => {
  if (e.target.classList.contains("prob")) set(e.target.dataset.id, {problem: e.target.value});
});
document.addEventListener("input", e => {
  // 메모는 글자마다 다시 그리면 포커스를 잃는다. 저장만 하고 화면은 그대로 둔다.
  if (!e.target.classList.contains("memo")) return;
  marks[e.target.dataset.id] =
    Object.assign({}, marks[e.target.dataset.id], {memo: e.target.value});
  save();
});
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === "1" || e.key === "0") {
    set(DATA.items[cur].id, {h1: Number(e.key)});
    goto(cur + 1);
  } else if (e.key === "j" || e.key === "k") {
    goto(cur + (e.key === "j" ? 1 : -1));
    render();
  }
});

function dump(){
  const rows = DATA.items.map(it => {
    const m = marks[it.id] || {};
    return {id: it.id, 대상: it.target, 방향: it.direction, bucket: it.bucket,
            BM5: it.scores.BM5, BM7: it.scores.BM7,
            BH1: m.h1 === undefined ? "" : m.h1,
            문제유형: m.problem || "", 메모: (m.memo || "").replace(/\t/g, " ")};
  });
  document.getElementById("out").value = mode === "json"
    ? JSON.stringify(rows, null, 1)
    : [Object.keys(rows[0]).join("\t")]
        .concat(rows.map(r => Object.values(r).join("\t"))).join("\n");
}
document.getElementById("tsv").onclick = () => { mode = "tsv"; dump(); };
document.getElementById("json").onclick = () => { mode = "json"; dump(); };
document.getElementById("export").onclick = () => {
  const out = document.getElementById("out");
  out.scrollIntoView({behavior: "smooth"});
  out.select();
};
document.getElementById("reset").onclick = () => {
  if (confirm("점수를 전부 지웁니다. 계속할까요?")) { marks = {}; save(); render(); }
};
render();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path, help="generate.py가 만든 runs/ 아래 디렉터리")
    ap.add_argument("--limit", type=int, default=100, help="읽을 건수 상한")
    ap.add_argument("--bucket", default=",".join(DEFAULT_BUCKETS),
                    help=f"쉼표로 구분. 기본값은 {', '.join(DEFAULT_BUCKETS)}. 전부 보려면 all")
    ap.add_argument("--out", type=Path, default=None,
                    help="저장 위치. 디렉터리를 주면 그 안에 <실행 이름>.html로 넣는다. "
                         "생략하면 실행 디렉터리 안의 review.html")
    args = ap.parse_args()

    buckets = (tuple(BUCKET_ORDER) if args.bucket == "all"
               else tuple(b.strip() for b in args.bucket.split(",") if b.strip()))
    page, count = build(args.run_dir, args.limit, buckets)

    # 채점 결과는 브라우저가 실행 이름으로 저장한다. 파일을 어디에 두든 같은 경로에서
    # 계속 열기만 하면 이어서 할 수 있다.
    if args.out is None:
        out = args.run_dir / "review.html"
    elif args.out.suffix == ".html":
        out = args.out
    else:
        out = args.out / f"{args.run_dir.name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"{count}건  저장: {out}")


if __name__ == "__main__":
    main()
