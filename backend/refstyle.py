"""Structural style detection, and field extraction driven by it.

`refparse.py` grew one branch per bibliography style, each guarded against the
others; the guards were what broke when a new style arrived. This module takes
the other route, the one the literature supports.

Two findings shape it.

**Styles collapse.** The Citation Style Language corpus holds 2,862 independent
styles, but classified by the ORDER of author/date/title/container they reduce
to three shapes covering 80% of styles and seven covering 94%, and the author
comes first in 96.6%. So a parser does not need to know "IEEE" from "Vancouver"
— it needs to know where the date sits. Date second means the author-date
family (APA, Harvard, Chicago author-date); date last means the numeric family
(IEEE, Vancouver, Elsevier, Springer LNCS).

**Detection beats parsing.** Crossref's style classifier reaches 94% by
throwing the WORDS away and classifying the punctuation-and-case skeleton
alone. A style is a distribution over that skeleton, and it is far easier to
recognise than any individual field boundary. We take the same skeleton, but
vote it across the whole bibliography rather than one entry — 40 entries in one
style is overwhelming evidence where a single entry is ambiguous.

Field extraction then follows BibPro's "blocking": anchor the fields that have
an orthographic signature (year, pages, volume, identifiers, the author run),
SUBTRACT them, and split only what remains. Every published evaluation finds
the venue the hardest field and the title/venue boundary the place parsers
fail, because those two are the only open-vocabulary title-case spans and they
sit adjacent. Subtracting everything else first is what makes that one split
tractable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# The skeleton — a reference with its words erased
# --------------------------------------------------------------------------- #
# Lifted in spirit from Crossref's citation-style-classifier, which showed that
# punctuation and case alone carry the style. The case tests are str methods
# rather than [A-Z] character classes: an ASCII-only class splits "Jablonski"
# spelled with its real diacritics into three tokens and loses the author
# entirely, and non-English surnames are entirely ordinary.
_YEARISH = re.compile(r"^(?:16|17|18|19|20)\d{2}[a-z]?$")


def _word_class(tok: str) -> str:
    if tok.isdigit():
        return "YEAR" if _YEARISH.match(tok) else "NUM"
    if _YEARISH.match(tok):
        return "YEAR"
    if tok.isupper():
        return "UCLETT" if len(tok) == 1 else "UCWORD"
    if tok.islower():
        return "LCLETT" if len(tok) == 1 else "LCWORD"
    if tok[:1].isupper() and tok[1:].islower():
        return "CAPWORD"
    return "WORD"


_PUNCT = {
    ".": "DOT", ",": "COMMA", "(": "LPAR", ")": "RPAR", "[": "LBRACK",
    "]": "RBRACK", ":": "COLON", ";": "SEMI", "/": "SLASH", "&": "AMP",
    "“": "QUOT", "”": "QUOT", '"': "QUOT", "'": "APOS", "’": "APOS",
}
_DASHES = "-‐‑‒–—―−"
_TOKEN = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])*|\d+|[^\s\w]")


def tokenize(entry: str) -> list[tuple[str, str, int, int]]:
    """[(text, class), …]. "Smith, J. (2011)." classes to
    CAPWORD COMMA UCLETT DOT LPAR YEAR RPAR DOT.

    The text is kept alongside the class because field extraction needs to slice
    the original string back out once the skeleton has told it where to cut.
    """
    out: list[tuple[str, str, int, int]] = []
    for m in _TOKEN.finditer(entry):
        tok = m.group(0)
        if tok in _PUNCT:
            cls = _PUNCT[tok]
        elif tok in _DASHES:
            cls = "DASH"
        else:
            cls = _word_class(tok)
        out.append((tok, cls, m.start(), m.end()))
    return out


def skeleton(entry: str) -> list[str]:
    return [c for _, c, _, _ in tokenize(entry)]


# --------------------------------------------------------------------------- #
# Where the author run ends — and, crucially, what closes it
# --------------------------------------------------------------------------- #
# This one boundary is what every style-specific branch in refparse was really
# trying to find, and got wrong in a different way each time. Answering it
# structurally lets the CLOSING punctuation be reported rather than assumed —
# and that is the fact the whole bibliography then votes on. A style whose
# author run ends on a comma needs the opposite title rule to one that ends on
# a period, and a single entry cannot tell you which you are holding.
_NAMEISH = {"CAPWORD", "UCWORD", "WORD", "OTHER"}
_SEPS = {"COMMA", "SEMI", "AMP"}
_AND = {"and", "und", "et", "y", "e", "&"}
# An organisation standing where an author stands: "DoD, Levels of…",
# "NASA, Mars Climate Orbiter…", "OpenAI, 2024, GPT-4 technical report".
_ORG = re.compile(r"^(?:[A-Z][A-Za-z&.]{1,11}|[A-Z][a-z]+(?: [A-Z][a-z]+){0,3})$")


def _skip_initials(cls: list[str], i: int) -> int:
    """Past a run of initials — UCLETT DOT repeated, dashes allowed so "T.-Y."
    stays one name. Returns i unchanged when there are none."""
    j = i
    while j + 1 < len(cls) and cls[j] == "UCLETT" and cls[j + 1] == "DOT":
        j += 2
        if j < len(cls) and cls[j] == "DASH":
            j += 1
    return j


def _skip_surname(cls: list[str], i: int) -> int:
    """Past a surname, allowing particles and double-barrels ("Li Puma",
    "van der Wilk") — at most three words."""
    j, n = i, 0
    while j < len(cls) and cls[j] in _NAMEISH and n < 3:
        j, n = j + 1, n + 1
    return j if n else i


def _one_name(cls: list[str], i: int, order: str | None,
              txt: list[str] | None = None) -> tuple[int, str] | None:
    """Parse ONE personal name at i.

    Once the bibliography's name order is known it is ENFORCED, and that is what
    stops a title's first word being read as another author: in
    "…, A. Ekedahl, WEST full tungsten operation", "WEST" is not a name, because
    in this style every author carries initials.
    """
    if order in (None, "given-first", "family-first-full"):
        j = _skip_initials(cls, i)
        if j > i:
            k = _skip_surname(cls, j)
            if k > j:
                return k, "given-first"
    if order in (None, "family-first"):
        k = _skip_surname(cls, i)
        if k > i and cls[k:k + 1] == ["COMMA"]:
            m = _skip_initials(cls, k + 1)
            if m > k + 1:
                return m, "family-first"                # "Smith, J."
    if order in (None, "family-first-full"):
        # "Kwon, Hyeyoung." / "Goldman, Anne." — the first author inverted with
        # a full given name, which Chicago and MLA both do and none of the
        # initials rules can see. A closing PERIOD is required: that is what
        # separates it from an organisation followed by a title
        # ("NASA, Mars Climate Orbiter, Mishap Investigation Board…").
        k = _skip_surname(cls, i)
        if k > i and cls[k:k + 1] == ["COMMA"]:
            j, n = k + 1, 0
            while j < len(cls) and cls[j] in ("CAPWORD", "UCWORD", "WORD") and n < 2:
                j, n = j + 1, n + 1
            if n and cls[j:j + 1] == ["DOT"]:
                return j, "family-first-full"
    if order in (None, "full-name", "family-first-full"):
        # "Mihály Héder." / "Ramanan Sekar, Oleh Rybkin" — given name spelled
        # out, no initials anywhere. ACM, Chicago and MLA all write names this
        # way and none of the initials-based rules can see them. Two words are
        # required when the order is still being established, because a single
        # capitalised word is indistinguishable from a Title Case title.
        # Chicago and MLA invert only the FIRST author, so once that has
        # established the order the rest are plain forenames-first names.
        need = 1 if order in ("full-name", "family-first-full") else 2
        n, j = 0, i
        while j < len(cls) and n < 4:
            if cls[j] in ("CAPWORD", "UCWORD", "WORD"):
                j, n = j + 1, n + 1
                continue
            # a middle initial inside a spelled-out name: "William A. Wieselquist"
            if cls[j] == "UCLETT" and cls[j + 1:j + 2] == ["DOT"] and n:
                j += 2
                continue
            break
        # Falls THROUGH when it does not match — the Vancouver rule below still
        # needs its turn, and an early return here hid it.
        # "Rose ME," is a surname and initials, not the two-word name "Rose Me":
        # when the order is still open and the name ENDS in a short caps run,
        # leave it to the Vancouver rule, or the whole entry is voted
        # full-name and its last single-initial author ("Melick J.") is lost.
        initials_last = (order is None and n == 2 and cls[j - 1] == "UCWORD"
                         and txt is not None and len(txt[j - 1]) <= 3)
        if n >= need and cls[j:j + 1] and not initials_last:
            # "Ugur Mertyurek and William A. Wieselquist." — only a real joiner
            # may close the name. Any lowercase word would let a Title Case
            # title ("Transition Core Modeling for…") parse as another author.
            if cls[j] in ("DOT", "COMMA", "SEMI", "AMP"):
                return j, "full-name"
            # ...and only a name of two or more words may close on "and": with
            # one, "Isotopic and fuel lattice parameter trends…" reads as an
            # author and the first word of the title is lost.
            if n >= 2 and cls[j] == "LCWORD" and txt and txt[j:j + 1] and txt[j] in _AND:
                return j, "full-name"
    if order in (None, "family-initials"):
        # "Smith JD" / "Bucalossi J" / "Pitts RA" — Vancouver, Nature. A single
        # initial classes as UCLETT, so both are accepted; the absence of a
        # period is what separates this from given-first ("J. Smith").
        # The surname is matched shortest-first, because a greedy surname eats
        # the very initials that identify the style ("Pitts RA" → one name).
        for n in (1, 2, 3):
            k = i + n
            if k > len(cls) or not all(c in _NAMEISH for c in cls[i:k]):
                break
            # Once earlier names have fixed the order, "Parmar N." is the LAST
            # author with its closing period, not "N. Surname" given-first —
            # without this the final single-initial author fell into the title.
            if cls[k:k + 1] == ["UCWORD"] or (
                cls[k:k + 1] == ["UCLETT"]
                and (cls[k + 1:k + 2] != ["DOT"] or order == "family-initials")
            ):
                return k + 1, "family-initials"
    return None


def author_run(entry: str) -> tuple[int, str, str] | None:
    """(token index where the authors end, the class CLOSING the run, the name
    order) — or None when the entry does not open with names."""
    toks = tokenize(entry)
    cls = [c for _, c, _, _ in toks]
    txt = [t.lower() for t, _, _, _ in toks]

    # An organisation may stand in for the whole author list, but only in first
    # position — anywhere else a capitalised run is the title or the venue.
    if cls[:1] and cls[0] in ("UCWORD", "CAPWORD", "WORD"):
        j = _skip_surname(cls, 0)
        if cls[j:j + 1] == ["COMMA"] and _one_name(cls, 0, None, txt) is None:
            if _ORG.match(" ".join(t for t, _, _, _ in toks[:j])):
                return j, "COMMA", "org"

    i, order, names, end_i, close = 0, None, 0, 0, "END"
    while True:
        r = _one_name(cls, i, order, txt)
        if r is None:
            break
        j, this_order = r
        order = order or this_order
        names += 1
        end_i = j

        k, sep = j, None
        while k < len(cls):
            if cls[k] == "DOT" and sep is None:
                sep, k = "DOT", k + 1
                continue
            if cls[k] in _SEPS:
                sep, k = sep or cls[k], k + 1
                continue
            if cls[k] == "LCWORD" and txt[k] in _AND:
                if txt[k] == "et" and txt[k + 1:k + 2] == ["al"]:
                    k = k + 2 + (1 if cls[k + 2:k + 3] == ["DOT"] else 0)
                    end_i, sep = k, "ETAL"
                    break
                sep, k = sep or "AND", k + 1
                continue
            break

        close = sep or "NONE"
        if sep is None:
            break
        if sep == "ETAL":
            # "…, A. Ekedahl, et al., et al., WEST full tungsten…" — a PDF
            # duplicates the marker often enough that consuming only one leaves
            # the second sitting at the head of the title.
            while True:
                while k < len(cls) and cls[k] in _SEPS | {"DOT"}:
                    close = cls[k]
                    k += 1
                if txt[k:k + 2] == ["et", "al"]:
                    k += 2
                    continue
                break
            i = end_i = k
            continue
        i = k
    if not names or order is None:
        return None
    return end_i, close, order


# --------------------------------------------------------------------------- #
# Anchors — the fields that carry an orthographic signature
# --------------------------------------------------------------------------- #
# Every evaluation of reference parsers finds the same thing: year, pages,
# volume and identifiers are extracted near-perfectly, while the venue is the
# worst field in every tool and the title/venue boundary is where parsers fail.
# The reason is that title and venue are the only two open-vocabulary
# title-case spans, and they sit adjacent with one punctuation mark between
# them. So the anchors are found and SUBTRACTED first, and the hard split is
# made on the short remainder rather than on the whole string.
_A_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;\]]+")
_A_URL = re.compile(r"https?://[^\s,;\]]+", re.IGNORECASE)
_A_ARXIV = re.compile(r"\barXiv[:\s]\s*\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
_A_ISBN = re.compile(r"\bISBN[:\s]*[\d][\d –-]{8,16}[\dX]", re.IGNORECASE)
_A_PAGES = re.compile(r"\bpp?\.\s*\d+(?:\s*[-–—]\s*\d+)?|\b\d{1,5}\s*[-–—]\s*\d{1,5}\b")
# "64 (11)", "12(3)", "5(2005/2006)" — a volume with its issue.
_A_VOLISS = re.compile(r"\b\d{1,4}\s*\(\s*\d{1,4}(?:\s*[/–-]\s*\d{1,4})?\s*\)")
_A_YEAR = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
# "Retrieved December 2019 from …", "Accessed 12 March 2021" — an access date is
# not the publication date, and it sits at the END of the entry where a
# last-year-wins rule is guaranteed to pick it up instead.
_A_ACCESSED = re.compile(
    r"\b(?:retrieved|accessed|last\s+accessed|viewed|downloaded|cited)\b"
    r"[^.;]{0,40}?(?:19|20)\d{2}",
    re.IGNORECASE,
)


def anchors(entry: str) -> list[tuple[int, int, str]]:
    """[(start, end, kind), …] for every high-signal span, left to right.

    Identifiers are matched first and the spans they cover are not offered to
    the weaker patterns — otherwise "arXiv:1905.12322" donates a "1905" year and
    a DOI tail donates a page range, which is how a 2019 paper came to be dated
    to 1905.
    """
    spans: list[tuple[int, int, str]] = []
    taken: list[tuple[int, int]] = []

    def add(rx: re.Pattern, kind: str) -> None:
        for m in rx.finditer(entry):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            spans.append((m.start(), m.end(), kind))
            taken.append((m.start(), m.end()))

    for rx, kind in (
        (_A_URL, "url"), (_A_ARXIV, "arxiv"), (_A_DOI, "doi"), (_A_ISBN, "isbn"),
        (_A_ACCESSED, "accessed"),
        (_A_VOLISS, "volume"), (_A_PAGES, "pages"), (_A_YEAR, "year"),
    ):
        add(rx, kind)
    return sorted(spans)


# --------------------------------------------------------------------------- #
# The venue gazetteer — small, and used at one decision only
# --------------------------------------------------------------------------- #
# Every system that does well on venue carries a gazetteer, and none of them
# needs one anywhere else. These are the closed-class words that open or close
# a container title; they are deliberately generic, because the alternative is
# a list of journal names that can never be complete.
_VENUE_WORD = re.compile(
    r"\b(?:journal|proceedings|proc|conference|conf|symposium|workshop|congress|"
    r"transactions|trans|review|revue|bulletin|annals|acta|archiv|zeitschrift|"
    r"quarterly|letters|reports|advances|studies|magazine|newsletter|"
    r"press|publishers?|publishing|books?|edition|eds?|editors?|"
    r"university|univ|college|institute|academic|society|association|"
    r"council|department|ministry|agency|administration|board|commission|"
    r"office|bureau|laborator(?:y|ies)|centre|center|corporation|foundation|"
    r"springer|elsevier|wiley|routledge|sage|pergamon|blackwell|mit|oxford|"
    r"cambridge|pearson|prentice|mcgraw|addison|kluwer|ios|thesis|dissertation|"
    r"preprint|technical\s+report|working\s+paper|white\s*paper|deskbook|handbook)\b",
    re.IGNORECASE,
)
# "Nucl.", "Syst.", "Eng." — a journal abbreviation. One is enough: a title
# essentially never contains a capitalised word truncated by a period, whereas
# an abbreviated journal name is made of nothing else.
_ABBREV_TOKEN = re.compile(r"\b[A-Z][a-z]{1,5}\.(?:\s|$)")
# Corporate and place tails that close a publisher block rather than open one.
_IMPRINT = re.compile(r"\b(?:inc|ltd|llc|gmbh|co|corp|&\s*sons|and\s+sons)\b\.?", re.IGNORECASE)
# What can trail an author list without being a name: "et al.", and a
# collaboration credit ("J.E.T. contributors", "the ATLAS Collaboration").
_AUTHOR_TAIL = re.compile(
    r"^(?:[\s,.;&]*(?:et\s+al\.?"
    r"|[^,]{0,48}?\b(?:contributors?|collaborations?|collaborators?|consortium|"
    r"team|group)\b)[\s,.;]*)+",
    re.IGNORECASE,
)
# "In: Proceedings of…", "In Advances in…" — an explicit container marker.
_IN_MARKER = re.compile(r"^in:?\s+(?=[A-Z“\"])", re.IGNORECASE)
# "10th Biennial International Conference…", "1st International System
# Integration" — an ordinal opens a proceedings title, never an article title.
_ORDINAL_VENUE = re.compile(r"^\d{1,3}(?:st|nd|rd|th)\b", re.IGNORECASE)
# A bare acronym standing alone as a segment is the issuing body: "…, NASA, 1995".
# "NeurIPS", "IJCAI", "TACL" — and the mixed-case ones longer than six
# letters, which carry a second capital where a lone title word would not.
_BARE_ACRONYM = re.compile(r"^[A-Z][A-Za-z]{0,5}$|^(?:[A-Z]\.){2,4}$|^[A-Z][a-z]*[A-Z][A-Za-z]{0,8}$")
# "…, C.f.S. Engineering, ed., …" — the segment BEFORE an editor marker is a
# person, so the work's own title has already ended.
_LEADING_ACRONYM = re.compile(r"^(?:[A-Z]{2,}|[A-Z][a-z]*[A-Z][A-Za-z]*)\b(?!-)")
_EDITOR_MARK = re.compile(r"^\(?\s*(?:eds?|editors?)\b\.?\s*\)?[.,]?$", re.IGNORECASE)


def _is_venue_segment(seg: str, nxt: str = "") -> bool:
    seg = seg.strip()
    if not seg:
        return False
    return bool(
        _IN_MARKER.match(seg)
        or _VENUE_WORD.search(seg)
        or _ABBREV_TOKEN.search(seg)
        or _IMPRINT.search(seg)
        or _ORDINAL_VENUE.match(seg)
        or _BARE_ACRONYM.match(seg)
        or _EDITOR_MARK.match(nxt)
    )


# --------------------------------------------------------------------------- #
# Splitting the remainder into fields
# --------------------------------------------------------------------------- #
# An abbreviation is a capitalised word of at most five letters closed by a
# period — "Nucl.", "Syst.", "Eng.". A period after one of those is part of the
# word, not a field break, and splitting there is what turned "Nucl. Fusion"
# into a title.
_ABBREV_BEFORE = re.compile(
    r"(?:"
    r"\b[A-Z][a-z]{1,4}"                              # Nucl. Syst. Eng. Tech. Ph.
    # A lone capital closed by a period is an initial, not a sentence end. Without
    # this the D of "Ph.D. thesis" breaks the entry in half and the degree ends up
    # in the title: "Machine Super Intelligence, Ph.D" | "thesis, University of…".
    r"|\b[A-Z]"
    r")$"
)
# A quoted title is the one field boundary in this whole module that needs no
# heuristic at all. IEEE, Chicago, MLA and Harvard all quote the article title,
# and between them that is a large share of real bibliographies — so where the
# quotes exist, they are believed over everything else.
#
# The closing punctuation sits INSIDE the quote in IEEE ("…procedure,") and
# Chicago/MLA ("…Life."), so it is trimmed off the captured text rather than
# left to look like part of the title.
_QUOTED = re.compile(
    r"[“\"]\s*(?P<t>[^“”\"]{6,300}?)\s*[,.]?\s*[”\"]"      # “…,” / "…."
    r"|(?<![A-Za-z])[‘']\s*(?P<u>[^‘’']{6,300}?)\s*[,.]?\s*[’'](?![A-Za-z])"
)


def quoted_title(entry: str) -> tuple[str, int, int] | None:
    """(title, start, end) for a quoted title, or None. Exact where it fires."""
    m = _QUOTED.search(entry)
    if not m:
        return None
    text = (m.group("t") or m.group("u") or "").strip()
    if len(text.split()) < 2:
        return None
    return text, m.start(), m.end()
_IN_SPLIT = re.compile(r"[.,]\s+(?=[Ii]n:?\s+[A-Z“\"])")


def _split_fields(body: str, sep: str) -> list[tuple[str, int]]:
    """[(segment, offset), …] at the separator this bibliography actually uses."""
    cuts = [0]
    for m in _IN_SPLIT.finditer(body):
        cuts.append(m.end())
    if sep == "DOT":
        for m in re.finditer(r"\.\s+", body):
            if not _ABBREV_BEFORE.search(body[:m.start()]):
                cuts.append(m.end())
        # "…but are they necessary? In Advances in…" — a question mark ends a
        # title too. Whether what follows is still the title or the venue is
        # then decided by the venue test, not here.
        for m in re.finditer(r"[?!]\s+(?=[A-Z“\"]|arXiv\b)", body):
            cuts.append(m.end())
    else:
        for m in re.finditer(r",\s+", body):
            cuts.append(m.end())
    cuts = sorted(set(cuts))
    out = []
    for a, b in zip(cuts, cuts[1:] + [len(body)]):
        seg = body[a:b].strip().rstrip(",.;").strip()
        if seg:
            out.append((seg, a))
    return out


# --------------------------------------------------------------------------- #
# The ACL / NeurIPS-natbib head: "Names. YYYY. Title."
# --------------------------------------------------------------------------- #
# The year is a sentence of its own straight after the names, which makes it a
# firmer author/title boundary than `author_run` can find token by token — that
# walk stops at an initial without a period ("Jared D Kaplan", "Peter J Liu")
# or a particle run ("Henrique Ponde de Oliveira Pinto") and hands the rest of
# a 30-name list to the title.
NATBIB_YEAR = re.compile(r"\.\s+((?:19|20)\d{2})[a-z]?\.(?=\s|$)")
# Lowercase words a name run may hold: the joiners and the surname particles.
_NAME_LOWER = {"and", "et", "al", "al.", "de", "da", "di", "del", "della", "der",
               "den", "van", "von", "la", "le", "du", "dos", "das", "ter", "bin", "y"}


def is_name_run(run: str) -> bool:
    """Is this text (everything before ". YYYY.") a list of author names?"""
    run = run.strip()
    if not run or not run[0].isupper():
        return False
    # A sentence break means a title. A period may follow only an initial
    # ("Quoc V. Le", "C.Y. Chan") or "et al".
    for dot in re.finditer(r"\.", run):
        before = run[:dot.start()]
        if not (re.search(r"(?:^|[\s.\-])[^\W\d_]$", before) and before[-1].isupper()
                or before.endswith("et al")):
            return False
    words = [w.strip(",") for w in run.split() if w.strip(",")]
    stray = [w for w in words if w[0].islower() and w.lower() not in _NAME_LOWER]
    # One stray lowercase token is tolerated in a real list — a PDF's split
    # diacritic leaves "Piotr Pi˛ ekos". An unlisted run is a corporate author
    # ("BIG-bench collaboration") and must be short.
    listed = run.count(",") + len(re.findall(r"\band\b", run))
    if listed:
        return len(stray) <= (1 if listed >= 2 else 0)
    return len(words) <= 3 and len(stray) <= 1


def natbib_head(entry: str) -> tuple[int, int, int] | None:
    """(authors end, year, title start) for a "Names. YYYY. Title." entry."""
    m = NATBIB_YEAR.search(entry)
    if not m or m.start() > 900 or not is_name_run(entry[:m.start()]):
        return None
    return m.start(), int(m.group(1)), m.end()


@dataclass
class Profile:
    """What one bibliography does, decided by voting over all of its entries."""
    order: str = "given-first"      # given-first | family-first | family-initials
    sep: str = "COMMA"              # what closes the author run: COMMA | DOT
    date_pos: str = "last"          # last (numeric family) | second (author-date)
    marker: str = "none"            # bracket | dotted | none
    quoted: bool = False            # the article title sits in quotes
    entries: int = 0
    agreement: float = 0.0

    @property
    def family(self) -> str:
        return "author-date" if self.date_pos == "second" else "numeric"


def detect(raws: list[str]) -> Profile:
    """Vote a style profile across the whole bibliography.

    Voting is the entire point. Any single entry is ambiguous — a period after
    an author's initial is indistinguishable from a period closing the author
    run — but forty entries in one style are not, and the majority answer is
    then applied to the ambiguous ones instead of a guess.
    """
    orders: dict[str, int] = {}
    seps: dict[str, int] = {}
    early_year = dated = markers = dotted = quoted = 0
    for raw in raws:
        body = re.sub(r"^\s*\[?\d{1,3}[\]).]\s+", "", raw)
        if body != raw:
            markers += 1
            dotted += 1 if re.match(r"^\s*\d{1,3}[).]", raw) else 0
        run = author_run(body)
        if run:
            end, close, order = run
            orders[order] = orders.get(order, 0) + 1
            if close in ("COMMA", "DOT"):
                seps[close] = seps.get(close, 0) + 1
            elif order in ("family-first", "family-initials"):
                # the period closing the last initial IS the field break here
                seps["DOT"] = seps.get("DOT", 0) + 1
            toks = tokenize(body)
            tail = body[toks[end][2]:] if end < len(toks) else ""
        else:
            tail = None
        quoted += 1 if quoted_title(body) else 0
        if tail is not None:
            dated += 1
            if re.match(r"^[\s,.;&]*\(?\s*(?:19|20)\d{2}", tail):
                early_year += 1

    n = max(len(raws), 1)
    order = max(orders, key=orders.get) if orders else "given-first"
    sep = max(seps, key=seps.get) if seps else "COMMA"
    return Profile(
        order=order,
        sep=sep,
        date_pos="second" if early_year > max(dated, 1) / 2 else "last",
        marker=("dotted" if dotted > markers / 2 else "bracket") if markers > n / 2 else "none",
        quoted=quoted > n / 2,
        entries=len(raws),
        agreement=(orders.get(order, 0) / n) if orders else 0.0,
    )


def _venue_of(rest: str) -> str:
    """What follows a quoted title, up to the first anchor — the container."""
    rest = _IN_MARKER.sub("", rest.strip())
    cut = min((a for a, _, _ in anchors(rest)), default=len(rest))
    v = re.search(r",?\s*\b(?:vol|no|iss|pp?)\b\.?\s*\d", rest, re.IGNORECASE)
    if v:
        cut = min(cut, v.start())
    # "American Journal of Sociology 127" — a bare volume trailing the name.
    v = re.sub(r"[\s,]*\d{1,4}$", "", re.sub(r"\s+", " ", rest[:cut])).strip(" ,;:")
    # A trailing period belongs to the abbreviation, not to the sentence:
    # "IEEE Trans. Biomed. Eng." must not be trimmed to "…Eng".
    while v.endswith(".") and not _ABBREV_BEFORE.search(v[:-1]):
        v = v[:-1].strip(" ,;:")
    return v


def fields(raw: str, profile: Profile) -> dict:
    """One entry + the bibliography's profile → its fields.

    Anchors are subtracted, the author run is cut with the profile's rules, and
    only the short remainder is split into title and venue.
    """
    entry = re.sub(r"^\s*\[?\d{1,3}[\]).]\s+", "", raw).strip()
    spans = anchors(entry)
    out: dict = {k: None for k in
                 ("title", "venue", "year", "volume", "pages", "doi", "url", "authors")}
    found: dict[str, str] = {}
    for a, b, kind in spans:
        found.setdefault(kind, entry[a:b].rstrip(".,;"))
    if found.get("arxiv"):
        # store the resolvable form, not the bare identifier
        aid = re.search(r"\d{4}\.\d{4,5}(?:v\d+)?", found["arxiv"])
        found["arxiv"] = f"https://arxiv.org/abs/{aid.group(0)}" if aid else ""
    # a literal URL beats a DOI, which beats an arXiv id — all three are taken
    # from characters that appeared in the entry, never inferred
    out["url"] = found.get("url") or found.get("arxiv") or None
    out["doi"] = found.get("doi") or None
    for a, b, kind in spans:
        if kind == "volume" and out["volume"] is None:
            out["volume"] = entry[a:b]
        elif kind == "pages" and out["pages"] is None:
            out["pages"] = entry[a:b]

    run = author_run(entry)
    head = natbib_head(entry) if profile.date_pos == "second" else None
    if head:
        out["authors"] = entry[:head[0]].strip().rstrip(",.;& ")
        out["year"] = head[1]
        body = entry[head[2]:]
    elif run:
        end, _, _ = run
        toks = tokenize(entry)
        cut = toks[end][2] if end < len(toks) else len(entry)
        out["authors"] = entry[:cut].strip().rstrip(",.;& ")
        body = entry[cut:]
    else:
        body = entry
    # "…, J.E.T. contributors, et al., Long plasma duration…" — a collaboration
    # note closes an author list without being a name, so it survives the run
    # and lands at the head of the title. GROBID gives this its own label
    # (orgName type="collaboration"); here it is simply dropped.
    # Not after a "Names. YYYY." head: the year already closed the authors, and
    # the title may itself open on the word ("Reframing human-AI collaboration…").
    if not head:
        body = _AUTHOR_TAIL.sub("", body)
    body = body.lstrip(" ,.;&")

    # An author-date style puts the year here, between the authors and the title.
    if profile.date_pos == "second" and not head:
        m = re.match(r"^\(?\s*((?:19|20)\d{2})[a-z]?(?:\s*ff)?\s*\)?[.,]?\s*", body, re.I)
        if m:
            out["year"] = int(m.group(1))
            body = body[m.end():]
    if out["year"] is None:
        years = [entry[a:b] for a, b, k in spans if k == "year"]
        parens = re.findall(r"\((?:19|20)\d{2}[a-z]?\)", entry)
        if parens:
            out["year"] = int(parens[-1][1:5])
        elif years:
            out["year"] = int((years[0] if profile.date_pos == "second" else years[-1])[:4])
        else:
            # "…Management 5(2005/2006), 261–280." — the volume anchor claimed
            # the only year in the entry. Look inside it rather than return None.
            inside = re.findall(r"(?:19|20)\d{2}", " ".join(
                entry[a:b] for a, b, k in spans if k in ("volume", "pages")))
            out["year"] = int(inside[-1]) if inside else None

    if profile.quoted:
        q = quoted_title(body)
        if q:
            out["title"], _, qe = q
            rest = body[qe:].strip(" ,.;")
            out["venue"] = _venue_of(rest) or None
            return out

    segs = _split_fields(body, profile.sep)
    if not segs:
        return out
    first_anchor = min((a for a, _, _ in spans if a >= len(entry) - len(body)), default=len(entry))
    base = len(entry) - len(body)

    # "S. Hu, 2024, Large language model meets…" — some entries in a numeric
    # bibliography still carry the year here. A segment that is nothing but a
    # year is a date wherever it sits; it is never a title.
    while segs and re.fullmatch(r"\(?(?:19|20)\d{2}[a-z]?(?:\s*ff)?\)?", segs[0][0], re.I):
        out["year"] = out["year"] or int(re.search(r"\d{4}", segs[0][0]).group())
        segs = segs[1:]
    if not segs:
        return out

    title, venue = [], []
    t_start = t_end = 0
    nxt = {off: segs[i + 1][0] if i + 1 < len(segs) else "" for i, (_, off) in enumerate(segs)}
    for seg, off in segs:
        abs_end = base + off + len(seg)
        in_anchor = abs_end > first_anchor
        if not title:
            title.append(seg)
            t_start, t_end = off, body.index(seg, off) + len(seg)
            continue
        # "NAACL Findings", "CHI Extended Abstracts", "NeurIPS Track on…": the
        # LAST segment opening on a conference acronym is the venue.
        last_acronym = off == segs[-1][1] and _LEADING_ACRONYM.match(seg)
        if venue or in_anchor or last_acronym or _is_venue_segment(seg, nxt.get(off, "")):
            venue.append(seg)
        else:
            title.append(seg)
            t_end = body.index(seg, off) + len(seg)
    # The title is sliced from the entry, not re-joined: a title that runs on
    # past a "?" or "!" ("Did aristotle use a laptop? A question answering…")
    # keeps its own punctuation instead of gaining a comma.
    t = _IN_MARKER.sub("", re.sub(r"\s+", " ", body[t_start:t_end]).strip())  # "in: Proceedings…"
    out["title"] = re.sub(r",\s*\(?(?:19|20)\d{2}[a-z]?\)?$", "",
                          t.strip().rstrip(".,;").strip()) or None
    out["venue"] = ", ".join(venue).strip().rstrip(".,;").strip() or None
    return out
