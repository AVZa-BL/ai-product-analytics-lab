"""Check that quoted evidence really appears in the documents.

A model asked to justify a recommendation can invent a plausible quotation. This is the
deterministic defence: a quote that claims to come from a text document must be found in it.

The comparison is forgiving about typography only (case, runs of whitespace, curly quotes,
dashes, Markdown emphasis marks), because models normalise those; it is not forgiving about
words. A quote that passes proves the words are in the document, not that the model read them
correctly, and not that the event it supports is the right one.
"""

from __future__ import annotations

import re
import unicodedata

from tracewright.propose.documents import Document

MIN_QUOTE_CHARS = 8

_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        "*": "",
        "`": "",
    }
)
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """The form in which quotes and documents are compared."""
    folded = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return _SPACES.sub(" ", folded).strip().casefold()


def quote_in_document(quote: str, document: Document) -> bool | None:
    """True or False for a text document; None when it cannot be searched (a PDF)."""
    if document.text is None:
        return None
    needle = normalise(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return False
    return needle in normalise(document.text)
