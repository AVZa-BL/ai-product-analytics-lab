import pytest

from tracewright.propose.documents import Document
from tracewright.propose.grounding import MIN_QUOTE_CHARS, normalise, quote_in_document


def text_doc(text):
    return Document(name="d.md", kind="text", text=text, data=None, sha256="0" * 64)


def test_a_verbatim_quote_is_found():
    document = text_doc("x. Members earn Map Fragments from y")
    assert quote_in_document("Members earn Map Fragments", document) is True


@pytest.mark.parametrize(
    "quote",
    [
        "members  EARN\nmap fragments",  # case and whitespace
        "Members earn **Map Fragments**",  # emphasis marks
        "Players’ share",  # curly apostrophe
        "five – ten",  # en dash
    ],
)
def test_typography_is_forgiven(quote):
    document = text_doc("Members earn Map Fragments. Players' share. five - ten")
    assert quote_in_document(quote, document) is True


def test_different_words_are_not_forgiven():
    document = text_doc("Members earn Map Fragments from battles")
    assert quote_in_document("Players collect Map Fragments from battles", document) is False


def test_a_quote_that_is_too_short_proves_nothing():
    assert len("abc") < MIN_QUOTE_CHARS
    assert quote_in_document("abc", text_doc("abc abc abc")) is False


def test_a_pdf_cannot_be_searched():
    pdf = Document(name="d.pdf", kind="pdf", text=None, data=b"%PDF-", sha256="0" * 64)
    assert quote_in_document("anything at all here", pdf) is None


def test_normalise_is_idempotent():
    once = normalise("  Héllo  **World**  ")
    assert normalise(once) == once == "héllo world"
