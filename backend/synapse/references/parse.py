"""Segment a bibliography into entries, then parse each entry into fields.

Segmentation is built for how PDFs actually break (all three seen in a real
extraction, not hypothetical):

  * detached markers — [1]..[10] as a contiguous block at the top of the page,
    nowhere near their entries. Anything keyed on "line starts with [n]"
    mis-aligns every entry, so entries are segmented on their own boundaries
    and the ordinals re-attached positionally afterwards.
  * page furniture mid-reference — a running header and an editorial
    placeholder landing between the two halves of a URL. Furniture is stripped
    BEFORE segmenting (the section heading, bare page numbers, placeholder
    patterns, and lines that repeat across pages — but see
    `refparse.strip_furniture`: repetition alone is not proof, because a
    two-column author-year bibliography repeats its wrapped venue tails).
  * wrapped URLs — split across lines with or without a hyphen. Rejoined
    before anything looks at them, so a live link doesn't read as dead.

Field parsing follows the house rule from refparse.py: identifiers (DOI, URL,
ISBN, ISSN) are ONLY ever taken literally from the entry text by regex —
never from a model, which fabricates them. The LLM (local Ollama, heuristic
fallback) supplies what regex can't: title, authors, venue.
"""
from __future__ import annotations

import logging
import re

import llm
import refparse
import refstyle

log = logging.getLogger("synapse.references.parse")

# --------------------------------------------------------------------------- #
# Furniture
# --------------------------------------------------------------------------- #
# Editorial boilerplate that publishers' templates leave in the text layer.
_PLACEHOLDER = re.compile(
    r"will be inserted|volume editors|to appear in|preprint submitted",
    re.IGNORECASE,
)
# A page number is a short bare integer alone on a line. Capped at 4 digits so
# a URL tail that happens to be numeric (e.g. a wrapped `doc_id=47559`) is not
# eaten — page numbers run to thousands, document ids run longer.
def _strip_furniture(lines: list[str]) -> list[str]:
    """Drop editorial placeholders, then the headings/page numbers/running
    headers that `refparse.strip_furniture` detects.

    Repetition alone does not make a line furniture — in an author-year
    bibliography the wrapped venue tails repeat, and dropping them deletes the
    end of a reference. That call carries the rule; only the publisher-template
    placeholders, which can appear just once, are handled here.
    """
    return refparse.strip_furniture(
        [ln for ln in lines if not _PLACEHOLDER.search(ln)]
    )


# --------------------------------------------------------------------------- #
# Detached ordinal markers
# --------------------------------------------------------------------------- #
_MARKER_LINE = re.compile(r"^\[(\d{1,3})\]$|^(\d{1,3})[.)]$")


def _extract_detached_markers(lines: list[str]) -> tuple[list[str], list[int]]:
    """Remove runs of >= 2 consecutive marker-only lines; return their ordinals.

    Ordinals are collected in order of appearance so a per-page block
    ([1]..[10] on one page, [11]..[16] on the next) still yields 1..16.

    A SINGLE marker line is the other layout: the number sits on its own line
    and its reference starts on the next ("[25]" / " A. Murari, …" — Elsevier
    copy-paste does this mid-list). That marker is glued back onto the line
    after it. Left alone, "[25]" alone fails the inline-marker test, so every
    such entry merged into the last properly-marked one: 78 references pasted,
    48 found (2026-10-28). Only the bracketed form is glued, and before runs
    are looked for: a wrapped DOI tail ("004.", "04.") also reads as a
    marker-only line, and must neither swallow the next entry's number nor
    pair up with a lone "[55]" into a fake run.
    """
    lead: list[str] = []
    i = 0
    while i < len(lines):
        cur, nxt = lines[i].strip(), (lines[i + 1].strip() if i + 1 < len(lines) else "")
        prev = lines[i - 1].strip() if i else ""
        # The tail of a detached column ("[9]", "[10]", then text) is a run, not a lead-in.
        if (re.fullmatch(r"\[\d{1,3}\]", cur) and nxt and not _MARKER_LINE.match(nxt)
                and not re.fullmatch(r"\[\d{1,3}\]", prev)):
            lead.append(cur + " " + nxt)
            i += 2
        else:
            lead.append(lines[i])
            i += 1
    lines = lead

    ordinals: list[int] = []
    keep: list[str] = []
    i = 0
    while i < len(lines):
        j = i
        run: list[int] = []
        while j < len(lines) and (m := _MARKER_LINE.match(lines[j])):
            run.append(int(m.group(1) or m.group(2)))
            j += 1
        if len(run) >= 2:
            ordinals.extend(run)
            i = j
        else:
            keep.append(lines[i])
            i += 1
    return keep, ordinals


