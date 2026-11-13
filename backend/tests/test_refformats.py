"""BibTeX, RIS and EndNote — the formats that already say where a field ends.

These are parsed exactly. Nothing here should ever reach the prose heuristics,
because doing so throws away a perfect answer for a guessed one.
"""
import refformats as F
import refpipeline

BIB = r"""
@string{jct = "Journal of Computational Typography"}

@article{knuth1986,
  author  = {Donald E. Knuth and Michael F. Plass},
  title   = {The {TeX}book and other studies in typesetting},
  journal = jct,
  volume  = {12}, number = {3}, pages = {45--67}, year = 1986,
  doi     = {10.1000/xyz123}
}

@inproceedings{fontaine,
  author    = {Jean de La Fontaine and {Association for Computing Machinery}},
  title     = {Le Corbeau et le Renard},
  booktitle = {Proc. Fables},
  year      = {1668}
}
"""

RIS = """TY  - JOUR
TI  - Attention Is All You Need
AU  - Vaswani, Ashish
AU  - Shazeer, Noam
T2  - Journal of Machine Learning Research
PY  - 2017/12/04/
DO  - 10.1000/jmlr.2017.0001
AB  - We propose a new simple network architecture, the Transformer,
      dispensing with recurrence entirely.
ID  - vaswani2017
ER  - 
"""

ENW_ENDNOTE = """%0 Journal Article
%A Herbert H. Clark
%D 1982
%T Hearers and Speech Acts
%B Language
%R 10.2307/414102
"""

ENW_REFER = """%A Brian W. Kernighan
%T A System for Typesetting Mathematics
%J J. Comm. ACM
%D March 1978
%R 12345
"""


def test_sniff_tells_the_three_apart_and_leaves_prose_alone():
    assert F.sniff(BIB) == "bibtex"
    assert F.sniff(RIS) == "ris"
    assert F.sniff(ENW_ENDNOTE) == "enw"
    assert F.sniff("J. Bucalossi, WEST full tungsten operation, Nucl. Fusion 64 (2024) 1.") is None


# --------------------------------------------------------------------------- #
# BibTeX
# --------------------------------------------------------------------------- #
def test_bibtex_resolves_string_macros_and_detexes():
    a, b = F.parse_bibtex(BIB)
    assert a["title"] == "The TeXbook and other studies in typesetting"
    assert a["venue"] == "Journal of Computational Typography"      # via @string
    assert (a["year"], a["link"]) == (1986, "https://doi.org/10.1000/xyz123")
    assert b["venue"] == "Proc. Fables" and b["year"] == 1668


def test_bibtex_names_follow_the_reference_table():
    # The worked table from *Tame the BeaST* §11 — the canonical statement of
    # how BibTeX splits First / von / Last / Jr.
    table = [
        ("jean de la fontaine",      "",            "jean de la", "fontaine"),
        ("Jean de la fontaine",      "Jean",        "de la",      "fontaine"),
        ("Jean {de} la fontaine",    "Jean de",     "la",         "fontaine"),
        ("Jean {de} {la} fontaine",  "Jean de la",  "",           "fontaine"),
        ("Jean De La Fontaine",      "Jean De La",  "",           "Fontaine"),
        ("jean De la Fontaine",      "",            "jean De la", "Fontaine"),
        ("Jean de La Fontaine",      "Jean",        "de",         "La Fontaine"),
        ("de la fontaine, Jean",     "Jean",        "de la",      "fontaine"),
        ("De La Fontaine, Jean",     "Jean",        "",           "De La Fontaine"),
        ("De la Fontaine, Jean",     "Jean",        "De la",      "Fontaine"),
        ("de La Fontaine, Jean",     "Jean",        "de",         "La Fontaine"),
    ]
    for name, given, von, family in table:
        p = F.name_parts(name)
        assert (p["given"], p["von"], p["family"]) == (given, von, family), name


def test_bibtex_suffix_and_corporate_author():
    assert F.name_parts("Ford, Jr., Henry")["suffix"] == "Jr."
    # double braces make the whole thing one token with no depth-0 character,
    # so it lands in the family part verbatim rather than being split
    p = F.name_parts("{Association for Computing Machinery}")
    assert p["family"] == "Association for Computing Machinery" and not p["given"]


def test_bibtex_and_inside_a_braced_name_does_not_split_it():
    assert F.split_names("{Barnes and Noble, Inc.} and Smith, J.") == [
        "{Barnes and Noble, Inc.}", "Smith, J."]


def test_journaltitle_and_address_aliases_resolve():
    recs = F.parse_bibtex("@article{k,author={A. B. C},title={T},"
                          "journaltitle={Nature},year={2020}}")
    assert recs[0]["venue"] == "Nature"


# --------------------------------------------------------------------------- #
# RIS
# --------------------------------------------------------------------------- #
def test_ris_repeated_tags_continuations_and_slashed_dates():
    r, = F.parse_ris(RIS)
    assert r["title"] == "Attention Is All You Need"
    assert r["authors"] == "Vaswani, Ashish; Shazeer, Noam"     # repeated AU
    assert r["year"] == 2017                                    # from 2017/12/04/
    assert r["venue"] == "Journal of Machine Learning Research"
    assert r["link"] == "https://doi.org/10.1000/jmlr.2017.0001"


def test_ris_record_boundaries_are_ty_and_er():
    two = F.parse_ris(RIS + "\n" + RIS.replace("Attention Is All You Need", "Second"))
    assert [r["title"] for r in two] == ["Attention Is All You Need", "Second"]


# --------------------------------------------------------------------------- #
# EndNote vs plain Refer — the same letters, different meanings
# --------------------------------------------------------------------------- #
def test_percent_r_is_a_doi_only_in_endnote():
    # EndNote reassigned refer's letters. Reading .enw as Refer files a DOI
    # under "report number"; reading Refer as EndNote invents a DOI.
    en, = F.parse_enw(ENW_ENDNOTE)
    rf, = F.parse_enw(ENW_REFER)
    assert en["link"] == "https://doi.org/10.2307/414102"
    assert rf["link"] is None
    assert (en["venue"], rf["venue"]) == ("Language", "J. Comm. ACM")


# --------------------------------------------------------------------------- #
# The pipeline must not send these down the heuristic path
# --------------------------------------------------------------------------- #
def test_pipeline_prefers_the_exact_parse():
    for text, n in ((BIB, 2), (RIS, 1), (ENW_ENDNOTE, 1)):
        out = refpipeline.parse(text)
        assert len(out) == n, text[:24]
        assert all(r["title"] for r in out)
    assert refpipeline.parse(BIB)[0]["title"] == "The TeXbook and other studies in typesetting"
