"""Turn a source document into a numbered list of text blocks.

One extractor per file format, because each format marks a paragraph
differently. The output is deliberately plain -- a list of `(id, text)` pairs --
so that everything downstream compares text and nothing downstream has to know
whether the document arrived as HWPX, HTML or plain text.

Collection format priority is HWPX > HWP (converted) > PDF. HWPX writes the
document structure out as tags, so paragraphs and table cells can be read
straight off. PDF records a printed page as characters at coordinates and has
no notion of a paragraph at all, so a PDF-only pair is flagged in its manifest
rather than extracted here. HWP 5.0 has no extractor yet; see `docs/TODO.md`.

The block id (`privacyOld14-B0007`) exists so that a label written elsewhere can
name the block it was written for. It is a position in *this extractor's*
output, not the article number printed in the document -- change the extractor
and the ids change with it.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

Block = tuple[str, str]  # (id, text)


# ------------------------------------------------------------------------ html

class _Text(HTMLParser):
    BREAK = {"p", "div", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BREAK or tag == "br":
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in self.BREAK:
            self.buf.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def _clean(lines) -> list[str]:
    out = [re.sub(r"\s+", " ", x).strip() for x in lines]
    return [x for x in out if x]


# ------------------------------------------------------------------------ hwpx

HWPX_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _paragraph_text(para) -> str:
    """Text of one <hp:p>, excluding paragraphs nested inside it.

    A table lives inside a paragraph (`hp:p > hp:tbl > hp:tr > hp:tc >
    hp:subList > hp:p`), so a plain descendant search would pull every cell
    into the paragraph that merely contains the table. Cell paragraphs are
    emitted separately, in document order, by the caller.

    Within one paragraph, text is split across `hp:run` elements whenever
    character formatting changes -- `제2조 (용어의 정의)` in bold and the
    `① ...` after it in regular weight are two runs of one sentence -- so the
    runs are concatenated rather than treated as separate blocks.
    """
    parts: list[str] = []

    def walk(node) -> None:
        for child in node:
            if child.tag == HWPX_NS + "p":
                continue  # belongs to a nested paragraph, not this one
            if child.tag == HWPX_NS + "t":
                parts.append("".join(child.itertext()))
            walk(child)

    walk(para)
    return "".join(parts)


# ----------------------------------------------------------------------- entry

def blocks(path: Path) -> list[str]:
    """Extract paragraph-level text blocks from hwpx, html or txt."""
    suffix = path.suffix.lower()
    if suffix == ".hwpx":
        out: list[str] = []
        with zipfile.ZipFile(path) as z:
            sections = sorted(
                n for n in z.namelist() if re.search(r"Contents/section\d+\.xml$", n)
            )
            for name in sections:
                root = ElementTree.fromstring(z.read(name))
                for para in root.iter(HWPX_NS + "p"):
                    out.append(_paragraph_text(para))
        return _clean(out)
    if suffix in (".html", ".htm"):
        parser = _Text()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        return _clean("".join(parser.buf).split("\n"))
    return _clean(path.read_text(encoding="utf-8", errors="replace").split("\n"))


# ------------------------------------------------------------------- block ids

def prefixes(before: Path, after: Path) -> tuple[str, str]:
    """Id prefixes for the two sides of one comparison.

    The file stem is used, so ids stay unique when the results of several pairs
    of one series (`privacyOld14` -> `privacyOld15`, `privacyOld15` ->
    `privacyOld16`, ...) are merged into a single labelling set. Two files with
    the same stem in different directories would collide, so those fall back to
    the side name.
    """
    if before.stem == after.stem:
        return "before", "after"
    return before.stem, after.stem


def indexed(path: Path, prefix: str) -> list[Block]:
    """Blocks of one document, each tagged with its 1-based position."""
    return [(f"{prefix}-B{i:04d}", text) for i, text in enumerate(blocks(path), 1)]


def source_info(path: Path, doc: list[Block]) -> dict:
    """What a result file needs to say about one input document.

    The digest is of the file as it was read, so a stored result can later be
    checked against the pair's `manifest.json` -- or against the file itself --
    to confirm which bytes it came from.
    """
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "blocks": len(doc),
        "id_prefix": doc[0][0].rsplit("-B", 1)[0] if doc else "",
    }