# --------------------------------------------------------------------------- #
# Wrapped-line repair
# --------------------------------------------------------------------------- #
_URLISH_TAIL = re.compile(r"(?:https?://|www\.|doi\.org/)\S*$", re.IGNORECASE)
# A two-column layout also breaks a URL at its colon, leaving "…URL https:" and
# "//host/path." on separate lines — the halves must rejoin or the entry ends
# without a link and its neighbour merges into it.
_SCHEME_TAIL = re.compile(r"\bhttps?:$", re.IGNORECASE)


def _rejoin_wrapped(lines: list[str]) -> list[str]:
    """Glue back URLs and number ranges the layout split across lines.

    A line whose tail is inside a URL and ends on a URL-structural character
    continues onto the next line's first token — hyphen kept, because inside a
    URL the hyphen is real. `1042-` / `1049` becomes `1042-1049`.

    A trailing `/` is ambiguous: it can end a complete URL. There the token is
    only glued when it reads as a path continuation (lowercase/digit start) —
    otherwise "…index-primer/" would swallow the next entry's first word.
    """
    out: list[str] = []
    for ln in lines:
        if out:
            prev = out[-1]
            tail_url = _URLISH_TAIL.search(prev)
            tok, _, rest = ln.partition(" ")
            glue = (
                tail_url
                and (
                    prev[-1] in "-=?&_%~"
                    or (prev[-1] == "/" and re.match(r"^[a-z0-9]", tok))
                )
            ) or (_SCHEME_TAIL.search(prev) and tok.startswith("//"))
            if glue:
                out[-1] = prev + tok
                if rest.strip():
                    out.append(rest.strip())
                continue
            if re.search(r"\d-$", prev) and re.match(r"^\d", ln):
                out[-1] = prev + ln
                continue
        out.append(ln)
    return out


# --------------------------------------------------------------------------- #
# Boundary segmentation (author-year bibliographies with no usable markers)
# --------------------------------------------------------------------------- #
# A line that FINISHES an entry. Only hard evidence counts — an identifier or
# a closing quote. A bare "…2016." is NOT enough: an author-year style puts
# exactly that at the end of its *first* line ("…Sivarajah. 2016.") and
# treating it as an end splits every such entry in half.
_HARD_END = re.compile(
    r"(?:"
    r"10\.\d{4,9}/[^\s]+\.?"          # DOI
    r"|https?://\S+"                   # URL
    r"|ISSN[:\s]*[\dX–-]{8,10}"        # ISSN
    r"|ISBN[:\s]*[\d –-]{10,18}X?\.?"  # ISBN
    r"|[”\"’']\."                      # closing quote + period
    r")$"
)
# Softer evidence: a year, a page range ("261–280."), a bare page ("…2006, 81.")
# or "p. 60." closing the line. IOS-Press-style bibliographies end EVERY entry
# this way — no DOI, no URL — so these must be able to close an entry, but only
# when the NEXT line opens with an unambiguous author signature.
_SOFT_END = re.compile(
    r"(?:(?:19|20)\d{2}[a-z]?\.?|\d+[-–]\d+\.?|p\.\s*\d+\.|\b\d{1,4}\.)$"
)
# Words that continue the current entry — never start a new one.
_CONTINUATION = re.compile(
    r"^(?:retrieved|from|in|doi|isbn|issn|available|accessed|pp?\.|vol\.|no\.|and)\b[:.]?",
    re.IGNORECASE,
)
# "Name Name. 2017." / "European Commission. 2014 ff." — an author block
# (people or an org) closed by a year early in the line.
_AUTHOR_YEAR_SIG = re.compile(r"^.{2,120}?\.\s+(?:19|20)\d{2}(?:\s+ff)?[a-z]?\.")
# Initials-first author lists (IOS Press / Elsevier style):
#   "M. Austin, J. Zakar, …"   "J.S. Beasley, Networking, …"   "T. Dowling and…"
_INITIALS_START = re.compile(r"^(?:[A-Z]\.\s*){1,4}[A-ZÀ-Þ][\w'’\-]+(?:,| and )")
# Authors written out in full — the NeurIPS/ICML/ACM shape, which carries no
# initials at all and so is invisible to every initials-based rule:
#   "Riley Cumberland, Ryan Sweet, Ugur Mertyurek, …"
#   "Ugur Mertyurek and William A. Wieselquist. Assessment of…"
#   "Google-Gemini-Team. Gemini: A family of…"
# and the authorless entry, where the title itself opens the reference:
#   "CASMO-5 User's Manual. Studsvik Scandpower (SSP), …"
# A personal name is at least TWO capitalised words — one is indistinguishable
# from a wrapped title line ("Systems, New Orleans, …").
_NAME = r"[A-ZÀ-Þ][\w'’\-]+(?:\s+[A-ZÀ-Þ][\w'’\-]*\.?){1,3}"
_FULLNAME_START = re.compile(
    rf"^{_NAME},\s+[A-ZÀ-Þ]"           # "Riley Cumberland, Ryan Sweet, …"
    rf"|^{_NAME}\s+and\s+[A-ZÀ-Þ]"     # "Ugur Mertyurek and William A. …"
    # An authorless or corporate entry, where the title opens the reference:
    # "Google-Gemini-Team. Gemini: …", "CASMO-5 User's Manual. Studsvik …".
    # Every word before the period is capitalised AND one carries a hyphen or a
    # digit — which a wrapped sentence fragment ("Systems.") never does.
    rf"|^(?=[A-ZÀ-Þ][\w'’\-]*[\-\d])[A-ZÀ-Þ][\w'’\-]*"
    rf"(?:\s+[A-ZÀ-Þ][\w'’\-]*){{0,3}}\.\s+[A-ZÀ-Þ“\"]"
)
# An org acronym as the author: "DoD, Levels of…", "NASA, Mars…", "GAO, Best…".
# Short token + comma + capitalised title word; length-capped so a wrapped
# title line ("Astronautica 20(1989), …") can't match.
_ORG_START = re.compile(r"^[A-Z][A-Za-z]{1,7},\s+[A-Z]")

