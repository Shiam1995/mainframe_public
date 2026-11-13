"""Segmentation against the broken-layout fixture.

The fixture reproduces three real extraction failures (see parse.py):
detached [n] marker blocks, page furniture landing mid-reference across a
page break, and URLs wrapped with and without hyphens. Ground truth is 16
references — the hand-labelled rows in fixtures/refs_groundtruth.csv.
"""
from pathlib import Path

from synapse.references import parse

FIXTURE = Path(__file__).parent / "fixtures" / "refs_messy.txt"


def _segments() -> list[dict]:
    return parse.segment(FIXTURE.read_text())


def test_sixteen_segments():
    assert len(_segments()) == 16


def test_ordinals_reattached_positionally():
    # [1]..[10] and [11]..[16] appear as detached blocks; every entry must
    # still get the right ordinal back.
    assert [s["ordinal"] for s in _segments()] == list(range(1, 17))


def test_first_and_last_entries_intact():
    segs = _segments()
    assert segs[0]["raw"].startswith("Mihály Héder. 2017.")
    assert "ISSN: 1715-3816" in segs[0]["raw"]
    assert segs[-1]["raw"].startswith("Christopher Bauer. 2004.")
    assert "findarticles.com/p/articles/mi_m4153/is_3_61/ai_n6153200" in segs[-1]["raw"]


def test_furniture_stripped():
    for s in _segments():
        assert "Athens, Greece" not in s["raw"]          # running header
        assert "will be inserted" not in s["raw"]        # editorial placeholder


def test_url_rejoined_across_page_break():
    # The DoE URL was split mid-token by a page break WITH the running header
    # and a placeholder line sitting between its two halves.
    doe = _segments()[9]["raw"]
    assert "0413.3-EGuide-04@@images/file" in doe


def test_url_rejoined_no_hyphen():
    tallinn = _segments()[3]["raw"]
    assert "document.cfm?doc_id=47559" in tallinn


def test_author_year_first_line_not_split():
    # "…Sivarajah. 2016." ends the first LINE of entry 7 — a year-period that
    # must not be read as the end of the ENTRY.
    seg7 = _segments()[6]["raw"]
    assert seg7.startswith("Hamad Al-Muftah")
    assert "Qualitative" in seg7 and "10.3233/978-1-61499-670-5-69" in seg7


def test_complete_url_does_not_swallow_next_entry():
    # Entry 12 ends in a COMPLETE URL ("…index-primer/"); the wrap-repair must
    # not glue entry 13's first word onto it.
    segs = _segments()
    assert segs[11]["raw"].endswith("technology-readiness-index-primer/")
    assert segs[12]["raw"].startswith("Innovation Fund Denmark. 2018.")


# --------------------------------------------------------------------------- #
# IOS Press / Elsevier style: initials-first authors ("M. Austin, J. Zakar,…"),
# org-acronym authors ("DoD,", "NASA,"), and NO DOIs or URLs anywhere — every
# entry ends on a bare year or page range. The style that returned 1 segment
# instead of 34 before the soft-end/strong-start rules covered it.
# --------------------------------------------------------------------------- #
IOS_FIXTURE = Path(__file__).parent / "fixtures" / "refs_ios_style.txt"


def _ios_segments() -> list[dict]:
    return parse.segment(IOS_FIXTURE.read_text())


def test_ios_style_thirty_four_segments():
    assert len(_ios_segments()) == 34


def test_ios_style_org_authors_split():
    # Three consecutive DoD entries and two NASA entries must not merge.
    starts = [s["raw"][:40] for s in _ios_segments()]
    assert sum(1 for s in starts if s.startswith("DoD,")) == 3
    assert sum(1 for s in starts if s.startswith("NASA,")) == 2


def test_ios_style_page_range_closes_entry():
    segs = _ios_segments()
    assert segs[3]["raw"].startswith("R.T. Brooks")      # ends "261–280."
    assert segs[3]["raw"].endswith("261–280.")
    assert segs[4]["raw"].startswith("D.M. Buede")


def test_ios_style_same_author_twice_not_merged():
    segs = _ios_segments()
    mankins = [s for s in segs if s["raw"].startswith("J.C. Mankins")]
    assert len(mankins) == 2


def test_ios_style_dowling_p60_intact():
    # "…QINETIQ, 2005, p. 60." — the "p. 60." tail must close the entry
    # without the mid-entry "M.o. Defense, ed.," splitting it.
    seg = _ios_segments()[10]["raw"]
    assert seg.startswith("T. Dowling and T. Pardoe")
    assert seg.endswith("p. 60.")


def test_literal_identifiers_only():
    # Identifiers come from the text or not at all.
    ids = parse._literal_identifiers(_segments()[8]["raw"])   # Mankins
    assert ids["doi"] == "10.1016/j.actaastro.2009.03.058"
    ids = parse._literal_identifiers(_segments()[1]["raw"])   # H2020 annex
    assert ids["doi"] is None and ids["url"] is None


# --------------------------------------------------------------------------- #
# ICML/JMLR author-year style: surname-first authors whose run CLOSES on an
# initial ("…and Szepesvari, C. To believe…"), no markers, no blank lines, and
# a two-column PDF's wrapped venue tails repeating verbatim across entries.
# The style that returned the venue as every title, and lost six references to
# a running header and to non-ASCII surnames.
# --------------------------------------------------------------------------- #
AY_FIXTURE = Path(__file__).parent / "fixtures" / "refs_author_year.txt"


