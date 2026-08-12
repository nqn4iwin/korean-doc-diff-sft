"""둘째 채점자에게 줄 **블라인드 문제지**를 만든다.

사람 검수가 1인이면 "이 항목이 나쁘다"와 "이 사람이 나쁘다고 봤다"를 가를 수 없다. 둘째
채점자를 붙여 일치도를 재면 갈린다. **다만 일치가 정답을 뜻하지는 않는다** -- 도메인
비전문가 둘이 일치하는 것은 "기준이 명확하다"는 뜻이지 "맞다"는 뜻이 아니다.

그래서 문제지에서 답이 될 만한 것을 전부 뺀다.

  뺀 것   지시 `(대상, 방향)` · 버킷 · BM 점수 · 역할 A의 해석 · 사람 채점
  남긴 것 개정 전 조항 · 개정 후 조항

**지시를 빼는 것이 핵심이다.** `동작유형`을 물으면서 지시를 보여주면 그것을 보고 맞히게
되어 무엇을 잰 것인지 알 수 없다. 왕복 검증이 역할 A에게 역할 B의 지시를 안 알려주는 것과
같은 이유다.

**같은 조항이 두 번 나오는 것을 흩는다.** 조항 하나에 지시를 둘 걸었으므로 같은 원문이
서로 다른 개정문 둘로 나온다. 나란히 놓이면 채점자가 둘을 비교해 지시를 역산한다. 씨앗을
고정해 섞는다.

**번호를 새로 매긴다.** `block_id`는 한 조항에 둘씩 붙어 있어 답을 맞대기에 모자란다.
`item_01` 식으로 다시 매기고, 되돌릴 열쇠는 문제지가 아니라 **별도 파일**에 쓴다.

사용:
    python3 training_data/mutate/blind_export.py RUN_DIR
    python3 training_data/mutate/blind_export.py RUN_DIR --out H_eval/blind.md
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent

MOVES = ["목록에 항목 추가", "절차 단계 추가", "주체 나란히 추가", "주체 교체",
         "값·기한 변경", "단서·예외 추가", "문구만 다듬음", "기타"]

HEADER = """# 개정문 채점

한국어 공공문서의 조항을 고쳐 쓴 것들입니다. 아래 {n}건 각각에 **두 가지를 판정하고 이유를**
적어 주세요. 원문과 개정문만 보고 판단하시면 됩니다. 문서 전체는 드리지 않습니다.

**앞뒤 항목을 참고하지 마세요.** 한 건씩 따로 봅니다.

## 물어보는 것

**(1) 무엇을 했나 (`동작유형`)** — 아래 목록에서 **하나만** 고릅니다. 잘했는지가 아니라
어떤 수를 뒀는지를 적는 칸입니다.

- `목록에 항목 추가` — `A와 B` → `A, B 및 C`처럼 나열에 항목을 끼워 넣음
- `절차 단계 추가` — 밟아야 할 단계 자체가 늘어남 (2단계이던 것이 3단계가 되는 식)
- `주체 나란히 추가` — 하던 주체는 그대로 두고 다른 주체를 나란히 붙임
- `주체 교체` — 하던 주체를 다른 주체로 바꿈
- `값·기한 변경` — 숫자나 날짜를 바꿈
- `단서·예외 추가` — `다만 …` `이 경우 …` 같은 단서나 예외를 덧붙임
- `문구만 다듬음` — 뜻이 사실상 안 바뀌고 표현만 손봄
- `기타` — 위 어디에도 안 맞음

**(2) 비합리 없음 (`BH1`)** — `1` 또는 `0`. **말이 되는지만 봅니다.**

`0`을 주는 경우는 이런 것들입니다.

- 조항 안에서 앞뒤가 어긋난다 (기준일은 바꾸고 마감일은 안 바꿔 계산이 안 맞는 식)
- 이미 성립한 것을 다시 하라고 한다
- 가리키는 것이 없다 (`필요한 요건`이 무엇인지 없이 갖추라고 하는 식)
- 주체와 대상이 뒤엉킨다 (연구단장이 연구단장의 권한을 정하는 식)
- 문장이 성립하지 않는다 (주어를 접속해 놓고 서술어가 안 받는 식)

**문체가 어색하다거나 실제로는 이렇게 안 쓸 것 같다는 이유로는 `0`을 주지 마세요.** 그
판단은 사람마다 갈려서 쓸 수 없다는 것이 실측으로 확인됐습니다. **말이 되면 `1`입니다.**

**(3) 이유** — 한 줄. **특히 `0`을 준 것에는 반드시 씁니다.** 숫자만 있으면 나중에 판정이
엇갈렸을 때 누가 맞는지 가릴 수 없습니다. `1`이어도 걸리는 데가 있으면 적어 주세요.

## 낼 것

아래 형식의 **탭으로 구분된 표**를 `result.tsv` 파일 하나로 내주세요. 다른 파일은 만들지
마세요.

```
item	동작유형	BH1	이유
item_01	주체 교체	1
item_02	단서·예외 추가	0	덧붙인 문장이 앞 문장과 겹쳐 같은 말을 두 번 한다
```

---
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    pairs = [p for p in json.loads((args.run_dir / "pairs.json").read_text(encoding="utf-8"))
             if p.get("after")]
    random.Random(args.seed).shuffle(pairs)

    out = args.out or (HERE / "H_eval" / f"blind__{args.run_dir.name}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    key_path = out.with_name(f"KEY__{out.stem}.tsv")

    body = [HEADER.format(n=len(pairs))]
    rows = []
    for index, pair in enumerate(pairs, 1):
        item = f"item_{index:02d}"
        body.append(f"### {item}\n\n**개정 전**\n\n{pair['clause']}\n\n"
                    f"**개정 후**\n\n{pair['after']}\n")
        rows.append({"item": item, "block_id": pair["block_id"],
                     "대상": pair["instruct"]["대상"], "방향": pair["instruct"]["방향"]})

    out.write_text("\n".join(body), encoding="utf-8")
    with key_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    print(f"문제지 {len(pairs)}건  ->  {out}")
    print(f"열쇠            ->  {key_path}")
    print("\n열쇠 파일은 채점자에게 주지 않습니다. 지시가 들어 있습니다.")


if __name__ == "__main__":
    main()