# The author-date families (APA, `apalike`, AAAI/JAIR, Chicago author-date):
#   "Bellemare, M., Veness, J., & Bowling, M. (2012). Investigating…"
#   "Legg, S. (2008). Machine Super Intelligence. Ph.D. thesis, …"
# Surname FIRST, then initials — the mirror image of _INITIALS_START, and
# invisible to every rule above: _FULLNAME_START wants two capitalised words
# before the comma ("Riley Cumberland,"), and _AUTHOR_YEAR_SIG wants a bare
# "… . 2012." rather than a parenthesised year.
#
# Surname + comma + an INITIAL is not on its own enough — a wrapped venue line
# reads the same way ("Systems, 15 (1), 25–46."). The parenthesised year soon
# after is what makes it unambiguous, so it is required by lookahead. Optional
# lowercase particles carry "van Hasselt, H." and "de Freitas, N.".
_APA_HEAD = re.compile(
    r"^(?:[a-zà-þ]{2,5}\s+){0,2}"                      # van / de / von der
    r"[A-ZÀ-Þ][\w'’\-]*(?:\s+[A-ZÀ-Þ][\w'’\-]*)?"        # surname, or two words
    r",\s+[A-ZÀ-Þ]\."                                  # , I.
)
_APA_YEAR = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
# "Powley, E.," / "Lucas, S. M.," — one surname-plus-initials group.
_APA_NAME = re.compile(r"[A-ZÀ-Þ][\w'’\-]+,\s+(?:[A-ZÀ-Þ]\.\s*){1,4}")


def _apa_start(line: str) -> bool:
    """Does this line open an author-date reference?

    The head alone is not enough — a wrapped venue line reads the same way
    ("Systems, 15 (1), 25–46."). Two independent things can settle it:

    the parenthesised year, which a venue fragment does not carry; or, when the
    author list is long enough to wrap and the year has been pushed onto the
    next line ("Browne, C. B., Powley, E., Whitehouse, D., …"), the sheer
    number of surname-plus-initials groups, which a venue fragment cannot fake.
    """
    if not _APA_HEAD.match(line):
        return False
    if _APA_YEAR.search(line[:220]):
        return True
    return len(_APA_NAME.findall(line)) >= 3


# In the author-date families the ONLY thing closing most entries is a full
# stop: "…(AAAI).", "…Springer, Berlin.", "…The MIT Press." — no DOI, no page
# range, no year. _SOFT_END cannot be widened to cover that (a bare period ends
# most lines in every style), so a plain period may close an entry only when
# the next line is an _APA_START, which carries its own year and so cannot be a
# wrapped fragment. A line ending in a comma is never an end: that is an author
# list continuing onto the next line, which is exactly how this style wraps.
_PERIOD_END = re.compile(r"[^\s,;:]\.\s*$")


