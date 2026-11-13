"""Structural style detection and the field extraction it drives.

The numbers asserted here are the reason the module exists. On the IOS Press
bibliography — initials-first authors, organisations standing in for authors,
"in:" editor constructs, and a venue that carries no year of its own — the
old style-branch parser extracted 3 of 34 titles correctly even when handed
perfect segmentation. Detecting the style once across the whole bibliography
and extracting against it takes that to 29.
"""
import csv
import re
from pathlib import Path

import refparse
import refstyle
from synapse.references import parse as segmenter

FIX = Path(__file__).parent / "fixtures"


def _raws(name: str) -> list[str]:
    return [s["raw"] for s in segmenter.segment((FIX / f"{name}.txt").read_text())]


def _truth(name: str) -> list[dict]:
    with (FIX / f"{name}.csv").open() as fh:
        return list(csv.DictReader(fh))


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").replace("|", ",").lower()).strip()


def _score(fixture: str, groundtruth: str) -> tuple[int, int, int]:
    raws, truth = _raws(fixture), _truth(groundtruth)
    assert len(raws) == len(truth), "fixture and ground truth disagree on count"
    prof = refstyle.detect(raws)
    t = sum(_norm(refstyle.fields(r, prof)["title"]) == _norm(w["title"])
            for r, w in zip(raws, truth))
    y = sum(str(refstyle.fields(r, prof)["year"]) == w["year"] for r, w in zip(raws, truth))
    return t, y, len(truth)


# --------------------------------------------------------------------------- #
# The skeleton — words erased, punctuation and case kept
# --------------------------------------------------------------------------- #
def test_skeleton_separates_the_two_families():
    apa = refstyle.skeleton("Smith, J. (2011). A title. Journal of Things, 12(3), 1-10.")
    els = refstyle.skeleton("J. Bucalossi, WEST full tungsten operation, Nucl. Fusion 64 (2024) 1.")
    assert apa[:4] == ["CAPWORD", "COMMA", "UCLETT", "DOT"]
    assert els[:4] == ["UCLETT", "DOT", "CAPWORD", "COMMA"]


def test_non_ascii_names_stay_one_token():
    # An ASCII [A-Z][a-z]+ class splits this into three tokens and loses the
    # author, which cost a whole reference on the Elsevier fixture.
    assert refstyle.skeleton("Jabłoński")[0] == "CAPWORD"
    assert refstyle.skeleton("Karakuş")[0] == "CAPWORD"


# --------------------------------------------------------------------------- #
# The author boundary, and what closes it
# --------------------------------------------------------------------------- #
def test_author_run_reports_its_closing_punctuation():
    # This is the fact the whole bibliography votes on: the same author list
    # closes on a comma in one style and a period in another.
    _, close, order = refstyle.author_run(
        "J. Bucalossi, A. Ekedahl, WEST full tungsten operation, Nucl. Fusion 64.")
    assert (order, close) == ("given-first", "COMMA")
    _, close, order = refstyle.author_run(
        "A. Krizhevsky, I. Sutskever, and G. E. Hinton. ImageNet. In NIPS, 2012.")
    assert (order, close) == ("given-first", "DOT")


def test_every_name_order_is_recognised():
    cases = {
        "given-first": "J. Bucalossi, A. Ekedahl, WEST full tungsten operation, Nucl. Fusion 64.",
        "family-first": "Hafner, D., Lillicrap, T. Dream to control. In ICLR, 2020.",
        "family-initials": "Bucalossi J, Pitts RA. WEST operation. Nucl Fusion. 2024;64:112022.",
        "full-name": "Mihály Héder. 2017. From NASA to EU. The Innovation Journal 22, 1-23.",
        "org": "DoD, Levels of Information Systems Interoperability, 1998.",
    }
    for want, entry in cases.items():
        run = refstyle.author_run(entry)
        assert run is not None, entry
        assert run[2] == want, f"{entry}\n  wanted {want}, got {run[2]}"


