"""Rescuing SHOUTED titles — and only the words that should come down.

A PDF's cover page often sets the title in caps, so the extractor stores
"AN IMAGE IS WORTH 16X16 WORDS: TRANSFORMERS FOR IMAGE RECOGNITION AT SCALE".
Lowercasing the string is not the fix: that same title holds "16x16", and
elsewhere in the repository sit "LLMs", "VLMs", "arXiv", "RISC-V" and
"ILSVRC-2012", every one of which a blanket `.lower()` destroys. The job is
therefore not "make it lowercase" but "decide, per word, whether its capitals
are POSITIONAL — there because a style rule put them there — or IDENTITY —
there because the word is spelled that way". Position is recomputed; identity
is preserved.

The interesting part is where the identity evidence comes from. It is already
here: 900+ reference titles and every stored abstract, a corpus that knows this
user's own vocabulary in a way no shipped acronym list would. Three rules make
it usable.

**Only non-positional forms are evidence.** In "ImageNet Classification with
Deep Convolutional Neural Networks", "Classification" is capitalised by title
case and says nothing about the word. "ImageNet" cannot be explained that way —
no positional rule produces an interior capital, and none produces "arXiv" or
"LLM". So a form counts only when it is all-caps or internally mixed; plain
Capitalised counts only mid-sentence in running prose, where the same argument
applies. This is the casing analogue of what `refstyle` does with punctuation:
discard everything a style rule could have caused, and read what is left.

**A shouting source cannot vouch for itself.** Any text that is itself mostly
caps is excluded from the corpus. Without that, "QWEN TECHNICAL REPORT" is its
own proof that "QWEN" is an acronym and every title stays as broken as it was.

**Evidence is counted in documents, not mentions.** The Qwen abstract writes
"QWEN" thirty times; it is still one opinion, and one document that spells a
name its own way should not outvote a library. Sightings are deduplicated per
source, so the confidence attached to a spelling reads "how many independent
documents agree", which is the number that should move it.

What is left over — a word in caps, absent from the corpus in lowercase and
absent from the system dictionary — is the honest unknown. It is lowercased
(the base rate says ordinary word) but its title is scored below the review
threshold rather than quietly changed, which is why this module returns a
reason and a confidence per word instead of just a string.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Tokenising
# --------------------------------------------------------------------------- #
# A "word" is a run of letters/digits, optionally joined by internal hyphens or
# apostrophes: "16X16", "RISC-V", "STATE-OF-THE-ART", "DON'T". The class is
# `[^\W_]` rather than `[A-Za-z0-9]` for the reason refstyle gives — an ASCII
# class cuts "Jabłoński" into pieces and loses the word entirely.
_JOINERS = "'’-‐‑‒–—―"
_WORD = re.compile(rf"[^\W_]+(?:[{re.escape(_JOINERS)}][^\W_]+)*")
_SPLIT = re.compile(rf"[{re.escape(_JOINERS)}]")
# Punctuation after which the next word is capitalised by position in either
# style, so its capital carries no information about the word itself.
_BREAKS = set(".:!?")
_VOWELS = set("AEIOUY")

# Title case lowercases these unless position forces otherwise: the classic
# short-function-word set. Anything longer stays capitalised.
MINOR_WORDS = {
    "a", "an", "the", "and", "as", "at", "but", "by", "en", "for", "from",
    "if", "in", "into", "nor", "of", "off", "on", "onto", "or", "over", "per",
    "so", "than", "to", "up", "upon", "versus", "via", "vs", "with", "within",
    "without", "yet",
}
_ROMAN = re.compile(r"^(?=[MDCLXVI]+$)M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
# Endings no acronym has. The dependency-free half of the ordinary-word test,
# for a machine with no word list installed.
_ENGLISH_SUFFIXES = ("ing", "tion", "sion", "ment", "ness", "ity", "ally", "ised", "ized")

# The review threshold the references pipeline already uses. A title below it
# is proposed but not trusted.
REVIEW_THRESHOLD = 0.80

# Spellings no local corpus can be expected to witness. Deliberately tiny — the
# corpus does the work and a list like this rots. Extend it per machine with
# ~/.mainframe/config/recase_words.txt, one spelling per line.
BUILTIN_FORMS = ["arXiv", "PhD", "DNA", "3D", "2D", "AI", "ML", "IEEE", "ACM"]

_WORDLISTS = ("/usr/share/dict/words", "/usr/share/dict/american-english")


def _is_mixed(form: str) -> bool:
    """True when the capitals sit where no positional rule could have put them."""
    return form != form.lower() and form != form.upper() and form != form.capitalize()


def _letters(form: str) -> str:
    return "".join(c for c in form if c.isalpha())


def shouting(text: str) -> bool:
    """Is this text set in caps — i.e. useless as casing evidence?

    Measured over cased letters, so digits and punctuation neither help nor
    hurt, and it takes a few of them so "AI" is not mistaken for a shout.
    """
    cased = [c for c in text if c.isalpha()]
    if len(cased) < 3:
        return False
    return sum(1 for c in cased if c.isupper()) / len(cased) >= 0.9


def parts(token: str) -> list[str]:
    """"RISC-V" -> ["RISC", "V"]. Each half is decided on its own."""
    return [p for p in _SPLIT.split(token) if p]


def _joiners_in(token: str) -> list[str]:
    return [c for c in token if c in _JOINERS]


def load_english(paths: tuple[str, ...] = _WORDLISTS) -> frozenset[str]:
    """Lowercase entries of the system word list, or empty if there is none.

    Only the lowercase entries: the list holds proper nouns too, and those are
    exactly the words whose capitals we must not throw away.
    """
    for p in paths:
        f = Path(p)
        if f.is_file():
            try:
                words = f.read_text(encoding="utf-8", errors="ignore").split()
            except OSError:
                continue
            return frozenset(w for w in words if w.islower() and len(w) > 1)
    return frozenset()


def load_proper(paths: tuple[str, ...] = _WORDLISTS) -> frozenset[str]:
    """Capitalised entries of the system word list ("Bayesian", "Python").

    Only `sentence_case` reads these. A Title Case title capitalises every
    word, so the capital itself is no evidence; the dictionary saying the word
    is a name is.
    """
    for p in paths:
        f = Path(p)
        if f.is_file():
            try:
                words = f.read_text(encoding="utf-8", errors="ignore").split()
            except OSError:
                continue
            return frozenset(w for w in words
                             if w[:1].isupper() and w[1:].islower() and "'" not in w)
    return frozenset()


def load_user_forms(path: Path | None = None) -> list[str]:
    """Extra spellings, one per line, ~/.mainframe/config/recase_words.txt.

    The escape hatch for a word this repository happens never to spell right:
    put "XiheFusion" there and it is honoured from then on, no code change.
    """
    if path is None:
        path = Path.home() / ".mainframe" / "config" / "recase_words.txt"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# The evidence
# --------------------------------------------------------------------------- #
@dataclass
class Lexicon:
    """How this repository spells things, learned from this repository.

    `strong` holds forms no positional rule could have produced (all-caps or
    internally mixed), counted in documents. `prose` holds Capitalised
    mid-sentence sightings — proper-noun evidence, weaker — against the
    lowercase sightings that argue the other way. `seen_lower` is the backstop:
    a word the corpus has ever written in lowercase is an ordinary word,
    whatever a shouting cover page did to it.
    """

    strong: dict[str, Counter] = field(default_factory=dict)
    prose: dict[str, Counter] = field(default_factory=dict)
    seen_lower: set[str] = field(default_factory=set)
    english: frozenset[str] = frozenset()
    proper: frozenset[str] = frozenset()
    sources: int = 0

    def observe(self, text: str, *, running_prose: bool = False) -> None:
        """Fold one title or abstract into the evidence. Shouts are ignored.

        Forms are gathered into a set before counting, so a document repeating
        its own name a hundred times still casts a single vote.
        """
        if not text or shouting(text):
            return
        self.sources += 1
        strong_here: set[str] = set()
        prose_here: set[str] = set()
        prev_break = True  # the first word is capitalised by position
        for m in _WORD.finditer(text):
            token = m.group(0)
            positional = prev_break
            prev_break = text[m.end():m.end() + 2].lstrip()[:1] in _BREAKS
            forms = [token, *parts(token)] if len(parts(token)) > 1 else [token]
            for form in forms:
                if not _letters(form):
                    continue
                if form.islower():
                    self.seen_lower.add(form.lower())
                    if running_prose and not positional:
                        prose_here.add(form)
                elif _is_mixed(form) or (form.isupper() and len(_letters(form)) >= 2):
                    strong_here.add(form)
                elif running_prose and not positional:
                    prose_here.add(form)
        for form in strong_here:
            self.strong.setdefault(form.lower(), Counter())[form] += 1
        for form in prose_here:
            self.prose.setdefault(form.lower(), Counter())[form] += 1

    # -- lookups ----------------------------------------------------------- #
    def identity(self, form: str) -> tuple[str, int] | None:
        """The corpus spelling of this word, and how many documents back it."""
        counts = self.strong.get(form.lower())
        if not counts:
            return None
        return counts.most_common(1)[0]

    def proper_noun(self, form: str) -> tuple[str, int] | None:
        """Capitalised mid-sentence, in prose, more often than not."""
        counts = self.prose.get(form.lower())
        if not counts:
            return None
        best, n = counts.most_common(1)[0]
        if best.islower() or n < 2 or n / sum(counts.values()) < 0.7:
            return None
        return best, n

    def ordinary(self, form: str) -> bool:
        """An ordinary word, whose capitals here can only be the shout."""
        word = form.lower()
        return (word in self.seen_lower or word in MINOR_WORDS or word in self.english
                or (len(word) >= 6 and word.endswith(_ENGLISH_SUFFIXES)))


def build_lexicon(titles: list[str], prose: list[str],
                  extra_forms: list[str] | None = None,
                  english: frozenset[str] | None = None,
                  proper: frozenset[str] | None = None) -> Lexicon:
    """Titles give strong evidence only; prose also witnesses proper nouns."""
    lex = Lexicon(english=load_english() if english is None else english,
                  proper=(load_proper() if english is None else frozenset())
                  if proper is None else proper)
    forms = BUILTIN_FORMS + (load_user_forms() if extra_forms is None else extra_forms)
    for form in forms:
        # Curated spellings enter as strong evidence with a decisive document
        # count, so one stray sighting in the corpus cannot outvote them.
        lex.strong.setdefault(form.lower(), Counter())[form] += 99
    for t in titles:
        lex.observe(t)
    for p in prose:
        lex.observe(p, running_prose=True)
    return lex


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
@dataclass
class Word:
    source: str      # as it stands
    result: str      # as it is proposed
    reason: str      # which rule decided it
    confidence: float


@dataclass
class Recased:
    original: str
    proposed: str
    words: list[Word]
    confidence: float
    skipped: str = ""      # set when the title was deliberately left alone

    @property
    def changed(self) -> bool:
        return self.proposed != self.original

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD

    @property
    def uncertain(self) -> list[Word]:
        return [w for w in self.words if w.confidence < REVIEW_THRESHOLD]


def _structural(token: str) -> tuple[str, str, float] | None:
    """Forms decidable from shape alone, with no corpus at all."""
    alpha = _letters(token)
    if not alpha:
        return token, "no-letters", 0.95
    if any(c.isdigit() for c in token):
        # "16X16", "GPT4": the shape is not a word, and the letters are small.
        return token.lower(), "alphanumeric", 0.85
    if token.isupper() and len(alpha) >= 2 and _ROMAN.match(alpha):
        return token, "roman-numeral", 0.9
    if token.isupper() and len(alpha) >= 2:
        # No vowel at all (LLM, VLMS, KGN). English words have one; acronyms
        # need not. A trailing S is the plural, and comes down with the rest.
        base = alpha[:-1] if alpha.endswith("S") and len(alpha) > 2 else alpha
        if len(base) >= 2 and not (set(base) & _VOWELS):
            return (base + "s" if base is not alpha else alpha), "no-vowels", 0.85
    return None


def _cap(word: str) -> str:
    return word[:1].upper() + word[1:]


def _positional(token: str, *, first: bool, last: bool, after_break: bool, style: str,
                head: bool = False) -> str:
    """Apply the target style to a word whose capitals are ours to choose.

    Hyphenated compounds are cased part by part, so title case gives
    "In-Context" and "State-of-the-Art" rather than "In-context". `head` marks
    the opening element of such a compound: it is capitalised even when it is a
    minor word, which is what makes "In-" come up with "-Context".
    """
    halves = parts(token)
    if len(halves) > 1:
        seps = _joiners_in(token)
        out = [_positional(halves[0], first=first, last=False, after_break=after_break,
                           style=style, head=True)]
        for j, half in enumerate(halves[1:], start=1):
            out.append(_positional(half, first=False, last=last and j == len(halves) - 1,
                                   after_break=False, style=style))
        return out[0] + "".join(s + p for s, p in zip(seps, out[1:]))
    lower = token.lower()
    if first or after_break:
        return _cap(lower)
    if style == "sentence":
        return lower
    if last or head:
        return _cap(lower)
    return lower if lower in MINOR_WORDS else _cap(lower)


def recase(title: str, lex: Lexicon, style: str = "title") -> Recased:
    """Propose a cased form of `title`, with a reason and a score per word.

    `style` is "title" (Title Case — the majority style in this repository) or
    "sentence" (only the first word, and words after a break, capitalised).
    Titles that are not shouting are returned untouched: this fixes the caps
    problem, it does not restyle a library.
    """
    spans = list(_WORD.finditer(title))
    if not spans:
        return Recased(title, title, [], 1.0, skipped="no words")
    # A one-word title is a name, not a sentence: "ILSVRC-2012", "Vetch".
    # Nothing in it is positional, so there is nothing to recompute.
    if len(spans) == 1:
        return Recased(title, title, [], 1.0, skipped="single-word title (a name)")
    if not shouting(title):
        return Recased(title, title, [], 1.0, skipped="not in caps")

    words: list[Word] = []
    out, cursor = [], 0
    prev_break = True
    for i, m in enumerate(spans):
        token = m.group(0)
        first, last, after_break = i == 0, i == len(spans) - 1, prev_break and i > 0
        follows = title[m.end():m.end() + 2].lstrip()[:1]
        prev_break = follows in _BREAKS
        w = _decide(token, lex, style=style, first=first, last=last, after_break=after_break,
                    pre_colon=first and follows == ":")
        words.append(w)
        out.append(title[cursor:m.start()])
        out.append(w.result)
        cursor = m.end()
    out.append(title[cursor:])

    return Recased(title, "".join(out), words, min(w.confidence for w in words))


def _decide(token: str, lex: Lexicon, *, style: str, first: bool, last: bool,
            after_break: bool, pre_colon: bool) -> Word:
    pos = dict(first=first, last=last, after_break=after_break, style=style)

    # 1. The corpus spells this word a way no style rule could have caused.
    #    One document alone is an opinion, not a consensus — hence the score.
    hit = lex.identity(token)
    if hit:
        form, docs = hit
        return Word(token, form, f"corpus·{min(docs, 99)}doc", 0.95 if docs >= 2 else 0.7)

    # 2. Shape alone settles it.
    st = _structural(token)
    if st:
        return Word(token, st[0], st[1], st[2])

    # 3. A compound, decided half by half: "RISC-V", "SURPRISE-GUIDED".
    halves = parts(token)
    if len(halves) > 1:
        pieces, confs = [], []
        for j, half in enumerate(halves):
            hit, st = lex.identity(half), _structural(half)
            if hit:
                pieces.append(hit[0])
                confs.append(0.95 if hit[1] >= 2 else 0.7)
            elif st:
                pieces.append(st[0])
                confs.append(st[2])
            else:
                pieces.append(_positional(
                    half, first=first and j == 0, last=last and j == len(halves) - 1,
                    after_break=after_break and j == 0, style=style, head=j == 0))
                confs.append(0.9 if lex.ordinary(half) else 0.6)
        seps = _joiners_in(token)
        merged = pieces[0] + "".join(s + p for s, p in zip(seps, pieces[1:]))
        return Word(token, merged, "compound", min(confs))

    # 4. First word of a "NAME: subtitle" construction, unattested elsewhere.
    #    That slot holds a name, so the capitals stay when they are short
    #    enough to be an initialism. Too long and it is a wordmark whose
    #    interior capitals cannot be recovered locally — "XIHEFUSION" could be
    #    XiheFusion, could be Xihefusion — so it is flagged, not guessed.
    if pre_colon and token.isupper():
        if len(_letters(token)) <= 6:
            return Word(token, token, "name before colon (kept)", 0.75)
        return Word(token, _positional(token, **pos), "wordmark (unknown)", 0.4)

    # 5. Written in lowercase somewhere, or a plain English word: ordinary, and
    #    its capitals here are the shout rather than the word.
    if lex.ordinary(token):
        return Word(token, _positional(token, **pos), "ordinary", 0.9)

    # 6. Capitalised mid-sentence in prose — a proper noun.
    pn = lex.proper_noun(token)
    if pn:
        return Word(token, pn[0], f"proper-noun·{pn[1]}doc", 0.8)

    # 7. Nothing knows this word. The base rate says ordinary — but say so.
    return Word(token, _positional(token, **pos), "unattested", 0.6)


# --------------------------------------------------------------------------- #
# Title Case -> sentence case
# --------------------------------------------------------------------------- #
# `recase` fixes shouts and leaves a correctly Title-Cased title alone. This is
# the other job: "Hands-On Machine Learning with Scikit-Learn" -> "Hands-on
# machine learning with Scikit-learn". The argument inverts. In a shout every
# capital is noise; in Title Case only the INITIAL capital is noise, so any
# capital a style rule could not have placed (interior, or a whole word in
# caps) is identity and stays. The open question is the plain Capitalised
# word, and there the base rate flips: in Title Case an unknown Capitalised
# word is more often a name than not, so it keeps its capital.


def _sentence_word(form: str, lex: Lexicon, *, lead: bool) -> tuple[str, str, float]:
    """One hyphen-free word. `lead` = first word, or first after a break."""
    alpha = _letters(form)
    if not alpha:
        return form, "no-letters", 0.95
    if lead:
        # Position capitalises it whatever it is; keep identity spellings.
        hit = lex.identity(form)
        if hit and not (_is_mixed(form) or form.isupper()):
            return hit[0], f"corpus·{min(hit[1], 99)}doc", 0.95
        return (form if form[:1].isupper() else _cap(form)), "position", 0.95
    if form.islower():
        return form, "already lower", 0.95
    if _is_mixed(form) or (form.isupper() and len(alpha) >= 2) or any(c.isdigit() for c in form):
        return form, "identity (interior capitals)", 0.95
    if len(alpha) == 1:
        # "A" and "I" are words; any other lone capital is a name: "C", "R".
        return (form.lower(), "ordinary", 0.9) if form == "A" else (form, "single letter", 0.9)
    hit = lex.identity(form)
    if hit:
        return hit[0], f"corpus·{min(hit[1], 99)}doc", 0.95 if hit[1] >= 2 else 0.7
    pn = lex.proper_noun(form)
    if pn:
        return pn[0], f"proper-noun·{pn[1]}doc", 0.8
    word, cap = form.lower(), form.capitalize()
    in_proper = cap in lex.proper
    in_lower = word in lex.english or word in lex.seen_lower or word in MINOR_WORDS
    if in_proper and in_lower:
        # "Python", "Swift": a name and a word. Keep the capital, ask.
        return cap, "name or word (kept)", 0.7
    if in_proper:
        return cap, "proper noun (dictionary)", 0.85
    if in_lower or (len(word) >= 6 and word.endswith(_ENGLISH_SUFFIXES)):
        return word, "ordinary", 0.9
    return form, "unattested (kept as a name)", 0.6


def sentence_case(title: str, lex: Lexicon) -> Recased:
    """Only the first word (and the first after ':' '.' '?' '!') capitalised.

    Shouted titles go through `recase` in sentence style first, so both inputs
    land in the same place.
    """
    if shouting(title):
        return recase(title, lex, style="sentence")
    spans = list(_WORD.finditer(title))
    if len(spans) < 2:
        return Recased(title, title, [], 1.0, skipped="single-word title (a name)")
    words: list[Word] = []
    out, cursor, prev_break = [], 0, True
    for m in spans:
        token = m.group(0)
        lead = prev_break
        prev_break = title[m.end():m.end() + 2].lstrip()[:1] in _BREAKS
        halves = parts(token)
        if len(halves) > 1:
            decided = [_sentence_word(h, lex, lead=lead and j == 0) for j, h in enumerate(halves)]
            seps = _joiners_in(token)
            result = decided[0][0] + "".join(s + d[0] for s, d in zip(seps, decided[1:]))
            w = Word(token, result, "compound", min(d[2] for d in decided))
        else:
            r, why, conf = _sentence_word(token, lex, lead=lead)
            w = Word(token, r, why, conf)
        words.append(w)
        out += [title[cursor:m.start()], w.result]
        cursor = m.end()
    out.append(title[cursor:])
    return Recased(title, "".join(out), words, min(w.confidence for w in words))


# --------------------------------------------------------------------------- #
# CLI — dry run over the graph, --apply to write
# --------------------------------------------------------------------------- #
def _main() -> int:
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="Recase SHOUTED titles in the graph.")
    ap.add_argument("--label", default="Paper", help="node label to fix (default: Paper)")
    ap.add_argument("--prop", default="title", help="property holding the title")
    ap.add_argument("--style", choices=["title", "sentence"], default="title")
    ap.add_argument("--sentence", action="store_true",
                    help="convert Title Case titles too, to sentence case (first letter only)")
    ap.add_argument("--where", default="",
                    help="extra Cypher filter on n, e.g. \"n.kind = 'book'\"")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--include-review", action="store_true",
                    help="with --apply, also write the titles flagged for review")
    args = ap.parse_args()

    async def run() -> int:
        from activity import record
        from db import close_driver, run_read, run_write

        # Evidence: every title and abstract in the graph. Shouted ones drop
        # out inside observe(), so the broken titles cannot vouch for
        # themselves or for each other.
        titles = [r["t"] for r in await run_read(
            "MATCH (n) WHERE n.title IS NOT NULL AND n.title <> '' RETURN n.title AS t")]
        prose = [r["t"] for r in await run_read(
            "MATCH (n) WHERE n.abstract IS NOT NULL AND n.abstract <> '' RETURN n.abstract AS t")]
        lex = build_lexicon(titles, prose)
        print(f"lexicon: {lex.sources} clean sources, {len(lex.strong)} identity spellings, "
              f"{len(lex.seen_lower)} words seen in lowercase, "
              f"{len(lex.english)} in the system word list\n")

        rows = await run_read(
            f"MATCH (n:{args.label}) WHERE n.{args.prop} IS NOT NULL "
            + (f"AND ({args.where}) " if args.where else "")
            + f"RETURN n.id AS id, n.{args.prop} AS title ORDER BY n.{args.prop}")
        fix = (lambda t: sentence_case(t, lex)) if args.sentence else \
              (lambda t: recase(t, lex, args.style))
        hits = [(r["id"], p) for r in rows if (p := fix(r["title"])).changed]

        written = 0
        for node_id, p in hits:
            print(f"{'!!' if p.needs_review else '  '} {p.original}\n"
                  f"   → {p.proposed}   [{p.confidence:.2f}]")
            for w in p.uncertain:
                print(f"      ? {w.source} → {w.result}   ({w.reason}, {w.confidence:.2f})")
            if args.apply and (not p.needs_review or args.include_review):
                await run_write(
                    f"MATCH (n:{args.label} {{id: $id}}) SET n.{args.prop} = $t",
                    id=node_id, t=p.proposed)
                await record("paper", "update", f"recased title: {p.proposed}",
                             entity_id=node_id, trigger="system")
                written += 1
            print()

        review = sum(1 for _, p in hits if p.needs_review)
        print(f"{len(hits)} of {len(rows)} {args.label} titles "
              f"{'change' if args.sentence else 'are in caps'}; "
              f"{review} flagged for review (!!).")
        if args.apply:
            print(f"wrote {written}." + ("" if args.include_review else
                  "  Flagged titles were left alone — add --include-review to write them too."))
        else:
            print("dry run — nothing written. Add --apply to write.")
        await close_driver()
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(_main())
