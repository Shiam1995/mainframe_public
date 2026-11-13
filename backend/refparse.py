"""Parse a pasted bibliography into individual references — no LLM involved.

The LLM path invents identifiers that never appeared in the source (measured
against a real bibliography: 5 of 8 arXiv ids were fabricated, one duplicated
from a different entry). This parser is deliberately literal — a link is only
ever taken from characters present in the text you pasted, so fabrication is
structurally impossible rather than merely unlikely.

Handles the shapes that cover almost every bibliography:
    [1] A. Author and B. Author. Title here. Venue, 2007.
    1. A. Author. Title here. Venue, 2007.
    A. Author, B. Author. Title here. Venue, 2007.     (blank-line separated)
    Author, A., Other, B., and Third, C. Title here. In Venue, 2007.
        (author-year / ICML-JMLR style — surname first, initials closing the
         author run, no markers and no blank lines between entries)
"""
from __future__ import annotations

import re

# The opening bracket is optional: PDF text layers drop it often enough
# ("8] R. Cao, …") that requiring it silently welds that entry onto the one
# before it, and the whole reference disappears without any error.
_MARKER = re.compile(r"^\s*(?:\[?(\d{1,3})\]|(\d{1,3})[.)])\s+")
# The digits of a year, with an optional disambiguating suffix ("2025a") that
# author-year styles append when one author has two papers in a year — the
# suffix is part of the citation key, not of the year.
_YEAR = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")
# ")" is allowed through: a DOI can contain one ("10.1016/0893-6080(89)90020-8")
# and stopping at it yields a dead link. A URL merely wrapped in prose
# parentheses is handled by `_trim_link`, which drops only UNBALANCED trailers.
_URL = re.compile(r"https?://[^\s,;\]]+", re.IGNORECASE)
_WWW = re.compile(r"\bwww\.[^\s,;\]]+", re.IGNORECASE)
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;\]]+")
_ARXIV = re.compile(r"arXiv[:\s]\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
# A token that reads as an initial: "R.", "R.M.", "L.-J.".
# Deliberately case-SENSITIVE — with re.IGNORECASE, [A-Z] also matches lowercase
# and surnames like "Cox" and "Ng" parse as three initials, swallowing the title.
# Every letter but the last must carry its period — callers hand this the token
# with its closing period already removed. Without that rule an acronym ending a
# title ("…in the age of large-scale AI.") reads as an author initial, the
# author run is taken to run past the title, and the venue becomes the title.
_INITIALS = re.compile(r"^(?:[A-Z]\.-?){0,3}[A-Z]$")
# "et al." closes an author list rather than continuing it.
_ET_AL = re.compile(r"^al$", re.IGNORECASE)
_TRAILING_YEAR = re.compile(r",\s*(?:19|20)\d{2}[a-z]?$")
# Royal Society / Nature / APA style puts the year BETWEEN authors and title:
#     Turner JR, Xue Y. 2018 On the success of megaprojects. IJMPB 17, 783–805.
#     Hafner, D., Lillicrap, T., 2018. Learning latent dynamics…
# The authors run up to the first year token; the title is what follows it.
_YEAR_FIRST = re.compile(
    r"^(?P<authors>.{2,200}?[.,])\s+(?P<year>(?:19|20)\d{2})[a-z]?[.,]?\s+"
    r"(?P<rest>[“\"'A-Z0-9].+)$"
)


# A line break can fall on a hyphen the word actually owns. When it does,
# dropping the hyphen welds two words together ("Model-\nbased" → "Modelbased"),
# which is worse than keeping a spurious one. These are the halves that signal a
# real compound rather than a syllable break — deliberately words that are never
# themselves split at that point by a hyphenator.
_COMPOUND_LEFT = frozenset(
    "multi non self cross semi meta model data task agent policy zero few one "
    "two three fine high low large small real long short single double first "
    "second closed mixed source plasma vision language open".split()
)
_COMPOUND_RIGHT = frozenset(
    "based aware wise level scale free specific dependent driven world term "
    "order tuning shot source art augmentation context efficient facing "
    "language vision rank".split()
)


# A PDF text layer hands back typographic ligatures as single code points, so
# "fine-tuning" arrives as "ﬁne-tuning". Left in, the title never matches the
# same paper anywhere else — not in a Crossref lookup, not in the user's search.
_LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st",
})