# The ACL / NAACL / EMNLP / NeurIPS-natbib shape — full names, then a bare year
# as its own sentence:
#   "Jacob Andreas, Dan Klein, and Sergey Levine. 2018. Learning with…"
# Entries end on a bare venue ("…EMNLP.", "…arXiv:2204.01691.") so, as in the
# APA family, a full stop is the only ending there is. And the author list
# wraps freely — Brown et al. runs seven lines before its year — so the start
# cannot be judged from one line. `_natbib_start` reads ahead to the first
# ". YYYY." and accepts only when everything before it is an author run.

def _natbib_start(lines: list[str], i: int) -> bool:
    """Does lines[i] open a "Names. YYYY. Title." reference?"""
    if not re.match(r"^[A-ZÀ-Þ]", lines[i]) or _CONTINUATION.match(lines[i]):
        return False
    return refstyle.natbib_head(" ".join(lines[i:i + 8])) is not None


def _starts_entry(line: str) -> bool:
    if _CONTINUATION.match(line):
        return False
    return bool(re.match(r"^[\[\(]?[A-ZÀ-Þ“\"']", line))


def _strong_start(line: str) -> bool:
    return bool(
        _apa_start(line)
        or _AUTHOR_YEAR_SIG.match(line)
        or _INITIALS_START.match(line)
        or _ORG_START.match(line)
        or _FULLNAME_START.match(line)
        or refparse._AUTHOR_START.match(line)
        or refparse._MARKER.match(line)
    )


def _segment_by_boundary(lines: list[str]) -> list[str]:
    entries: list[str] = []
    cur: list[str] = []
    for i, ln in enumerate(lines):
        if cur:
            prev = cur[-1]
            close = (
                (_HARD_END.search(prev) and _starts_entry(ln))
                or (_SOFT_END.search(prev) and _strong_start(ln))
                # author-date: a full stop is the only ending there is
                or (_PERIOD_END.search(prev) and _apa_start(ln))
                # ACL natbib: same, with "Names. YYYY." read across the wrap
                or (re.search(r"[^\s,;:][.?!]\s*$", prev) and _natbib_start(lines, i))
            )
            if close:
                entries.append(" ".join(cur))
                cur = []
        cur.append(ln)
    if cur:
        entries.append(" ".join(cur))
    return entries


# --------------------------------------------------------------------------- #
# Public: segment
# --------------------------------------------------------------------------- #
def segment(text: str) -> list[dict]:
    """Bibliography text → [{ordinal, raw}], in source order.

    Furniture is stripped and wraps are repaired BEFORE any boundary logic
    runs; detached ordinals are re-attached positionally at the end.
    """
    text = text.replace("\r\n", "\n")
    lines = _strip_furniture(text.split("\n"))
    lines, detached = _extract_detached_markers(lines)
    lines = refparse._dehyphenate("\n".join(lines)).split("\n")
    lines = _rejoin_wrapped(lines)

    inline_markers = sum(1 for ln in lines if refparse._MARKER.match(ln))
    if inline_markers >= 2:
        raws = refparse.split_entries("\n".join(lines))
    else:
        raws = [re.sub(r"\s+", " ", e).strip() for e in _segment_by_boundary(lines)]
        raws = [r for r in raws if len(r) > 20]

    if detached and len(detached) != len(raws):
        log.warning(
            "detached markers (%d) do not line up with segments (%d) — ordinals dropped",
            len(detached), len(raws),
        )
        detached = []
    return [
        {"ordinal": (detached[i] if detached else i + 1), "raw": raw}
        for i, raw in enumerate(raws)
    ]


# --------------------------------------------------------------------------- #
# Field parsing (LLM + literal identifiers)
# --------------------------------------------------------------------------- #
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;\]]+")
_URL = re.compile(r"https?://[^\s,;\]]+", re.IGNORECASE)
_ISBN = re.compile(r"ISBN[:\s]*([\d][\d –-]{8,16}[\dX])", re.IGNORECASE)
_ISSN = re.compile(r"ISSN[:\s]*(\d{4}[–-]\d{3}[\dX])", re.IGNORECASE)

_FIELDS_SYS = (
    "You parse ONE bibliography entry. Return ONLY JSON with keys: "
    "title (string), authors (array of {family: string, given: string or null, "
    "is_org: boolean} — is_org true for an organisation like a commission or "
    "agency), year (integer or null), venue (string or null — the journal, "
    "conference, publisher or issuing body). Use null when the entry does not "
    "say. Do NOT include DOIs, URLs or ISBNs, and do not invent anything."
)


