"""Local PDF text extraction using PyMuPDF (fitz).

100% offline — no OCR service, no cloud. We pull raw text per page plus a
"head" slice (first pages) that's enough for metadata extraction, and try to
isolate the references section for citation parsing.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

log = logging.getLogger("synapse.pdf")

# A references heading, allowing for how PDFs actually render one:
#   "REFERENCES"      "5  References"      "R E F E R E N C E S"    "References:"
# The letter-spaced form is common in two-column papers where the extractor
# inserts a space between every glyph.
_REFERENCES_HEADING = re.compile(
    r"^\s*(?:\d+\.?\s*)?"
    r"(r\s?e\s?f\s?e\s?r\s?e\s?n\s?c\s?e\s?s"
    r"|b\s?i\s?b\s?l\s?i\s?o\s?g\s?r\s?a\s?p\s?h\s?y"
    r"|works\s+cited)"
    r"\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_text(path: str | Path, max_pages: int | None = None) -> str:
    """Return the full (or first max_pages) plain text of a PDF."""
    text_parts: list[str] = []
    with fitz.open(str(path)) as doc:
        pages = doc if max_pages is None else (doc[i] for i in range(min(max_pages, doc.page_count)))
        for page in pages:
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts)


def extract_head(path: str | Path, pages: int = 2) -> str:
    """First `pages` pages — enough for title/authors/abstract extraction."""
    return extract_text(path, max_pages=pages)


# A paper puts its title, authors and abstract on page 1. A book opens with a
# cover, a half-title and a blank verso, so two pages of it can be almost empty
# — which is how an empty prompt reached the model and came back with a
# confidently wrong title. Read on until there's enough to work with.
HEAD_MIN_CHARS = 400
HEAD_MAX_PAGES = 12


def extract_head_adaptive(path: str | Path, min_chars: int = HEAD_MIN_CHARS,
                          max_pages: int = HEAD_MAX_PAGES) -> tuple[str, int]:
    """Read pages until `min_chars` of text is found. Returns (text, pages_read).

    Stops as soon as it has enough, so a normal paper still costs one page.
    """
    parts: list[str] = []
    total = 0
    read = 0
    with fitz.open(str(path)) as doc:
        for i in range(min(max_pages, doc.page_count)):
            t = doc[i].get_text("text")
            parts.append(t)
            total += len(t.strip())
            read = i + 1
            if total >= min_chars:
                break
    return "\n".join(parts), read


def has_text_layer(path: str | Path, probe_pages: int = 30) -> bool:
    """Whether the PDF carries selectable text at all.

    A scanned book is a stack of page images: every extractor returns "" and no
    amount of re-reading helps — it needs OCR, which this app deliberately does
    not do. Worth knowing up front so we can say so instead of guessing.
    """
    with fitz.open(str(path)) as doc:
        n = doc.page_count
        # Sample across the document — a scan can still have a text cover page.
        idx = range(n) if n <= probe_pages else \
            [int(i * (n - 1) / (probe_pages - 1)) for i in range(probe_pages)]
        for i in idx:
            if len(doc[i].get_text("text").strip()) >= 50:
                return True
    return False


def page_count(path: str | Path) -> int:
    with fitz.open(str(path)) as doc:
        return doc.page_count


# References live at the end, so only the tail is read. Without this a scan of a
# 1,665-page textbook parsed 2.1 million characters to find a section that was
# always in the last few pages.
REFS_TAIL_PAGES = 40


def extract_tail(path: str | Path, pages: int = REFS_TAIL_PAGES) -> str:
    """Last `pages` pages of a PDF (the whole thing if it's shorter)."""
    with fitz.open(str(path)) as doc:
        start = max(0, doc.page_count - pages)
        return "\n".join(doc[i].get_text("text") for i in range(start, doc.page_count))


def extract_references_section(path: str | Path, tail_pages: int = REFS_TAIL_PAGES) -> str:
    """Best-effort slice of the references/bibliography section.

    Heuristic: within the last `tail_pages` pages, find the last
    'References'/'Bibliography' heading and return everything after it. Returns
    "" if no such heading is found.
    """
    tail = extract_tail(path, tail_pages)
    matches = list(_REFERENCES_HEADING.finditer(tail))
    if not matches:
        return ""
    start = matches[-1].end()
    return tail[start:].strip()
