"""Elsevier / Vancouver comma style — authors, title and venue split on COMMAS.

The fixture is a real 41-entry fusion-and-LLM bibliography pasted out of a PDF.
Before `_comma_style_parse` existed the parser returned 25 references, and the
25 were mistitled: with no period closing the author run, the first "." in an
entry belongs to a journal abbreviation ("Nucl. Fusion"), so the title came back
as the venue — "Fusion 64 (11) (2024) 112022" — or as a bare DOI, and the 16
entries whose fragment was under six characters were dropped without a word.

The fixture also carries the three PDF artefacts that came with it: a dropped
"[" on entry 8, URLs wrapped mid-DOI with no hyphen, and fi/fl ligatures.
"""
from pathlib import Path

import refparse

FIXTURE = Path(__file__).parent / "fixtures" / "refs_elsevier.txt"


def _parsed() -> list[dict]:
    return refparse.parse(FIXTURE.read_text())


def test_every_reference_survives():
    assert len(_parsed()) == 41


def test_title_is_the_title_not_the_venue():
    p = _parsed()
    assert p[0]["title"] == "WEST full tungsten operation with an ITER grade divertor"
    assert p[36]["title"] == "Multilayer feedforward networks are universal approximators"


def test_title_keeps_its_own_commas():
    # "…detection, tracking, and classification…" is one title, not three.
    assert _parsed()[23]["title"].endswith(
        "detection, tracking, and classification of thermal events on the "
        "in-vessel components of fusion reactors"
    )


def test_dropped_opening_bracket_still_starts_an_entry():
    # The fixture's entry 8 reads "8] R. Cao, …" — no "[".
    assert _parsed()[7]["title"].startswith("DictPrompt:")


def test_year_between_authors_and_title():
    # "S. Hu, 2024, Large language model meets…" and "OpenAI, 2024, …"
    p = _parsed()
    assert (p[19]["year"], p[19]["title"]) == (
        2024, "Large language model meets graph neural network in knowledge distillation")
    assert (p[32]["year"], p[32]["title"]) == (2024, "PT-4 technical report")


def test_year_ignores_arxiv_ids_and_doi_tails():
    p = _parsed()
    assert p[39]["year"] == 2019      # not 1905, from "arXiv:1905.12322"
    assert p[16]["year"] == 2021      # not 2020, from the DOI tail
    assert p[15]["year"] == 2019      # not 2020, from the page range "2015–2020"


def test_wrapped_urls_are_rejoined_whole():
    links = [p["link"] for p in _parsed() if p["link"]]
    assert len(links) == 38
    assert all(len(l) > 25 and not l.endswith(("doi.", "/10.")) for l in links)
    # a DOI that legitimately contains parentheses keeps them
    assert _parsed()[36]["link"] == "https://doi.org/10.1016/0893-6080(89)90020-8"


def test_ligatures_normalised():
    titles = " ".join(p["title"] for p in _parsed())
    assert not any(c in titles for c in "ﬁﬂﬀﬃﬄ")
    assert "fine-tuning" in titles and "identification" in titles


def test_no_link_is_invented():
    # Entries 26, 32 and 41 carry no identifier at all in the source text.
    p = _parsed()
    assert p[25]["link"] is None and p[31]["link"] is None and p[40]["link"] is None
