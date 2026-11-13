"""Recasing shouted titles.

The cases that matter are the ones a blanket `.lower()` gets wrong, so most of
this file is about what must NOT change: "ILSVRC-2012" is a whole title, "16x16"
is a word, and the Qwen abstract must not be allowed to certify its own shout.
"""
import recase
from recase import Lexicon, build_lexicon, recase as fix

# A miniature repository: correctly cased titles plus one abstract of prose.
TITLES = [
    "ImageNet Classification with Deep Convolutional Neural Networks",
    "Attention Is All You Need",
    "Computer Organization and Design: The Hardware/Software Interface: RISC-V Edition",
    "Efficient inference with VLMs on edge devices",
    "Scaling laws for LLMs and their limits",
    "A survey of in-context learning",
]
PROSE = [
    "We evaluate on the ILSVRC-2012 split and report results on arXiv preprints. "
    "The VLMs we test are small. Fusion plants are the target application.",
]


# Stand-in for /usr/share/dict/words, so the tests say the same thing on a
# machine that has no word list installed.
ENGLISH = frozenset("""
    harnessing communication surge large language models model study methods
    technical report cost scale token reduction video edge devices inference
    efficient learning context design note laws survey limits image words worth
    series released compare split results preprints target application
""".split())


def lex(titles=None, prose=None, english=ENGLISH):
    return build_lexicon(TITLES if titles is None else titles,
                         PROSE if prose is None else prose,
                         extra_forms=[], english=english)


def test_positional_capitals_come_down_identity_capitals_stay():
    out = fix("EFFICIENT INFERENCE WITH VLMS ON EDGE DEVICES", lex())
    assert out.proposed == "Efficient Inference with VLMs on Edge Devices"


def test_minor_words_lowercase_but_never_first_or_last():
    out = fix("THE COST OF SCALE", lex())
    assert out.proposed == "The Cost of Scale"


def test_sentence_style_capitalises_only_the_opening_and_after_a_colon():
    out = fix("SCALING LAWS FOR LLMS: A SURVEY", lex(), style="sentence")
    assert out.proposed == "Scaling laws for LLMs: A survey"


def test_alphanumeric_words_are_not_shouting():
    out = fix("AN IMAGE IS WORTH 16X16 WORDS", lex())
    assert out.proposed == "An Image Is Worth 16x16 Words"


def test_hyphenated_compounds_are_cased_part_by_part():
    # Both halves capitalised in title case — the opening element too, even
    # though "in" is a minor word on its own.
    assert fix("LEARNING IN-CONTEXT AT SCALE", lex()).proposed == "Learning In-Context at Scale"
    # A known half keeps its own spelling.
    assert fix("A NOTE ON RISC-V DESIGN", lex()).proposed == "A Note on RISC-V Design"


def test_single_word_titles_are_names_and_are_left_alone():
    out = fix("ILSVRC-2012", lex())
    assert out.proposed == "ILSVRC-2012"
    assert not out.changed and out.skipped


def test_titles_that_are_not_shouting_are_untouched():
    original = "Attention Is All You Need"
    out = fix(original, lex())
    assert out.proposed == original and out.skipped == "not in caps"


def test_a_shouting_source_cannot_vouch_for_itself():
    """Without this the broken titles certify each other and nothing changes."""
    shouted = "QWEN TECHNICAL REPORT"
    l = lex(titles=TITLES + [shouted, "TECHNICAL REPORT ON REPORT WRITING"], prose=[])
    assert l.identity("TECHNICAL") is None
    assert fix(shouted, l).proposed.endswith("Technical Report")


def test_evidence_is_counted_in_documents_not_mentions():
    """One document repeating its own name is one opinion, and scores as one."""
    l = lex(prose=["We introduce QWEN. QWEN is a series. QWEN-CHAT follows QWEN."])
    assert l.identity("QWEN") == ("QWEN", 1)
    out = fix("QWEN TECHNICAL REPORT", l)
    assert out.proposed == "QWEN Technical Report"
    assert out.needs_review          # one document is not consensus
    l2 = lex(prose=PROSE + ["QWEN was released.", "We compare against QWEN too."])
    assert l2.identity("QWEN") == ("QWEN", 2)
    assert not fix("QWEN TECHNICAL REPORT", l2).needs_review