def test_a_title_word_is_not_read_as_another_author():
    # "…, A. Ekedahl, WEST full tungsten operation" — in a style where every
    # author carries initials, "WEST" cannot be a surname.
    entry = "J. Bucalossi, A. Ekedahl, WEST full tungsten operation, Nucl. Fusion 64."
    end, _, _ = refstyle.author_run(entry)
    assert refstyle.tokenize(entry)[end][2] == len("J. Bucalossi, A. Ekedahl")


# --------------------------------------------------------------------------- #
# Anchors
# --------------------------------------------------------------------------- #
def test_identifiers_claim_their_digits_before_weaker_patterns():
    kinds = dict((k, e) for _, e, k in
                 [(a, e, k) for a, e, k in refstyle.anchors(
                     "A study of BFLOAT16, 2019, arXiv:1905.12322.")])
    assert "arxiv" in kinds
    years = [k for _, _, k in refstyle.anchors("A study, 2019, arXiv:1905.12322.")
             if k == "year"]
    assert len(years) == 1        # 1905 inside the arXiv id is not a year


def test_access_date_is_not_the_publication_date():
    kinds = [k for _, _, k in refstyle.anchors(
        "The TRI primer, 2014. Retrieved December 2019 from https://x.org/a")]
    assert "accessed" in kinds


# --------------------------------------------------------------------------- #
# Detection votes across the bibliography
# --------------------------------------------------------------------------- #
def test_profiles_of_the_four_fixtures():
    expected = {
        "refs_elsevier": ("given-first", "COMMA", "numeric"),
        "refs_ios_style": ("given-first", "COMMA", "numeric"),
        "refs_author_year": ("family-first", "DOT", "numeric"),
        "refs_messy": ("full-name", "DOT", "author-date"),
    }
    for name, (order, sep, family) in expected.items():
        p = refstyle.detect(_raws(name))
        assert (p.order, p.sep, p.family) == (order, sep, family), name


# --------------------------------------------------------------------------- #
# What it is all for
# --------------------------------------------------------------------------- #
def test_ios_titles_beat_the_old_parser_by_a_wide_margin():
    raws, truth = _raws("refs_ios_style"), _truth("refs_ios_groundtruth")
    old = sum(_norm(refparse.title_of(r)) == _norm(w["title"]) for r, w in zip(raws, truth))
    new, year, n = _score("refs_ios_style", "refs_ios_groundtruth")
    assert n == 34
    assert old <= 3          # the style-branch parser, given perfect segments
    assert new >= 29
    assert year == 34


def test_elsevier_holds_at_full_marks():
    # The style-specific branch that was written for this bibliography scored
    # 41/41; the general path must not buy the IOS gain by giving this up.
    title, year, n = _score("refs_elsevier", "refs_elsevier_groundtruth")
    assert (title, year, n) == (41, 41, 41)


def test_messy_years_improve():
    raws = _raws("refs_messy")
    prof = refstyle.detect(raws)
    truth = _truth("refs_groundtruth")
    dated = [(w, r) for w, r in zip(truth, raws) if w["year"]]
    new = sum(str(refstyle.fields(r, prof)["year"]) == w["year"] for w, r in dated)
    old = sum(str(refparse.year_of(r)) == w["year"] for w, r in dated)
    assert old == 13 and new == len(dated) == 15


