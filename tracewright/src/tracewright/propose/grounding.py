"""Check that quoted evidence really appears in the documents.

A model asked to justify a recommendation can invent a plausible quotation. This is the
deterministic defence: a quote that claims to come from a text document must be found in it.

The comparison is forgiving about typography only: case, runs of whitespace, curly quotes,
hyphens and dashes (U+2010 to U+2015, minus), zero-width characters, and the `*` and backtick
marks of Markdown emphasis and code. Other markup (`_emphasis_`, links, escapes) must be quoted
as it appears in the file. It is not forgiving about words: a quote that starts or ends inside
a word or a number does not match (`entry cost of 50` is not found in `entry cost of 500`).
A quote that passes proves the words are in the document, not that the model read them
correctly, and not that the event it supports is the right one.
"""

from __future__ import annotations

import re
import unicodedata

from tracewright.propose.documents import Document

MIN_QUOTE_CHARS = 8

_APOSTROPHES = "‘’ʼ"
_DOUBLE_QUOTES = "“”„‟"
_DASHES = "‐‑‒–—―−﹘﹣－"
_INVISIBLE = "​‌‍⁠﻿­"

_TRANSLATE = str.maketrans(
    {
        **{c: "'" for c in _APOSTROPHES},
        **{c: '"' for c in _DOUBLE_QUOTES},
        **{c: "-" for c in _DASHES},
        **{c: None for c in _INVISIBLE},
        " ": " ",
        "*": "",
        "`": "",
    }
)
_SPACES = re.compile(r"\s+")
_ALNUM = "0-9a-z"


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
    # A quote may not start or end inside a word or a number. The boundary is applied only on a
    # side where the quote's edge is an ASCII letter or digit, so that text in scripts written
    # without spaces between words (Chinese, Japanese) can still be quoted by the clause.
    lead = rf"(?<![{_ALNUM}])" if re.match(rf"[{_ALNUM}]", needle) else ""
    trail = rf"(?![{_ALNUM}]|[.,][0-9])" if re.search(rf"[{_ALNUM}]$", needle) else ""
    return re.search(lead + re.escape(needle) + trail, normalise(document.text)) is not None
