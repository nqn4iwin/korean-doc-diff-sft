"""What a block contains, and therefore which mutation operators can apply to it.

`probes/mutate_probe/` showed that most failures were not model errors: 36 runs
returned only 21 blocks carrying the operator they were told to apply, and the
misses were mostly combinations with nowhere to land. `threshold_increased` was
aimed at a 대리인 clause holding no number at all, so the model either invented a
number or quietly did something else.

The fix is not to annotate every clause by hand. It is to ask what the clause
*contains* -- a number, a deadline, an actor, an enumeration, a proper name, a
duty -- and derive the applicable operators from that. A clause with no number
cannot have its threshold raised, whoever writes it.

Two kinds of operator, and the distinction is the point of this file:

  * A **slot operator** rewrites something the clause already has.
    `threshold_increased` needs a number, `deadline_changed` needs a time
    expression, `responsibility_shifted` needs an actor. No slot, no operator --
    these are the combinations that produced the 25~30% miss rate.
  * A **kind operator** adds to the clause or re-weights it, and needs only that
    the clause be a clause: `obligation_strengthened`, `verification_added`. It
    still needs a predicate to strengthen, but not a particular value.

A block that is a heading (`나) 구성`) or a table fragment has no predicate and
takes no operator at all. Roughly half of this corpus is that.

Detection is regex over surface forms taken from the corpus, not invented: the
amount forms are the ones that actually occur (`3천만원`, `1억원`), and article
citations (`제3조`) are excluded from 수치 because renumbering a citation is a
different edit from raising a threshold.

Usage:
    python source_data/block_components.py DOC [--json OUT] [--show COMPONENT]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from extract import indexed

# A citation, an item marker, or a bare year is a number that must NOT count as
# a threshold. They are masked out before the 수치 patterns run, so `요령 제12조
# 제5항에 따른다` reads as having no number -- which is correct, there is no
# threshold in it to raise.
MASK = re.compile(
    r"제\s*\d+\s*(?:조|항|호|목|장|절|편|관)(?:\s*의\s*\d+)?"
    r"|\d{4}\s*년도?"
    r"|www\.[\w.]+|https?://\S+"
)

COMPONENTS: dict[str, re.Pattern] = {
    # Quantities a revision can raise or lower. `00.00%` and the like are form
    # templates from 별지 서식, not thresholds, so a run of zeros is excluded.
    "수치": re.compile(
        r"(?<!0)\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만)?\s*원"
        r"|(?<!0)\d+(?:\.\d+)?\s*%"
        r"|\d+\s*(?:인|명|개|건|회|배|점|위|등급)"
        r"|\d+\s*분의\s*\d+"
    ),
    # Durations, deadlines and points in time. `이내/이상/이하/까지` carry the
    # deadline sense even without a bare number attached.
    "기한": re.compile(
        r"\d+\s*(?:일|주|개월|년|시간)"
        r"|\d{4}\s*[.년]\s*\d{1,2}\s*[.월]"
        r"|기한|기간|시행일|만료|매년|매월|분기|반기|즉시|지체\s*없이"
        r"|이내|이전|이후|까지"
    ),
    # Who acts or is answerable. Grounded in the actors this corpus names.
    "주체": re.compile(
        r"장관|위원장|위원회|평가단|전문기관|운영기관|운영사|전담기관|연계기관"
        r"|주관연구개발기관|연구개발기관|창업기업|투자자|신청자|담당자|간사"
        r"|협회|진흥원|중소벤처기업부|[가-힣]{2,}기관"
    ),
    # A list a revision can add an item to or strike one from.
    "열거": re.compile(
        r"다음\s*각\s*호|다음\s*각호|다음과\s*같|어느\s*하나에\s*해당"
        r"|각\s*목|아래와\s*같|다음의"
    ),
    # Named things that can be renamed. Quoted names, statutes, systems.
    "명칭": re.compile(
        r"[“”\"'‘’][^“”\"'‘’]{2,}[“”\"'‘’]"
        r"|「[^」]+」|『[^』]+』"
        r"|[가-힣A-Za-z]{2,}(?:시스템|사업|제도|사업단|센터|펀드|타운)"
    ),
    # A duty to strengthen, weaken, or hang a new verification step off.
    "의무": re.compile(
        r"하여야\s*한다|해야\s*한다|하여야\s*하며|한다\.?$|된다\.?$"
        r"|할\s*수\s*있다|할\s*수\s*없다|원칙으로\s*한다|아니\s*된다|안\s*된다"
        r"|금지|의무|책임|필요하다|본다\.?$"
    ),
}

# The strong duty forms. `할 수 있다` is a permission -- there is nothing in it
# to weaken, so obligation_weakened does not apply to it.
STRONG_DUTY = re.compile(
    r"하여야\s*한다|해야\s*한다|하여야\s*하며|원칙으로\s*한다"
    r"|아니\s*된다|안\s*된다|금지|의무"
)

# operator -> (kind, required components). "slot" means the component must be
# present because the operator rewrites it; "kind" means the operator adds to
# the clause and only needs it to be a clause.
OPERATORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "threshold_increased": ("slot", ("수치",)),
    "deadline_changed": ("slot", ("기한",)),
    "responsibility_shifted": ("slot", ("주체",)),
    "scope_expanded": ("slot", ("열거", "명칭", "주체")),
    "scope_reduced": ("slot", ("열거", "명칭", "주체")),
    "obligation_strengthened": ("kind", ("의무",)),
    "verification_added": ("kind", ("의무",)),
    "obligation_weakened": ("kind", ("강한의무",)),
}


def is_clause(text: str) -> bool:
    """Whether the block is something an operator could be applied to.

    A heading (`나) 구성`, `5) 제재처분평가단`) states a topic and has no
    predicate; there is no obligation in it to strengthen and no threshold to
    raise. Requiring a sentence-final predicate is what separates the two, and
    the length floor drops table fragments that end in a stray `한다`.
    """
    return len(text) >= 20 and bool(
        re.search(r"(?:다|음|함|됨|것)\.?$|한다\.?$|있다\.?$|없다\.?$", text))


def components(text: str) -> list[str]:
    masked = MASK.sub(" ", text)
    found = [name for name, pat in COMPONENTS.items() if pat.search(masked)]
    if "의무" in found and STRONG_DUTY.search(masked):
        found.append("강한의무")
    return found


def operators(present: list[str]) -> list[str]:
    have = set(present)
    return [
        name for name, (_, required) in OPERATORS.items()
        if have.intersection(required)
    ]


def analyse(doc: list[tuple[str, str]]) -> dict:
    clauses, headings = [], 0
    for block_id, text in doc:
        if not is_clause(text):
            headings += 1
            continue
        present = components(text)
        clauses.append({
            "id": block_id,
            "text": text,
            "components": present,
            "operators": operators(present),
        })
    comp_counts: Counter = Counter(c for b in clauses for c in b["components"])
    op_counts: Counter = Counter(o for b in clauses for o in b["operators"])
    return {
        "blocks": len(doc),
        "headings_or_fragments": headings,
        "clauses": len(clauses),
        "component_counts": dict(comp_counts.most_common()),
        "operator_counts": dict(op_counts.most_common()),
        "no_operator": sum(1 for b in clauses if not b["operators"]),
        "items": clauses,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("doc", type=Path)
    ap.add_argument("--json", type=Path, help="result path (default: DOC.components.json)")
    ap.add_argument("--show", help="print sample clauses carrying this component or operator")
    ap.add_argument("--samples", type=int, default=8)
    args = ap.parse_args()

    doc = indexed(args.doc, args.doc.stem)
    result = analyse(doc)
    total = result["clauses"]
    print(f"{args.doc.name}")
    print(f"  blocks            : {result['blocks']}")
    print(f"  headings/fragments: {result['headings_or_fragments']}")
    print(f"  clauses           : {total}")
    print("  components")
    for name, count in result["component_counts"].items():
        print(f"      {name:<10} {count:>5}  {count / total:6.1%}")
    print("  applicable operators")
    for name, count in result["operator_counts"].items():
        kind = OPERATORS[name][0]
        print(f"      {name:<26} {kind:<5} {count:>5}  {count / total:6.1%}")
    print(f"  clauses with no operator : {result['no_operator']}")

    if args.show:
        picked = [
            b for b in result["items"]
            if args.show in b["components"] or args.show in b["operators"]
        ]
        print(f"\n  samples for {args.show} ({len(picked)} clauses)")
        for b in picked[: args.samples]:
            print(f"    {b['id']} {b['text'][:100]}")
            print(f"      components={b['components']} operators={b['operators']}")

    out = args.json or args.doc.with_suffix(".components.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