# --------------------------------------------------------------------------- #
# Quoted titles — the one boundary that needs no heuristic
# --------------------------------------------------------------------------- #
# IEEE, Chicago, MLA and Harvard all quote the article title, and between them
# that is a large share of real bibliographies. Where the quotes exist they are
# believed over every other rule, so extraction is exact rather than inferred.
IEEE = [
    '[1] M. M. Chiampi and L. L. Zilberti, “Induction of electric field in human '
    'bodies moving near MRI: An efficient BEM computational procedure,” IEEE Trans. '
    'Biomed. Eng., vol. 58, no. 10, pp. 2787–2793, Oct. 2011, doi: 10.1109/TBME.2011.2158315.',
    '[2] J. Zhao, G. Sun, and Y. Xie, “Energy-efficient GPU design with reconfigurable '
    'in-package graphics memory,” in Proc. ACM/IEEE Int. Symp. Low Power Electron. '
    'Design (ISLPED), Jul. 2012, pp. 403–408.',
]
CHICAGO = [
    'Kwon, Hyeyoung. “Inclusion Work: Children of Immigrants Claiming Membership in '
    'Everyday Life.” American Journal of Sociology 127, no. 6 (2022): 1818–59.',
    'Dittmar, Emily L., and Douglas W. Schemske. “Temporal Variation in Selection.” '
    'American Naturalist 202, no. 3 (2023): 4–5.',
]
MLA = [
    'Goldman, Anne. "Questions of Transport: Reading Primo Levi Reading Dante." '
    'The Georgia Review, vol. 64, no. 1, spring 2010, pp. 69-88.',
]
HARVARD = [
    "Chen, Y. (2023) 'Addressing uncertainties through improved reserve product "
    "design', IEEE Transactions on Power Systems, 38(4), pp. 3911-3923.",
]


def test_quoted_styles_are_detected_as_quoted():
    for name, entries in (("IEEE", IEEE), ("Chicago", CHICAGO),
                          ("MLA", MLA), ("Harvard", HARVARD)):
        assert refstyle.detect(entries).quoted, name


def test_quoted_titles_come_out_exactly():
    want = {
        "Induction of electric field in human bodies moving near MRI: "
        "An efficient BEM computational procedure": IEEE,
        "Inclusion Work: Children of Immigrants Claiming Membership in Everyday Life": CHICAGO,
        "Questions of Transport: Reading Primo Levi Reading Dante": MLA,
        "Addressing uncertainties through improved reserve product design": HARVARD,
    }
    for title, entries in want.items():
        prof = refstyle.detect(entries)
        assert refstyle.fields(entries[0], prof)["title"] == title


def test_the_closing_comma_inside_an_ieee_quote_is_not_part_of_the_title():
    # IEEE writes  …procedure,”  — the comma sits INSIDE the closing quote.
    assert not refstyle.quoted_title(IEEE[0])[0].endswith(",")


def test_chicago_and_mla_invert_only_the_first_author():
    # "Dittmar, Emily L., and Douglas W. Schemske." — one inverted name then a
    # natural-order one. None of the initials-based rules can see either.
    prof = refstyle.detect(CHICAGO)
    assert prof.order == "family-first-full"
    assert refstyle.fields(CHICAGO[1], prof)["title"] == "Temporal Variation in Selection"


def test_venue_follows_a_quoted_title():
    prof = refstyle.detect(IEEE)
    assert refstyle.fields(IEEE[0], prof)["venue"] == "IEEE Trans. Biomed. Eng."
    assert refstyle.fields(IEEE[1], prof)["venue"].startswith("Proc. ACM/IEEE Int. Symp.")


def test_an_organisation_is_not_mistaken_for_an_inverted_name():
    # "NASA, Mars Climate Orbiter, …" must not parse as family "NASA",
    # given "Mars Climate" the way "Kwon, Hyeyoung." does.
    entries = ["DoD, Levels of Information Systems Interoperability, 1998.",
               "NASA, Mars Climate Orbiter, Mishap Investigation Board: Phase I Report, 1999."]
    prof = refstyle.detect(entries)
    assert prof.order == "org"
    assert refstyle.fields(entries[0], prof)["title"] == \
        "Levels of Information Systems Interoperability"