def _normalise(text: str) -> str:
    return text.translate(_LIGATURES)


def _dehyphenate(text: str) -> str:
    """Rejoin words a PDF split across a line break.

    Drops the hyphen for ordinary words (`Understand-\\ning` → `Understanding`)
    but keeps it where it is real: inside a URL or domain
    (`www.image-\\nnet.org` → `www.image-net.org`) and inside a compound whose
    halves stand on their own (`Model-\\nbased` → `Model-based`).
    """
    text = _normalise(text)

    def join(m: re.Match) -> str:
        left, right = m.group(1), m.group(2)
        tail = left[-24:].lower()
        in_url = "://" in tail or "www." in tail or "/" in tail
        last = re.split(r"[^\w'’]", left)[-1].lower()
        head = re.split(r"[^\w'’]", right)[0].lower()
        # "Leap-of-\nthought", "out-of-\ndomain": a word that is already a
        # hyphenated compound is continuing that compound, not being split.
        chained = bool(re.search(r"[^\W\d_]-[^\W\d_]+$", left))
        compound = last in _COMPOUND_LEFT or head in _COMPOUND_RIGHT or chained
        return left + ("-" if in_url or compound else "") + right

    text = re.sub(r"(\S*[A-Za-z0-9])-\n\s*([a-z]\S*)", join, text)
    return _rejoin_urls(text)


# What a URL's continuation looks like: URL characters, and carrying a digit or
# a slash. "Innovation" has neither and opens the next reference instead.
_URL_TAIL_TOKEN = re.compile(r"(?=[^\s]*[\d/])[\w%~+./#?=&()\[\]:-]+")
# ...and the direction that settles the ambiguous cases: a continuation starts
# lowercase or with a digit, or it carries a path separator. A capitalised token
# with neither opens the NEXT reference —
#     "https://arxiv.org/abs/2105.12192."  +  "B. Venkatraman Ayush Jain, …"
#     "…/ML2327/ML23279A041.pdf."          +  "CASMO-5 User's Manual. …"
# — and gluing those together loses a whole reference, where declining to join
# a genuine continuation only shortens a link. The asymmetry decides the rule.
def _continues_url(tok: str) -> bool:
    return bool(_URL_TAIL_TOKEN.fullmatch(tok)) and (
        tok[:1].islower() or tok[:1].isdigit() or "/" in tok
    )


def _rejoin_urls(text: str) -> str:
    """Repair a URL the PDF broke across a line with no hyphen to rejoin on.

    "https://doi.\norg/10.1016/…" is otherwise captured as the truncated
    "https://doi." and every DOI in the bibliography resolves nowhere.

    A trailing "/", "." or ":" is not on its own proof that the URL is
    unfinished — plenty of complete URLs end in "/", and the line after one is
    usually the NEXT reference. So the following line has to read like more URL
    (its first token carries a digit, dot or slash) and must not open a new
    entry, or the two get welded together and a reference disappears.
    """
    lines = text.split("\n")
    if not lines:
        return text
    out = [lines[0]]
    for ln in lines[1:]:
        prev, nxt = out[-1], ln.lstrip()
        tok = nxt.split()[0] if nxt.split() else ""
        if (prev[-1:] in ("/", ".", ":")
                and re.search(r"https?:\S*$", prev)
                and tok and _continues_url(tok)
                and not _MARKER.match(nxt)):
            out[-1] = prev + nxt
        else:
            out.append(ln)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Page furniture
# --------------------------------------------------------------------------- #
_HEADING = re.compile(
    r"^(?:references|reference list|bibliography|works cited)\s*:?\s*$",
    re.IGNORECASE,
)
# A page number is a short bare integer alone on a line. Capped at 4 digits so a
# wrapped numeric URL tail is not eaten — page numbers run to thousands.
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")
# Signals that a line is citation text rather than furniture: a year, a page
# range, or an opening word that only ever continues an entry.
_CITE_SIGNAL = re.compile(r"(?:19|20)\d{2}|\d+\s*[–-]\s*\d+|\bpp?\.\s*\d")
_CONTINUES = re.compile(
    r"^(?:in|and|pp?|vol|no|eds?|editors?|available|retrieved|from|doi|isbn"
    r"|issn|url)\b[.:]?(?:\s|$)",
    re.IGNORECASE,
)


