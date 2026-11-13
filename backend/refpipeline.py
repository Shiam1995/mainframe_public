"""The one way a bibliography becomes references.

Before this module there were two segmenters. `refparse.split_entries` served
the paste box; `synapse.references.parse.segment` served the PDF path. They did
the same job and the user-facing one was much the weaker of the two — on the
messy two-column fixture it found 2 entries where the other found 16, and on
the IOS Press fixture 49 where the truth is 34. Everything now goes through the
stronger one.

Field extraction prefers `refstyle`, which detects the bibliography's
structural style by voting across all of its entries and then extracts against
that style, and falls back to `refparse`'s literal rules for any single entry
the profile cannot place. Identifiers stay literal in both paths: a link is
only ever characters that appeared in the pasted text.
"""
from __future__ import annotations

import re

import refformats
import refparse
import refstyle
from synapse.references import parse as _segmenter


# A semicolon between two author names: an initial on the left ("Vaswani A;",
# "Smith, J.;") and a name on the right ("Shazeer N", "Jones, K."). Scopus,
# ACS and some Vancouver exports separate authors this way, and the author-run
# detector only knows commas and "and" — so "Vaswani A; Shazeer N; Parmar N."
# lost its last author into the title. A semicolon anywhere else ("…control;
# a review", "NeurIPS; 2017") is left exactly as it is.
_SEMI_AUTHORS = re.compile(
    r"(?<=[A-Z])(\.?)\s*;\s*"
    r"(?=[^\W\d_][^\W\d_'’-]*(?:[-'’][^\W\d_]+)*,?\s+[A-Z]{1,3}(?:\.|\b))")


def normalise_semicolons(raw: str) -> str:
    """Author-separating semicolons -> commas; every other semicolon untouched."""
    return _SEMI_AUTHORS.sub(r"\1, ", raw)


def segment(text: str) -> list[str]:
    """Bibliography text → one raw string per reference."""
    return [s["raw"] for s in _segmenter.segment(text)]


def parse(text: str) -> list[dict]:
    """Pasted bibliography → [{title, year, link, venue, authors, raw}].

    BibTeX, RIS and EndNote say where every field ends, so when the paste is
    one of those it is parsed exactly and none of the prose heuristics below
    ever run. People paste these constantly — it is what Zotero, Mendeley,
    JabRef and Google Scholar's "Cite" button hand out.
    """
    structured = refformats.parse(text)
    if structured:
        return [{
            "title": (r["title"] or "")[:300],
            "year": r["year"],
            "link": r["link"],
            "venue": r["venue"],
            "authors": r["authors"],
            "raw": r["raw"],
        } for r in structured if r["title"]]

    raws = segment(text)
    # Fields are read from the normalised text; `raw` is kept as pasted.
    clean = [normalise_semicolons(r) for r in raws]
    profile = refstyle.detect(clean)
    out: list[dict] = []
    for raw, norm in zip(raws, clean):
        f = refstyle.fields(norm, profile)
        title = f["title"] or ""
        # `refstyle` reads the structure; when it cannot place an entry against
        # the bibliography's profile, the literal rules still get a turn.
        if len(title) < 6:
            title = refparse.title_of(norm)
        if len(title) < 6:
            continue
        out.append({
            "title": title[:300],
            "year": f["year"] if f["year"] is not None else refparse.year_of(raw),
            "link": f["url"] or (f["doi"] and "https://doi.org/" + f["doi"])
                    or refparse.link_of(raw),
            "venue": f["venue"],
            "authors": f["authors"],
            "raw": raw[:400],
        })
    return out


def profile_of(text: str) -> refstyle.Profile:
    """The detected style, for showing the user what was recognised."""
    kind = refformats.sniff(text)
    if kind:
        return refstyle.Profile(order=kind, sep="-", date_pos="-",
                                marker="-", entries=0, agreement=1.0)
    return refstyle.detect(segment(text))
