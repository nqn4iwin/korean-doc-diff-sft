"""Block-level diff for a document pair, with mechanical `no real change` detection.

Each normalization rule collapses one kind of non-semantic difference. If a
before/after block pair becomes identical under rule R, the difference *is* R --
no model judgement needed. Blocks that survive every rule are real-change
candidates.

Two findings drove the design:

  * Region-level classification does not work. difflib groups adjacent differing
    blocks into one opcode, so a real change and the page renumbering it caused
    land in the same region. Blocks inside a region are realigned by similarity
    before classification.
  * Rule order matters. Stripping whitespace first breaks the item-marker
    pattern (`바. 1억원` -> `바.1억원`), so RULES order is significant.

Counting rule, one item each for:
  * every no-real-change rule group (article renumbering across a document is
    one item, not fourteen),
  * every group of real-change blocks that share an identical substitution (a
    system renamed in twelve places is one item, not twelve),
  * every added block and every deleted block.

Every block carries an id (`privacyOld14-B0007`) so a label written elsewhere
can point back at the block it was written for, and every classified block --
including the mechanical `no real change` ones -- keeps its source text. The
result is always written to a file: without it the counts cannot be audited.

Usage:
    python source_data/classify_diff.py BEFORE AFTER [--json OUT] [--show N]

Reading the documents is `extract.py`'s job; this file only compares what it
returns, so the formats supported are whatever that module supports.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import Counter
from pathlib import Path

from extract import Block, indexed, prefixes, source_info

CIRCLED = "".join(chr(0x2460 + i) for i in range(20))  # (1)..(20)
HANGUL_ITEM = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"


def _reference(text: str) -> str:
    """Normalize a pointer to another item *inside the sentence*.

    The `항목기호` rule only touches the marker a block begins with. When an
    article is inserted, every sentence that cites a later one shifts too
    (`이 지침 9. 마.` -> `9. 라.`), and those citations sit mid-sentence.

    The range form must be handled before the single form, or `상기 ①~⑤항`
    loses its left endpoint to the single rule and the range never matches.
    """
    text = re.sub(rf"[{CIRCLED}]\s*[∼~-]\s*[{CIRCLED}]", "@∼@", text)
    text = re.sub(
        rf"(상기|위|앞)\s*(?:[{HANGUL_ITEM}]\)|[{CIRCLED}]|\d{{1,2}}\))", r"\1@", text)
    return re.sub(rf"(?<=\d)\s*\.\s*[{HANGUL_ITEM}]\s*\.", ".@.", text)

# Order is significant: whitespace removal must come after any rule whose
# pattern depends on spacing.
RULES: list[tuple[str, object]] = [
    # Anchored to the start of the block, so only a heading's own number is
    # normalized. An unanchored rule also rewrote citations inside a sentence,
    # and `「개인정보보호법」제25조에 따라` -> `제26조에 따라` -- a correction that
    # points the reader at a different statute -- silently became no change.
    ("조항번호", lambda s: re.sub(r"^(\s*제)\s*\d+\s*(조|항|호|목|장|절|편|관)", r"\1N\2", s)),
    # A circled marker needs no punctuation after it; a hangul or digit marker
    # does, or ordinary prose starting with a number would be swallowed.
    # A dash bullet must be followed by a space, or `-5%p` would lose its sign.
    # The marker is deleted rather than replaced by a placeholder: the same item
    # keeps appearing with the marker stripped when a numbered list becomes an
    # HTML bullet list, and `가. X` vs `X` has to reduce to no real change too.
    ("항목기호", lambda s: re.sub(
        rf"^\s*(?:[-•▪]\s+"
        rf"|\((?:[{HANGUL_ITEM}]|\d{{1,2}})\)"
        rf"|[{CIRCLED}]\s*[.)]?"
        rf"|(?:[{HANGUL_ITEM}]|\d{{1,2}})\s*[.)])\s*",
        "", s)),
    ("조항참조", lambda s: _reference(s)),
    ("붙임번호", lambda s: re.sub(
        r"(붙임|별표|별지|별첨|서식)\s*\d+(?:\s*-\s*\d+)?", r"\1N", s)),
    # Only a line that still has real text left over may lose a trailing page
    # number. A table cell holding just `17` must never normalize to nothing,
    # or a change from 17 to 14 silently becomes `no real change`.
    # The lookbehind forces the whole trailing run of digits to be taken; a
    # greedy head would otherwise leave all but the last digit in place, so
    # `...30` and `...29` would reduce to `...3` and `...2` and still differ.
    ("목차페이지", lambda s: re.sub(r"^(.*[가-힣A-Za-z].*?)\s*(?<!\d)\d{1,3}$", r"\1", s)),
    # Typographic quotes and brackets are deleted wherever they appear: none of
    # them mean anything but quoting. ASCII `<` `>` `[` `]` cannot be treated
    # that way -- `<` and `>` are also comparison operators, and deleting them
    # everywhere would turn `기준 < 10억` -> `기준 > 10억`, a reversed condition,
    # into no change. So an ASCII pair is only unwrapped when it encloses the
    # whole block, which is how a screen label is written (`<확인하기>`).
    ("따옴표기호", lambda s: re.sub(
        r"^\s*[<\[]\s*(.*?)\s*[>\]]\s*$", r"\1",
        re.sub(r"[“”\"‘’'「」『』｢｣〈〉《》]", "", s))),
    # `ㆍ` (U+318D, a hangul letter) is used as an interpunct by Korean word
    # processors, so `수집·이용` and `수집ㆍ이용` are the same text typed on two
    # different systems.
    ("가운뎃점", lambda s: re.sub(r"[·ㆍ․‧∙・]", "", s)),
    ("띄어쓰기", lambda s: re.sub(r"\s+", "", s)),
]
RULE_NAMES = [name for name, _ in RULES]


# ------------------------------------------------------------------ classification

def normalize(text: str, rules: set[str]) -> str:
    for name, fn in RULES:
        if name in rules:
            text = fn(text)
    return text


def classify(before: str, after: str) -> tuple[str, ...] | None:
    """Smallest rule set that makes the two sides identical, or None if real."""
    if before == after:
        return ()
    for name in RULE_NAMES:
        if normalize(before, {name}) == normalize(after, {name}):
            return (name,)
    for i in range(2, len(RULE_NAMES) + 1):
        subset = set(RULE_NAMES[:i])
        if normalize(before, subset) == normalize(after, subset):
            return tuple(sorted(subset))
    return None


def align(before: list[Block], after: list[Block], threshold: float = 0.55):
    """Greedy 1:1 block pairing inside one region; leftovers are add/delete.

    Both sides are `(id, text)` pairs; only the text takes part in the
    similarity comparison.
    """
    pairs, used = [], set()
    for b in before:
        best, chosen = threshold, None
        for j, a in enumerate(after):
            if j in used:
                continue
            ratio = difflib.SequenceMatcher(None, b[1], a[1], autojunk=False).ratio()
            if ratio > best:
                best, chosen = ratio, j
        if chosen is None:
            pairs.append((b, None))
        else:
            used.add(chosen)
            pairs.append((b, after[chosen]))
    pairs += [(None, a) for j, a in enumerate(after) if j not in used]
    return pairs


def signature(before: str, after: str) -> tuple[tuple[str, str], ...]:
    """The changed spans of one block pair, as an order-preserving key.

    Two block pairs with the same signature underwent the same substitution --
    a system renamed throughout a document, a contact name replaced everywhere.
    The counting rule folds them into one item.
    """
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return tuple(
        (before[i1:i2].strip(), after[j1:j2].strip())
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )


def compare(before: list[Block], after: list[Block]) -> dict:
    matcher = difflib.SequenceMatcher(
        None, [t for _, t in before], [t for _, t in after], autojunk=False)
    regions = [
        (before[i1:i2], after[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
    negatives: Counter = Counter()
    negative_items: list[dict] = []
    identical = 0
    real: dict[tuple, list[dict]] = {}
    added, deleted = [], []
    for bs, as_ in regions:
        for b, a in align(bs, as_):
            if b is None:
                added.append({"id": a[0], "text": a[1]})
                continue
            if a is None:
                deleted.append({"id": b[0], "text": b[1]})
                continue
            record = {
                "before_id": b[0], "after_id": a[0],
                "before": b[1], "after": a[1],
            }
            rules = classify(b[1], a[1])
            if rules is None:
                real.setdefault(signature(b[1], a[1]), []).append(record)
                continue
            if not rules:
                # Same text on both sides, swept into a region by a neighbour.
                # Counted only so the block totals add up.
                identical += 1
                continue
            negatives[rules] += 1
            negative_items.append({"rules": list(rules), **record})
    groups = sorted(real.items(), key=lambda kv: -len(kv[1]))
    real_groups = [
        {
            "substitutions": [list(pair) for pair in sig],
            "count": len(items),
            "blocks": items,
        }
        for sig, items in groups
    ]
    return {
        "regions": len(regions),
        "similarity": round(matcher.ratio(), 4),
        "no_real_change": {
            "blocks": sum(negatives.values()),
            "groups": {"+".join(k): v for k, v in negatives.most_common()},
            "identical": identical,
            # kept in full: these are the machine negatives the training set
            # needs, and the only way to check a rule did not swallow a real
            # change is to read the block it fired on
            "items": negative_items,
        },
        "added": added,
        "deleted": deleted,
        "real_change": {
            "blocks": sum(len(items) for _, items in groups),
            "groups": len(groups),
            "items": real_groups,
        },
        # counting rule: one item per no-real-change rule group, one per
        # identical-substitution group, one each for every added or deleted block
        "counted_items": (
            len(negatives) + len(groups) + len(added) + len(deleted)
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument(
        "--json", type=Path,
        help="result path (default: BEFORE__AFTER.classify.json beside AFTER)")
    ap.add_argument("--show", type=int, default=5, help="real-change samples to print")
    args = ap.parse_args()

    before_prefix, after_prefix = prefixes(args.before, args.after)
    before = indexed(args.before, before_prefix)
    after = indexed(args.after, after_prefix)
    result = {
        "schema_version": 2,
        "before": source_info(args.before, before),
        "after": source_info(args.after, after),
        **compare(before, after),
    }
    neg, pos = result["no_real_change"], result["real_change"]
    print(f"{args.before.name} -> {args.after.name}")
    print(f"  similarity        : {result['similarity']}")
    print(f"  changed regions   : {result['regions']}")
    print(f"  no real change    : {neg['blocks']} blocks -> {len(neg['groups'])} groups"
          f"  (+{neg['identical']} identical)")
    for name, count in neg["groups"].items():
        print(f"      {name:<34} {count:>4}")
    print(f"  added             : {len(result['added'])}")
    print(f"  deleted           : {len(result['deleted'])}")
    print(f"  real change       : {pos['blocks']} blocks -> {pos['groups']} groups")
    for group in pos["items"]:
        if group["count"] > 1:
            subs = " / ".join(f"{b} -> {a}" for b, a in group["substitutions"])
            print(f"      x{group['count']:<3} {subs[:70]}")
    print(f"  counted items     : {result['counted_items']}")
    for group in pos["items"][: args.show]:
        sample = group["blocks"][0]
        print(f"    {sample['before_id']} B: {sample['before'][:80]}")
        print(f"    {sample['after_id']} A: {sample['after'][:80]}")
    out = args.json or args.after.with_name(
        f"{args.before.stem}__{args.after.stem}.classify.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