def test_a_vowelless_word_is_an_acronym_even_with_no_corpus():
    empty = Lexicon()
    assert fix("A STUDY OF LLM PROMPTING", empty).proposed == "A Study of LLM Prompting"
    # …and its plural comes down to the conventional lowercase s.
    assert fix("A STUDY OF LLMS", empty).proposed == "A Study of LLMs"


def test_a_name_before_a_colon_keeps_its_capitals_but_is_flagged():
    out = fix("SURGE: TOKEN REDUCTION FOR VIDEO", lex())
    assert out.proposed == "SURGE: Token Reduction for Video"
    assert out.needs_review          # could be an initialism, could be a word


def test_a_long_wordmark_is_flagged_rather_than_guessed():
    """"XIHEFUSION" could be XiheFusion or Xihefusion; nothing local knows."""
    out = fix("XIHEFUSION: HARNESSING LARGE LANGUAGE MODELS", lex())
    assert out.proposed == "Xihefusion: Harnessing Large Language Models"
    assert out.confidence < recase.REVIEW_THRESHOLD
    assert [w.source for w in out.uncertain] == ["XIHEFUSION"]


def test_the_user_word_list_settles_what_the_corpus_cannot():
    l = build_lexicon(TITLES, PROSE, extra_forms=["XiheFusion"], english=frozenset())
    out = fix("XIHEFUSION: A REPORT", l)
    assert out.proposed == "XiheFusion: A Report"
    assert not out.needs_review


def test_ordinary_words_absent_from_the_corpus_are_not_flagged():
    """The system word list keeps plain English out of the review queue."""
    out = fix("HARNESSING MODELS FOR COMMUNICATION", lex())
    assert out.proposed == "Harnessing Models for Communication"
    assert not out.needs_review


def test_an_unknown_word_is_lowercased_but_the_title_is_flagged():
    out = fix("A STUDY OF GRAKUL METHODS", lex())
    assert out.proposed == "A Study of Grakul Methods"
    assert out.needs_review
    assert [w.source for w in out.uncertain] == ["GRAKUL"]


def test_punctuation_and_spacing_survive_verbatim():
    out = fix("MATERIALS ROADMAP 2.0  —  PART II", lex())
    assert out.proposed == "Materials Roadmap 2.0  —  Part II"


# --------------------------------------------------------------------------- #
# Title Case -> sentence case
# --------------------------------------------------------------------------- #
from recase import sentence_case

PROPER = frozenset({"Python", "Bayesian"})
ENGLISH_PLUS = ENGLISH | {"python", "hands", "on", "crash", "course", "programming",
                          "introduction", "edition", "linear", "algebra", "language",
                          "hardware", "software", "interface", "organization", "computer"}


def slex():
    return build_lexicon(TITLES, PROSE, extra_forms=[], english=ENGLISH_PLUS, proper=PROPER)


def test_sentence_case_keeps_only_the_first_capital():
    out = sentence_case("Introduction to Linear Algebra, 5th Edition", slex())
    assert out.proposed == "Introduction to linear algebra, 5th edition"
    assert not out.needs_review


def test_sentence_case_keeps_identity_capitals_and_capitalises_after_a_colon():
    out = sentence_case("Computer Organization and Design: The Hardware/Software "
                        "Interface: RISC-V Edition", slex())
    assert out.proposed == ("Computer organization and design: The hardware/software "
                            "interface: RISC-V edition")


def test_sentence_case_keeps_a_lone_capital_letter_that_names_a_language():
    assert sentence_case("The C Programming Language", slex()).proposed == \
        "The C programming language"


def test_a_word_that_is_also_a_name_keeps_its_capital_and_is_flagged():
    out = sentence_case("Automate the Boring Stuff with Python", slex())
    assert out.proposed.endswith("with Python")
    assert out.needs_review


def test_sentence_case_lowers_hyphenated_compounds_part_by_part():
    out = sentence_case("Python Crash Course: A Hands-On Introduction", slex())
    assert out.proposed == "Python crash course: A hands-on introduction"
