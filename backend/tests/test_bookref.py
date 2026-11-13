"""Reading chapter, pages and mode out of hand-typed book session purposes.

Every string in REAL was typed by the user into a session's `purpose` before
the fields existed, and is what the backfill has to cope with. The point of
most of these cases is what must NOT be invented: "Page 22 - xxx?" records a
start and no end, and the parser has to say so rather than pick a number.
"""
import bookref
from bookref import chapter_of, chapter_sort_key, mode_of, pages_of, parse

# Verbatim from the graph — see the module docstring in bookref.py.
REAL = [
    ("Book [Page 1 - Page 17]",                          None,  1,   17),
    ("Book [Page 17 - Page 38]",                          None,  17,  38),
    ("Book Chapter 2 [Page 39 - Page 56]",                "2",   39,  56),
    ("Book Chapter 2 [Page 39 implementation - Page 44]", "2",   39,  44),
    ("Book Chapter 2 [Page 44 - Page 49] Implementation", "2",   44,  49),
    ("First chapter Page 0 - Page 23",                    "1",   0,   23),
    ("Book - [Chapter 2 Page 19 - Chapter 2 - Page 29]",  "2",   19,  29),
    ("Book Chapter 2 [Page 29 - Page xxx]",               "2",   29,  None),
    ("Introduction up to page 19",              "introduction",  None, 19),
    ("Chapter 1 - Page 19 - Page 22 the top third",       "1",   19,  22),
    ("Chapter 1 Page 22 - xxx?",                          "1",   22,  None),
    ("chapter 1 page 22 - xxxx?",                         "1",   22,  None),
    ("Chapter 1 - exercise 1.13 - ???",                   "1",   None, None),
    ("Book - Chapter 1 - [Page 25 - Page - xxx]",         "1",   25,  None),
    ("Chapter 1 page 1 - xxx?",                           "1",   1,   None),
]


def test_real_purposes_parse():
    for text, chapter, lo, hi in REAL:
        got = parse(text)
        assert got["chapter"] == chapter, text
        assert got["pages_from"] == lo, text
        assert got["pages_to"] == hi, text


def test_an_unwritten_end_page_stays_unwritten():
    # The whole reason pages_to is nullable. Anything but None here would be a
    # page number the user never recorded, inside a record meant to be shown.
    for text in ("Chapter 1 Page 22 - xxx?", "Book - Chapter 1 - [Page 25 - Page - xxx]",
                 "Chapter 3 page 40 - ???", "ch4 p.10 - tbc"):
        assert pages_of(text)[1] is None, text


def test_chapter_ranges_normalise_to_one_spelling():
    for text in ("Chapter 1-2", "chapters 1 to 2", "Ch 1 & 2", "chapter 2 to 1"):
        assert chapter_of(text) == "1 to 2", text
    # A "range" that names one chapter twice is that chapter.
    assert chapter_of("Chapter 3 - 3") == "3"


def test_named_chapters():
    assert chapter_of("First chapter Page 0 - Page 23") == "1"
    assert chapter_of("Introduction up to page 19") == "introduction"
    assert chapter_of("Preface, skimmed") == "front matter"
    # An introduction is NOT silently renumbered into chapter 1.
    assert chapter_of("Intro") != "1"


def test_no_chapter_named_is_none_not_one():
    for text in ("Book [Page 1 - Page 17]", "read a bit", ""):
        assert chapter_of(text) is None, text


def test_mode():
    assert mode_of("Chapter 1 - exercise 1.13 - ???") == "exercises"
    assert mode_of("Book Chapter 2 [Page 44 - Page 49] Implementation") == "code"
    assert mode_of("Chapter 2 revision") == "review"
    assert mode_of("Book [Page 1 - Page 17]") == "read"
    assert mode_of("") is None
    # Exercises win over implementation: the chapter-status rule counts them.
    assert mode_of("chapter 3 exercises, implemented in C") == "exercises"


def test_backwards_page_range_is_a_typo_not_a_backwards_read():
    assert pages_of("Chapter 1 [Page 56 - Page 39]") == (39, 56)


def test_chapter_order_is_the_book_s_order():
    chapters = ["2", None, "introduction", "1 to 2", "1", "front matter", "appendix a"]
    assert sorted(chapters, key=chapter_sort_key) == [
        "front matter", "introduction", "1", "1 to 2", "2", "appendix a", None]


def test_parse_is_pure():
    before = dict(vars(bookref))
    parse("Book Chapter 2 [Page 39 - Page 56]")
    assert set(vars(bookref)) == set(before)


# --------------------------------------------------------------------------- #
# Pairing a book with its project. Both cases below were live bugs found by
# running the proposal against the real library before anything was written.
# --------------------------------------------------------------------------- #
from routes.books import _norm, _score  # noqa: E402


def test_a_single_shared_word_is_not_a_match():
    # "Mathematics for Robotics" is a different project from the book
    # "Mathematics for Machine Learning"; the only word they share is "mathematics".
    score, sure = _score("Mathematics for Machine Learning", "Mathematics for Robotics")
    assert score == 0.0 and not sure


def test_an_unspaced_hyphen_does_not_truncate_the_title():
    # Stripping at the hyphen in "Hands-On" left both titles as "hands", which
    # matched every other hyphenated book in the library.
    assert _norm("Hands-On Machine Learning with Scikit-Learn") != "hands"
    score, sure = _score("Hands-On Machine Learning with Scikit-Learn, 3rd ed",
                         "Hands-On Machine Learning")
    assert score >= 0.95 and sure


def test_a_spaced_dash_still_separates_a_subtitle():
    assert _norm("The C Programming Language - 2nd edition") == _norm("The C Programming Language")


def test_only_exact_and_prefix_matches_are_certain():
    # A real pairing, but one only a person can confirm.
    score, sure = _score("Artificial Intelligence A Modern Approach", "AI, A Modern Approach")
    assert score >= 0.6 and not sure


def test_exact_match_is_certain():
    score, sure = _score("The C Programming Language", "The C Programming Language")
    assert score == 1.0 and sure


def test_unrelated_titles_do_not_match():
    for a, b in [("The Algorithm Design Manual", "Garden planter"),
                 ("Automate the Boring Stuff with Python", "Weather (Station)"),
                 ("Mathematics of Neural Networks", "Journal")]:
        assert _score(a, b)[0] == 0.0, (a, b)