def _reads_as_citation(line: str) -> bool:
    return bool(_CITE_SIGNAL.search(line) or _CONTINUES.match(line))


def strip_furniture(lines: list[str], keep_blanks: bool = False) -> list[str]:
    """Drop the section heading, page numbers and running headers/footers.

    A running header is detected, not hard-coded: it is a line whose normalised
    form appears more than once. Repetition alone is NOT enough, though — in an
    author-year bibliography the wrapped venue tails repeat constantly
    ("Systems, 2022." closes two different entries), and dropping those silently
    deletes the end of a reference along with its year. A repeated line is only
    furniture when it also either sits against a page-number line at one of its
    occurrences, or carries no citation signal at all.
    """
    def norm(ln: str) -> str:
        return re.sub(r"\s+", " ", ln.strip().lower())

    stripped = [ln.strip() for ln in lines]
    counts: dict[str, int] = {}
    for s in stripped:
        n = norm(s)
        if len(n) >= 8:
            counts[n] = counts.get(n, 0) + 1

    page_adjacent = {
        norm(s)
        for i, s in enumerate(stripped)
        if len(norm(s)) >= 8
        and any(
            _PAGE_NUMBER.match(stripped[j])
            for j in (i - 1, i + 1)
            if 0 <= j < len(stripped) and stripped[j]
        )
    }

    out: list[str] = []
    for s in stripped:
        if not s:
            if keep_blanks:
                out.append("")
            continue
        if _HEADING.match(s) or _PAGE_NUMBER.match(s):
            continue
        n = norm(s)
        if counts.get(n, 0) >= 2 and (n in page_adjacent or not _reads_as_citation(s)):
            continue
        out.append(s)
    return out


def split_entries(text: str) -> list[str]:
    """Break a pasted bibliography into one string per reference."""
    text = _dehyphenate(text.replace("\r\n", "\n"))
    lines = strip_furniture(text.split("\n"), keep_blanks=True)
    text = "\n".join(lines)

    # 1. explicit [n] / n. markers — the reliable case, and wrapped lines rejoin
    if sum(1 for ln in lines if _MARKER.match(ln)) >= 2:
        entries: list[str] = []
        cur: list[str] = []
        for ln in lines:
            if _MARKER.match(ln) and cur:
                entries.append(" ".join(cur))
                cur = []
            cur.append(ln.strip())
        if cur:
            entries.append(" ".join(cur))
        return [re.sub(r"\s+", " ", e).strip() for e in entries if e.strip()]

    # 2. blank-line separated blocks
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) >= 2:
        # Author-year bibliographies (no [n] markers) usually wrap without blank
        # lines between entries, so blank-line splitting can return a handful of
        # huge blocks holding dozens of references each — which is how a whole
        # citation went missing and only the model's truncated guess survived.
        # Try the author-start split on each block and take it when it clearly
        # finds more.
        out: list[str] = []
        for b in blocks:
            sub = _split_author_first(b)
            out.extend(sub if len(sub) > 1 else [b])
        return [re.sub(r"\s+", " ", e).strip() for e in out if e.strip()]

    # 3. a single unbroken block — author-start split, else one per line
    sub = _split_author_first(text)
    if len(sub) >= 2:
        return [re.sub(r"\s+", " ", e).strip() for e in sub if e.strip()]
    return [re.sub(r"\s+", " ", ln).strip() for ln in lines if len(ln.strip()) > 20]


# A line that opens a new citation in an author-first bibliography:
#   "Ramanan Sekar, Oleh Rybkin, … and Deepak Pathak."
#   "Hafner, D., Lillicrap, T., …"
# Two capitalised words, or a surname-comma-initial — enough to be a name, and
# specific enough that a wrapped title line ("Conference on Machine Learning")
# doesn't match on its own; the previous-line test below does the rest.
# The tail of a surname is matched with \w, not [A-Za-z]: "Akyürek" and
# "Särkkä" open entries too, and an ASCII-only class walked straight past them.
# The comma may not be followed by a number — that is what tells a publisher
# line ("CRC Press, 3rd edition, 2013.") from an author list.
_AUTHOR_START = re.compile(
    r"^(?:[A-ZÀ-ÖØ-Þ][\w'’\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'’\-\.]*){1,3},(?!\s*\d)"
    r"|[A-ZÀ-ÖØ-Þ][\w'’\-]+,\s*(?:[A-ZÀ-ÖØ-Þ]\.\s*){1,4}"            # Surname, A. B.
    r")"
)
# An entry ends on a year, a page range, a DOI/URL tail or a closing bracket.
_ENTRY_END = re.compile(r"(?:(?:19|20)\d{2}[a-z]?\.?|\d\.|\)|[/\w]\.)\s*$")