def _ay_segments() -> list[dict]:
    return parse.segment(AY_FIXTURE.read_text())


def _ay_fields() -> list[dict]:
    return [parse._heuristic_fields(s["raw"]) for s in _ay_segments()]


def test_author_year_one_hundred_segments():
    assert len(_ay_segments()) == 100


def test_author_year_repeated_venue_tail_is_not_furniture():
    # "Systems, 2022." and "Information Processing Systems, 2020." each close
    # two different entries. Stripping every repeated line deletes the end of a
    # reference — and its year — and merges the next entry into it.
    segs = _ay_segments()
    assert segs[1]["raw"].endswith("Processing Systems, 2022.")
    assert segs[20]["raw"].endswith("Information Processing Systems, 2020.")


def test_author_year_running_header_still_stripped():
    for s in _ay_segments():
        assert "should be Bayes-consistent" not in s["raw"]
    assert not _ay_segments()[0]["raw"].startswith("References")


def test_author_year_title_is_the_title_not_the_venue():
    titles = [f["title"] for f in _ay_fields()]
    assert titles[0] == (
        "To believe or not to believe your LLM: Iterative prompting for "
        "estimating epistemic uncertainty"
    )
    assert titles[17] == "A general framework for updating belief distributions"
    assert not any(t.startswith("In ") for t in titles)


def test_author_year_acronym_ending_a_title_is_not_an_initial():
    # "…in the age of large-scale AI." — "AI" read as initials made the author
    # run swallow the title.
    assert _ay_fields()[72]["title"] == (
        "Position: Bayesian deep learning is needed in the age of large-scale AI"
    )


def test_author_year_question_mark_does_not_end_a_title_early():
    titles = [f["title"] for f in _ay_fields()]
    assert titles[5] == (
        "What learning algorithm is in-context learning? Investigations with "
        "linear models"
    )
    # …but a venue after the question mark still ends it.
    assert titles[1] == "Deep ensembles work, but are they necessary?"


def test_author_year_suffixed_years_parse():
    # "2025a" / "2025b" disambiguate two papers by the same authors.
    assert [f["year"] for f in _ay_fields()[2:4]] == [2025, 2025]


def test_author_year_non_ascii_surnames_open_entries():
    starts = [s["raw"][:12] for s in _ay_segments()]
    assert any(s.startswith("Akyürek") for s in starts)
    assert any(s.startswith("Särkkä") for s in starts)


def test_author_year_publisher_line_does_not_start_an_entry():
    # "CRC Press, 3rd edition, 2013." reads like "Surname, …" but is the tail
    # of the Gelman entry.
    seg = _ay_segments()[34]["raw"]
    assert seg.startswith("Gelman") and seg.endswith("CRC Press, 3rd edition, 2013.")


def test_author_year_url_split_at_its_scheme_is_rejoined():
    seg = _ay_segments()[47]["raw"]
    assert "https://kellerjordan.github.io/posts/muon/" in seg
    assert parse._literal_identifiers(seg)["url"] == (
        "https://kellerjordan.github.io/posts/muon/"
    )


def test_author_year_compound_keeps_its_hyphen_across_a_line_break():
    # "Model-\nbased" is a real hyphen; "Szepes-\nvari" is not.
    assert _ay_fields()[32]["title"].startswith("Model-based lifelong")
    assert "Szepesvari" in _ay_segments()[0]["raw"]


def test_author_year_authors_without_the_llm():
    authors = _ay_fields()[0]["authors"]
    assert [a["family"] for a in authors] == [
        "Abbasi-Yadkori", "Kuzborskij", "György", "Szepesvari"
    ]
    assert [a["given"] for a in authors] == ["Y", "I", "A", "C"]
    # a particle surname stays whole
    assert "van der Wilk" in [a["family"] for a in _ay_fields()[66]["authors"]]


# --------------------------------------------------------------------------- #
# Lone markers: "[25]" on its own line, its reference on the next
# --------------------------------------------------------------------------- #
LONE_FIXTURE = Path(__file__).parent / "fixtures" / "refs_lone_markers.txt"


def test_lone_marker_lines_each_open_their_own_entry():
    # Elsevier copy-paste: [1]-[24] and [57]-[80] inline, [25]-[56] with the
    # number alone on a line. Those 32 used to merge into [24] (48 of 80).
    segs = parse.segment(LONE_FIXTURE.read_text())
    assert len(segs) == 80
    assert [int(s["raw"][1:s["raw"].index("]")]) for s in segs] == list(range(1, 81))
    assert segs[24]["raw"].startswith("[25] A. Murari")


def test_wrapped_doi_tail_is_not_taken_for_a_marker():
    # "…j.aei.2004.09." / "004." then "[55]": the tail must stay with [54]
    # and must not pair with the lone [55] into a detached-marker run.
    segs = parse.segment(LONE_FIXTURE.read_text())
    assert segs[54]["raw"].startswith("[55] P. Borst")
    assert segs[60]["raw"].startswith("[61] L. Moormann")