# --------------------------------------------------------------------------- #
# NeurIPS/ICML style: authors spelled out in full, no initials, no markers
# --------------------------------------------------------------------------- #
# This one returned 3 references out of 12. Three independent faults stacked:
# the URL-wrap repair welded the next reference onto a finished link, entries
# whose authors carry no initials at all had no entry-start signal, and a
# spelled-out name with a middle initial ("William A. Wieselquist") broke the
# author run in the middle.
NEURIPS_TITLES = [
    "Large language models: A survey",
    "Nukelm: Pre-trained and fine-tuned language models for the nuclear and energy domains",
    "Nukebert: A pre-trained language model for low resource nuclear domain",
    "Towards llms as operational copilots for fusion reactors",
    "Large language models as optimizers",
    "Chain-of-thought prompting elicits reasoning in large language models",
    "Self-consistency improves chain of thought reasoning in language models",
    "Isotopic and fuel lattice parameter trends in extended enrichment and higher "
    "burnup lwr fuel: Volume ii: Bwr fuel",
    "Transition Core Modeling for Extended-Enrichment Accident-Tolerant Fuels in "
    "Light Water Reactors Using PARCS/Polaris",
    "Assessment of core physics characteristics of extended enrichment and higher "
    "burnup lwr fuels using the polaris/parcs two-step approach: Vol. 2: Bwr fuel",
    "CASMO-5 User's Manual",
    "Gemini: A family of highly capable multimodal models",
]


def test_neurips_style_segments_and_titles():
    import refpipeline
    text = (FIX / "refs_neurips.txt").read_text()
    assert len(refpipeline.segment(text)) == 12
    got = [r["title"] for r in refpipeline.parse(text)]
    assert got == NEURIPS_TITLES


def test_a_finished_url_does_not_swallow_the_next_reference():
    # "…/abs/2105.12192."  +  "B. Venkatraman Ayush Jain, …"  is two references.
    # A continuation starts lowercase or with a digit, or carries a slash.
    joined = refparse._dehyphenate(
        "models. arXiv:2105.12192, 2021. URL\n"
        "https://arxiv.org/abs/2105.12192.\n"
        "B. Venkatraman Ayush Jain, N.M. Meenachi. Nukebert: A pre-trained model.")
    assert "2105.12192.\nB. Venkatraman" in joined
    # ...while a genuinely broken URL still rejoins
    assert "docs/ML2327/ML23279A041.pdf" in refparse._dehyphenate(
        "August 2023. URL https://www.nrc.gov/docs/\nML2327/ML23279A041.pdf.")


def test_a_spelled_out_name_may_carry_a_middle_initial():
    run = refstyle.author_run(
        "Ugur Mertyurek and William A. Wieselquist. Assessment of core physics.")
    assert run is not None and run[2] == "full-name"
    end = refstyle.tokenize(
        "Ugur Mertyurek and William A. Wieselquist. Assessment of core physics.")[run[0]][2]
    assert end == len("Ugur Mertyurek and William A. Wieselquist")


def test_a_one_word_name_may_not_close_on_and():
    # "Isotopic and fuel lattice parameter trends…" is a title, not an author.
    entry = ("Riley Cumberland, Ryan Sweet, and William A. Wieselquist. "
             "Isotopic and fuel lattice parameter trends. Technical Report, 2021.")
    prof = refstyle.detect([entry])
    assert refstyle.fields(entry, prof)["title"].startswith("Isotopic and fuel")


# --------------------------------------------------------------------------- #
# Author-date (APA / apalike / AAAI / JAIR): surname first, year in parentheses
# --------------------------------------------------------------------------- #
# A pasted JAIR bibliography segmented 12 of 33. Every rule in the segmenter
# recognised the OTHER author orders — initials-first ("M. Austin, …"), full
# names ("Riley Cumberland, …"), bare-year ("… . 2016.") — and nothing knew the
# commonest shape in the literature: "Bellemare, M., Veness, J. (2012)."
# The entries it did find were extracted correctly, so this is segmentation
# alone, and the fixture exists to keep it that way.
def test_apalike_segments_every_entry():
    raws = _raws("refs_apalike")
    assert len(raws) == 33


def test_apalike_wrapped_author_list_is_not_a_new_entry():
    # "Browne, C. B., Powley, E., Whitehouse, D., …," wraps before its year, so
    # the continuation line looks exactly like an entry opening. What saves it
    # is the line before ending in a COMMA — an author list still running.
    raws = _raws("refs_apalike")
    browne = [r for r in raws if r.startswith("Browne")]
    assert len(browne) == 1
    assert "Colton" in browne[0] and "Monte Carlo" in browne[0]


