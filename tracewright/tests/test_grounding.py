import pytest

from tracewright.propose.documents import Document
from tracewright.propose.grounding import MIN_QUOTE_CHARS, quote_in_document


def text_doc(text):
    return Document(name="d.md", kind="text", text=text, data=None, sha256="0" * 64)


def test_a_quote_that_is_too_short_proves_nothing():
    assert len("abc") < MIN_QUOTE_CHARS
    assert quote_in_document("abc", text_doc("abc abc abc")) is False


@pytest.mark.parametrize(
    ("quote", "document", "found"),
    [
        ("an entry cost of 50", "an entry cost of 500 coins", False),  # cut inside a number
        ("embers earn Map Fragments", "Members earn Map Fragments", False),  # cut inside a word
        ("Fragment Packs (3 per day)", "Fragment Packs (3 per day)", True),  # edge is punctuation
    ],
)
def test_a_quote_may_not_start_or_end_inside_a_word_or_number(quote, document, found):
    assert quote_in_document(quote, text_doc(document)) is found


@pytest.mark.parametrize(
    ("quote", "document"),
    [
        ("five \u2010 ten items", "five - ten items"),
        ("the players\u02bc share is", "the players' share is"),  # modifier apostrophe
        ("\u201eQuoted words\u201c here", '"Quoted words" here'),
    ],
)
def test_more_typography_is_forgiven(quote, document):
    assert quote_in_document(quote, text_doc(document)) is True