def _literal_identifiers(raw: str) -> dict:
    """DOI/URL/ISBN/ISSN taken from characters present in the entry — only."""
    doi = _DOI.search(raw)
    url = _URL.search(raw)
    isbn = _ISBN.search(raw)
    issn = _ISSN.search(raw)
    return {
        "doi": doi.group(0).rstrip(".,;") if doi else None,
        "url": url.group(0).rstrip(".,;") if url else None,
        "isbn": isbn.group(1).strip() if isbn else None,
        "issn": issn.group(1) if issn else None,
    }


_ORG_WORD = re.compile(
    r"commission|department|ministry|institute|centre|center|fund|agency|"
    r"university|council|committee",
    re.IGNORECASE,
)


def _author(name: str, given: str | None = None) -> dict:
    is_org = bool(_ORG_WORD.search(name))
    words = name.split()
    return {
        "family": name if is_org else words[-1],
        "given": None if is_org else (given or " ".join(words[:-1]) or None),
        "is_org": is_org,
    }


def _authors_from_run(run: str) -> list[dict]:
    """Parse an author run in surname-first style: "Abe, T., Buchanan, E. K.,
    and Cunningham, J. P." — the commas alternate between a family name and the
    initials belonging to the one before it, so a plain comma split would read
    every initial as another author. A two-author run has no comma at all
    before the first author's initials ("Cesa-Bianchi, N. and Lugosi, G."), so
    " and " splits too.

    In this style the chunk before the initials is the family name WHOLE —
    particles included, so "van der Wilk, M." keeps all three words as the
    family rather than reading "van der" as a given name.
    """
    surname_first = bool(refparse._SURNAME_FIRST.match(run))
    authors: list[dict] = []
    for chunk in run.split(","):
        chunk = re.sub(r"^(?:and|&)\s+", "", chunk.strip()).strip().rstrip(".")
        chunk = re.sub(r"^[^\w(\[]+", "", chunk)     # stray PDF diacritic debris
        if not chunk:
            continue
        for name in re.split(r"\s+and\s+", chunk):
            name = name.strip().rstrip(".")
            if not name:
                continue
            if refparse._INITIALS.match(name.replace(" ", "")):
                if authors and authors[-1]["given"] is None:
                    if not authors[-1]["is_org"]:
                        authors[-1]["given"] = name
                    continue
            authors.append(
                {"family": name, "given": None, "is_org": bool(_ORG_WORD.search(name))}
                if surname_first
                else _author(name)
            )
    return authors


def _heuristic_fields(raw: str) -> dict:
    """No-LLM fallback: refparse's literal title/year, authors best-effort."""
    title = refparse.title_of(raw)
    year = refparse.year_of(raw)
    m = re.match(r"^(.{2,160}?)\.\s+(?:19|20)\d{2}", raw)
    authors: list[dict] = []
    if m:
        for part in re.split(r",| and ", m.group(1)):
            part = part.strip().rstrip(".")
            if not part or len(part) < 3:
                continue
            authors.append(_author(part))
    else:
        # Author-year styles put the whole author run in front of the title;
        # refparse already knows where that boundary falls.
        body = refparse._MARKER.sub("", raw, count=1).strip()
        cut = refparse._title_start(body)
        if cut:
            authors = _authors_from_run(body[:cut].strip())
    return {"title": title, "authors": authors, "year": year, "venue": None}


async def parse_entry(raw: str, prompt_override: str | None = None) -> dict:
    """One raw entry → fields. `parse_source` records ollama vs heuristic."""
    fields: dict | None = None
    source = "heuristic"
    if await llm._use_ollama(prompt_override):
        data = await llm._ollama_json(_FIELDS_SYS, raw, prompt_override)
        if data and data.get("title"):
            fields = {
                "title": str(data["title"]).strip(),
                "authors": [
                    {"family": str(a.get("family", "")).strip(),
                     "given": (str(a["given"]).strip() or None) if a.get("given") else None,
                     "is_org": bool(a.get("is_org"))}
                    for a in (data.get("authors") or [])
                    if isinstance(a, dict) and a.get("family")
                ],
                "year": data.get("year") if isinstance(data.get("year"), int) else None,
                "venue": (str(data["venue"]).strip() or None) if data.get("venue") else None,
            }
            source = "ollama"
    if fields is None:
        fields = _heuristic_fields(raw)
    fields.update(_literal_identifiers(raw))   # identifiers: literal, always
    fields["raw_string"] = re.sub(r"\s+", " ", raw).strip()
    fields["parse_source"] = source
    return fields