def test_apalike_fields():
    title, year, n = _score("refs_apalike", "refs_apalike_groundtruth")
    assert n == 33
    assert year == 33
    # 30/33. The three misses are all the title/venue boundary, not segmentation:
    # "Games." and "Mario." are short capitalised words, which _ABBREV_BEFORE
    # reads as abbreviations ("Nucl.", "Syst.") and so declines to split on —
    # the same rule the Elsevier fixture's 41/41 depends on.
    assert title >= 30


def test_initial_period_is_not_a_field_break():
    # The D of "Ph.D." — without this the degree lands in the title and the
    # entry reads "Machine Super Intelligence, Ph.D" | "thesis, University of…".
    raws = _raws("refs_apalike")
    prof = refstyle.detect(raws)
    legg = next(r for r in raws if r.startswith("Legg, S. (2008)"))
    assert refstyle.fields(legg, prof)["title"] == "Machine Super Intelligence"


# Semicolon-separated authors (Scopus, ACS, some Vancouver exports).
import refpipeline


def test_semicolon_author_separators_do_not_leak_an_author_into_the_title():
    txt = ("[1] Vaswani A; Shazeer N; Parmar N. Attention is all you need. NeurIPS; 2017.\n"
           "[2] Rose ME; Huerbin MB; Melick J. Regulation of amino acid concentrations. "
           "Brain Res. 2002;935(1-2):40-6.\n")
    got = refpipeline.parse(txt)
    assert [r["title"] for r in got] == ["Attention is all you need",
                                        "Regulation of amino acid concentrations"]
    assert got[0]["authors"] == "Vaswani A, Shazeer N, Parmar N"


def test_a_semicolon_inside_a_title_is_left_alone():
    assert refpipeline.normalise_semicolons(
        "Smith, J.; Jones, K. Plasma control; a review. Nucl. Fusion 2020.") == \
        "Smith, J., Jones, K. Plasma control; a review. Nucl. Fusion 2020."


# --------------------------------------------------------------------------- #
# ACL / NeurIPS natbib: "Full Name, Full Name, and Full Name. 2019. Title. Venue."
# --------------------------------------------------------------------------- #
# A pasted Chain-of-Thought bibliography segmented 4 of 86. Entries end on a
# bare venue ("…EMNLP.", "…arXiv:2204.01691.") and only the APA start rule could
# follow a plain full stop; author lists wrap for up to seven lines before the
# year, so the start is judged by reading ahead to the first ". YYYY.".
def test_acl_natbib_segments_every_entry():
    assert len(_raws("refs_acl_natbib")) == 86


def test_acl_natbib_fields():
    title, year, n = _score("refs_acl_natbib", "refs_acl_natbib_groundtruth")
    assert n == 86
    assert year == 86
    assert title == 86


def test_natbib_head_cuts_a_long_author_list_at_the_year():
    # "Jared D Kaplan" (an initial without a period) stopped `author_run` and
    # handed 25 names to the title.
    raws = _raws("refs_acl_natbib")
    prof = refstyle.detect(raws)
    brown = next(r for r in raws if r.startswith("Tom Brown"))
    f = refstyle.fields(brown, prof)
    assert f["title"] == "Language models are few-shot learners"
    assert f["authors"].endswith("and Dario Amodei")
    assert f["venue"] == "NeurIPS"


def test_title_word_collaboration_is_not_an_author_note():
    raws = _raws("refs_acl_natbib")
    prof = refstyle.detect(raws)
    e = next(r for r in raws if "Reframing" in r)
    assert refstyle.fields(e, prof)["title"].startswith("Reframing human-AI collaboration")


def test_chained_compound_keeps_its_line_break_hyphen():
    assert refparse._dehyphenate("Leap-of-\nthought") == "Leap-of-thought"
