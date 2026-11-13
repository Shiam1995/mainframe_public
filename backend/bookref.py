"""bookref — read a book session's chapter, pages and mode out of free text.

Book sessions were logged for months as one `purpose` string, by hand, with no
agreed shape. What is actually in the graph:

    Book [Page 1 - Page 17]
    Book Chapter 2 [Page 39 - Page 56]
    Book Chapter 2 [Page 39 implementation - Page 44]
    Book - [Chapter 2 Page 19 - Chapter 2 - Page 29]
    First chapter Page 0 - Page 23
    Introduction up to page 19
    Chapter 1 - Page 19 - Page 22 the top third
    Chapter 1 Page 22 - xxx?
    Chapter 1 - exercise 1.13 - ???
    Book - Chapter 1 - [Page 25 - Page - xxx]

So this parser is deliberately forgiving, and deliberately incomplete:

    A MISSING VALUE IS RETURNED AS None, NEVER GUESSED. "Page 22 - xxx?" means
    the stopping page was not written down. Inventing one (the next session's
    start, the chapter's last page) would put a number nobody recorded into a
    record whose whole purpose is to be shown to someone else. The end page
    stays open and the master record renders it "p.22 →".

`parse` is pure and does no I/O, so the backfill can be dry-run against every
session and read before anything is written. See routes/books.py.
"""
from __future__ import annotations

import re

# Words that stand in for a number nobody wrote down: xxx, xxxx, ???, tbc.
_UNKNOWN = re.compile(r"^(?:x+|\?+|tbc|tbd|-+)$", re.I)

# "Chapter 2", "chapter 1", "ch. 3", "ch3"
_CH_NUM = re.compile(r"\b(?:chapters?|ch)\.?\s*(\d+)", re.I)
# "Chapter 1 to 2", "chapters 1-2", "chapter 1 & 2" — a session that ran over a
# boundary. Kept as a range string rather than collapsed to its first chapter.
_CH_RANGE = re.compile(
    r"\b(?:chapters?|ch)\.?\s*(\d+)\s*(?:-|–|to|and|&|,)\s*(?:chapters?|ch)?\.?\s*(\d+)", re.I)
# Named chapters that carry no number. "First chapter" is chapter 1; an
# introduction is its own thing and is NOT renumbered into one.
_CH_WORD = [
    (re.compile(r"\b(?:the\s+)?first\s+chapter\b", re.I), "1"),
    (re.compile(r"\b(?:preface|foreword)\b", re.I), "front matter"),
    (re.compile(r"\b(?:introduction|intro)\b", re.I), "introduction"),
]

# Any "page 44", "p.44", "pg 44" — and the "xxx" placeholders alongside them,
# which have to be matched too or "Page 22 - xxx" reads as a single-page session.
_PAGE = re.compile(r"\b(?:pages?|pgs?|pp?)\.?\s*(\d+|x+|\?+)\b", re.I)
# "up to page 19" / "through page 19" — an end page with no start.
_UPTO = re.compile(r"\b(?:up\s+to|upto|through|till|until)\s+(?:pages?|pgs?|pp?)\.?\s*(\d+)\b", re.I)

# What the session was. Order matters: "exercise" beats "implementation" when a
# line says both, because the exercises are what the chapter-status rule counts.
_MODES = [
    ("exercises", re.compile(r"\b(?:exercises?|ex\.?\s*\d|problems?|questions?\s+\d|q\d)\b", re.I)),
    ("code", re.compile(r"\b(?:implement\w*|coding|code|build|notebook|repl)\b", re.I)),
    ("review", re.compile(r"\b(?:review|revis\w+|recap|re-?read|reread|summar\w+)\b", re.I)),
    ("read", re.compile(r"\b(?:read\w*|book|chapter|page)\b", re.I)),
]


def _num(tok: str | None) -> int | None:
    """A captured page token as an int, or None when it is a placeholder."""
    if tok is None or _UNKNOWN.match(tok):
        return None
    try:
        return int(tok)
    except ValueError:
        return None


def chapter_of(text: str) -> str | None:
    """"2", "1 to 2", "introduction" — or None when the text names no chapter."""
    m = _CH_RANGE.search(text or "")
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo == hi:
            return str(lo)
        # Normalised to one spelling so "1-2", "1 to 2" and "1 & 2" group as
        # one chapter in the master record instead of three.
        return f"{min(lo, hi)} to {max(lo, hi)}"
    m = _CH_NUM.search(text or "")
    if m:
        return str(int(m.group(1)))
    for rx, label in _CH_WORD:
        if rx.search(text or ""):
            return label
    return None


def pages_of(text: str) -> tuple[int | None, int | None]:
    """(from, to). Either may be None — see the module docstring."""
    text = text or ""
    upto = _UPTO.search(text)
    if upto:
        return None, int(upto.group(1))
    toks = [_num(m.group(1)) for m in _PAGE.finditer(text)]
    real = [t for t in toks if t is not None]
    if not toks:
        return None, None
    if len(toks) == 1:
        return (real[0], None) if real else (None, None)
    first, last = toks[0], toks[-1]
    # "Page 22 - xxx": a start with no recorded end.
    if first is not None and last is None:
        return first, None
    # "Page - xxx - Page 49": an end with no recorded start.
    if first is None and last is not None:
        return None, last
    if first is None and last is None:
        return None, None
    # A range written backwards is a typo, not a backwards read.
    return (first, last) if first <= last else (last, first)


def mode_of(text: str) -> str | None:
    for mode, rx in _MODES:
        if rx.search(text or ""):
            return mode
    return None


def parse(purpose: str) -> dict:
    """Everything this text yields, as the three session fields.

    Returns a dict with `chapter`, `pages_from`, `pages_to`, `mode` — any of
    which may be None. Callers treat None as "not recorded", never as zero.
    """
    text = purpose or ""
    lo, hi = pages_of(text)
    return {
        "chapter": chapter_of(text),
        "pages_from": lo,
        "pages_to": hi,
        "mode": mode_of(text),
    }


def chapter_sort_key(chapter: str | None) -> tuple:
    """Order chapters the way a book does, with the unnumbered ones in place.

    Front matter and the introduction come first, then numbered chapters by
    their leading number ("1 to 2" sorts as 1), then anything unrecognised
    alphabetically, then the sessions that never said which chapter they were.
    """
    if not chapter:
        return (9, 0.0, "")            # "no chapter recorded" sorts last
    c = chapter.strip().lower()
    if c == "front matter":
        return (0, 0.0, c)
    if c == "introduction":
        return (0, 0.5, c)
    m = re.match(r"(\d+)", c)
    if m:
        # A range sorts at its first chapter but after that chapter alone, so
        # "1" then "1 to 2" then "2".
        return (1, float(m.group(1)) + (0.5 if "to" in c else 0.0), c)
    return (2, 0.0, c)