def _split_author_first(block: str) -> list[str]:
    """Split a marker-less bibliography where each entry starts with authors.

    A line only starts a new entry when it *looks like* an author list AND the
    text so far looks finished. Requiring both is what stops a wrapped title
    line that happens to begin with a name ("Minecraft demonstrations…") from
    cutting an entry in half.
    """
    lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
    if len(lines) < 4:
        return [block]
    entries: list[str] = []
    cur: list[str] = []
    for ln in lines:
        starts = bool(_AUTHOR_START.match(ln))
        finished = bool(cur) and bool(_ENTRY_END.search(cur[-1]))
        if starts and finished:
            entries.append(" ".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        entries.append(" ".join(cur))
    # Only worth using if it actually broke things apart into plausible entries.
    return entries if len(entries) >= 2 else [block]


def _year_first_parse(entry: str) -> tuple[int, str] | None:
    """(year, title) when the entry puts the year between authors and title.

    Guarded so the classic `Title. Venue, 2007.` shape falls through: the year
    must sit in the first 60% of the entry (an author list, even a long one,
    ends well before a trailing venue-year does), and what follows it must read
    as a title — starting like one and at least two words long.
    """
    s = _MARKER.sub("", entry, count=1).strip()
    m = _YEAR_FIRST.match(s)
    if not m or m.start("year") > 0.6 * len(s):
        return None
    rest = m.group("rest")
    end = re.search(r"[.?!](?:\s|$)", rest)
    title = (rest[: end.end()] if end else rest).strip().rstrip(".").strip()
    if len(title.split()) < 2:
        return None
    return int(m.group("year")), re.sub(r"\s+", " ", title)


# Surname-first author-year style: "Abbasi-Yadkori, Y., …, and Szepesvari, C."
# The author run CLOSES on an initial here, where first-name-first style closes
# on a surname — so the two need opposite rules for where the title starts.
_SURNAME_FIRST = re.compile(r"^[A-ZÀ-ÖØ-Þ][\w'’\-]+,\s*[A-ZÀ-ÖØ-Þ]\.")
# What follows the title, once the title has ended on a question or exclamation
# mark. Used only to decide whether a second sentence is still part of the title
# ("…in-context learning? Investigations with linear models.").
_VENUE_START = re.compile(
    r"^(?:In\b|arXiv\b|URL\b|Advances\b|Proceedings\b|Journal\b|Transactions\b"
    r"|IEEE\b|ACM\b|PhD thesis\b|Master'?s thesis\b|Technical [Rr]eport\b"
    r"|Nature\b|Science\b|OpenReview\b|Available\b|Retrieved\b|The Annals\b"
    r"|pp?\.|Vol\.|No\.|doi\b|https?://)"
)


# --------------------------------------------------------------------------- #
# Elsevier / Vancouver comma style
# --------------------------------------------------------------------------- #
# Authors, title and venue are separated by COMMAS, with no period closing the
# author run:
#     J. Bucalossi, A. Ekedahl, et al., WEST full tungsten operation with an
#     ITER grade divertor, Nucl. Fusion 64 (11) (2024) 112022.
# The period-delimited rules below cannot see this shape. The first "." in the
# entry belongs to a journal abbreviation ("Nucl. Fusion"), so the title comes
# back as the venue — or as a bare DOI when the entry holds no period at all,
# which then fails the length check in `parse` and the reference is dropped
# outright. On a 41-entry Elsevier bibliography that lost 16 references and
# mistitled the rest.
#
# One author segment: "J. Bucalossi", "R.A. Pitts", "T.-Y. Lin", "A. Li Puma".
# The initials must carry their periods — that is what keeps a title segment
# starting with an acronym ("IR thermography diagnostics for the WEST project")
# out of the author run.
_AUTHOR_SEG = re.compile(
    r"^(?:and\s+)?(?:[A-ZÀ-ÖØ-Þ]\.[-\s]?){1,4}\s*"
    r"[A-ZÀ-ÖØ-Þ][\w'’\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\w'’\-]+){0,2}\.?$"
)
_ET_AL_SEG = re.compile(r"^(?:and\s+)?et\s+al\.?$", re.IGNORECASE)
_BARE_YEAR_SEG = re.compile(r"^(?:19|20)\d{2}[a-z]?\.?$")
# The classic period style, seen from the first segment that is not an author:
# "B. Author. Title here. Venue". When this matches, the entry is NOT comma
# style and belongs to `_title_start`.
_AUTHOR_THEN_PERIOD = re.compile(
    r"^(?:and\s+)?(?:[A-ZÀ-ÖØ-Þ]\.[-\s]?){1,4}\s*"
    r"[A-ZÀ-ÖØ-Þ][\w'’\-]+\.(?:\s|$)"
)
# What ends the title: the venue. Case-sensitive on purpose — a lowercased
# "in one day" is title text, "In: Proceedings…" is not.
_VENUE_SEG = re.compile(
    r"^(?:arXiv\b|https?://|www\.|doi\b|In:|In\s+[A-Z]|Poster\b|Publisher:"
    r"|Proceedings\b|Advances\b|Technical [Rr]eport\b|PhD thesis\b|pp?\.\s*\d)"
)


def _comma_style_parse(entry: str) -> tuple[int | None, str] | None:
    """(year, title) for the comma-delimited style, or None if it doesn't fit."""
    s = _MARKER.sub("", entry, count=1).strip()
    if _SURNAME_FIRST.match(s):
        return None                      # "Hafner, D., …" — the other style
    segs = [p.strip() for p in s.split(",")]
    if len(segs) < 3:
        return None

    i = authors = 0
    while i < len(segs):
        if _AUTHOR_SEG.match(segs[i]) or _ET_AL_SEG.match(segs[i]):
            authors += 1
            i += 1
            continue
        # "…, B. Zhang, J.E.T. contributors, et al., Long plasma duration…":
        # a segment that is not itself an author still belongs to the run when
        # "et al." closes it.
        if any(_ET_AL_SEG.match(x) for x in segs[i + 1:i + 3]):
            i += 1
            continue
        break
    # A corporate author carries no initials ("OpenAI, 2024, GPT-4 technical
    # report"); accept one only in first position and only when a bare year
    # follows, which is what distinguishes it from a title.
    if authors == 0:
        if i or len(segs) < 3 or not _BARE_YEAR_SEG.match(segs[1]):
            return None
        if not re.fullmatch(r"[A-ZÀ-ÖØ-Þ][\w'’\-]+(?:\s+[\w'’\-]+){0,2}", segs[0]):
            return None
        i = 1

    year = None
    if i < len(segs) and _BARE_YEAR_SEG.match(segs[i]):
        year = int(segs[i][:4])          # year sits between authors and title
        i += 1
    if i >= len(segs) or _AUTHOR_THEN_PERIOD.match(segs[i]):
        return None

    title_segs: list[str] = []
    while i < len(segs):
        seg = segs[i]
        if _VENUE_SEG.match(seg) or _YEAR.search(seg):
            break
        title_segs.append(seg)
        i += 1
    title = ", ".join(t for t in title_segs if t).strip().rstrip(".").strip()
    if len(title.split()) < 2 or len(title) > 300:
        return None
    return year, re.sub(r"\s+", " ", title)


def _title_start(s: str) -> int:
    """Index where the title begins — i.e. where the author run ends."""
    if _SURNAME_FIRST.match(s):
        # Authors end at the LAST initial of the opening run: everything up to
        # "…and Szepesvari, C." is authors, and the title follows it. Taking the
        # first non-initial break instead (the first-name-first rule) lands one
        # sentence too late and returns the venue as the title.
        last = 0
        for m in re.finditer(r"[.?!]\s+", s):
            words = s[: m.start()].split()
            prev = words[-1].rstrip(",") if words else ""
            if _INITIALS.match(prev) and not _ET_AL.match(prev):
                last = m.end()
                continue
            return last or m.end()
        return last
    for m in re.finditer(r"[.?!]\s+", s):
        words = s[: m.start()].split()
        prev = words[-1].rstrip(",") if words else ""
        if _INITIALS.match(prev) and not _ET_AL.match(prev):
            continue                      # still inside the author list
        return m.end()                    # a surname, or "et al." — authors end here
    return 0


def title_of(entry: str) -> str:
    """The title, with the leading author run stripped.

    Where the author list ends depends on the style — see `_title_start`. The
    title then runs to the next `.`, `?` or `!`, so `…for object recognition?`
    keeps its question mark; a title that ends on `?` mid-way carries on into
    the next sentence unless a venue starts there.
    """
    entry = _normalise(entry)
    cs = _comma_style_parse(entry)
    if cs:
        return cs[1]
    yf = _year_first_parse(entry)
    if yf:
        return yf[1]
    s = _MARKER.sub("", entry, count=1).strip()
    rest = s[_title_start(s):].strip() or s
    end = re.search(r"[.?!](?:\s|$)", rest)
    title = (rest[: end.end()] if end else rest).strip()
    # "What learning algorithm is in-context learning? Investigations with
    # linear models." — one title, two sentences. Only ? and ! split a title
    # this way; a full stop ends it.
    while end and title.rstrip().endswith(("?", "!")) and len(title) < 250:
        tail = rest[end.end():].strip()
        if not tail or _VENUE_START.match(tail):
            break
        rest, end = tail, re.search(r"[.?!](?:\s|$)", tail)
        title = (title + " " + (tail[: end.end()] if end else tail)).strip()
    title = title.rstrip(".").strip()
    # a bare citation like "ILSVRC-2012, 2012" carries the year, not a subtitle
    title = _TRAILING_YEAR.sub("", title).strip()
    return re.sub(r"\s+", " ", title)


def _trim_link(url: str) -> str:
    """Drop trailing punctuation that belongs to the sentence, not the link.

    A ")" is only trailing punctuation when nothing opened it — that keeps the
    ")" inside "10.1016/0893-6080(89)90020-8" while still closing "(see …/foo)".
    """
    while url and url[-1] in ".,;)":
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def link_of(entry: str) -> str | None:
    """A link ONLY when it literally appears in the pasted text."""
    entry = _normalise(entry)
    u = _URL.search(entry)
    if u:
        return _trim_link(u.group(0))
    w = _WWW.search(entry)
    if w:
        return "https://" + _trim_link(w.group(0))
    d = _DOI.search(entry)
    if d:
        return "https://doi.org/" + _trim_link(d.group(0))
    a = _ARXIV.search(entry)
    if a:
        return "https://arxiv.org/abs/" + a.group(1)
    return None


def year_of(entry: str) -> int | None:
    """Publication year — the last one in the entry, which skips volume numbers
    and the years that appear inside conference names. In year-first style the
    leading year is the publication year and a DOI tail can carry a different
    one, so that style is detected first."""
    cs = _comma_style_parse(entry)
    if cs and cs[0]:
        return cs[0]
    yf = _year_first_parse(entry)
    if yf:
        return yf[0]
    # An arXiv id and a DOI are full of four-digit runs that read as years —
    # "arXiv:1905.12322" dated a 2019 paper to 1905, and the DOI tail
    # ".../j.fusengdes.2020.112223" overrode the entry's own 2021. Mask both.
    text = _DOI.sub(" ", _ARXIV.sub(" ", entry))
    # A parenthesised year is the publication year in this style, and outranks a
    # trailing page range that happens to look like one ("146 (2019) 2015–2020").
    parens = re.findall(r"\((?:19|20)\d{2}[a-z]?\)", text)
    if parens:
        return int(parens[-1][1:5])
    years = _YEAR.findall(text)
    return int(years[-1]) if years else None


def parse(text: str) -> list[dict]:
    """Pasted text → [{title, year, link, raw}], in source order."""
    out: list[dict] = []
    for raw in split_entries(text):
        title = title_of(raw)
        if len(title) < 6:
            continue
        out.append({
            "title": title[:300],
            "year": year_of(raw),
            "link": link_of(raw),
            "raw": raw[:400],
        })
    return out
