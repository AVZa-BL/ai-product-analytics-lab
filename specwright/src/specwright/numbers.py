"""Is the number a draft states in the quote it cites, and is that quote approximate?

Both are deterministic and deliberately plain. A number is in a quote if the quote writes it with
digits (`5,000`, `12.5`, `30%`, `5k`, `2 weeks` for 14 days). A number written in words (`two
weeks`, `half`) is not found, so a draft that states it must label the value `inferred`, where it
is listed for the analyst to confirm. Approximate wording ("about", "a few", "roughly") is never
a number: a claim that cites it must be `ambiguous`.
"""

from __future__ import annotations

import math
import re

_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|k\b|m\b|weeks?\b|days?\b)?",
    re.IGNORECASE,
)

# Words that make a quantity approximate. "about" counts only straight before a number: "we care
# about a 10% lift" is not approximate, "about 10%" is. Quantity words with no digits ("a few",
# "several") are listed too, because a number cannot be read from them.
_NEAR = r"roughly|approximately|approx\.?|around|nearly|almost|circa|ca\."
_BOUND = (
    r"about|estimated|maybe|perhaps|probably|likely|up to|at least|at most|more or less|between"
)
HEDGES = re.compile(
    rf"\b(?:{_NEAR})\s+(?:an?\s+|the\s+)?[$€£]?\d"
    rf"|\b(?:{_BOUND})\s+[$€£]?\d"
    r"|\b(?:a few|few|several|a couple(?: of)?|couple of|some|many|dozens?)\b"
    r"|\d\s*(?:or so|-?ish|\+)|~\s*\d|±|\+/-",
    re.IGNORECASE,
)


def numbers_in(text: str) -> set[float]:
    """Every number the text writes with digits, with its readings: a percentage is also a
    fraction, `5k` is 5,000, `2 weeks` is 14 days."""
    found: set[float] = set()
    for match in _NUMBER.finditer(text):
        number = float(match.group(1).replace(",", ""))
        suffix = (match.group(2) or "").lower()
        found.add(number)
        if suffix == "%":
            found.add(number / 100)
        elif suffix == "k":
            found.add(number * 1_000)
        elif suffix == "m":
            found.add(number * 1_000_000)
        elif suffix.startswith("week"):
            found.add(number * 7)
        # `50/50`: each side is a share of 100
        if suffix == "" and number <= 100:
            found.add(number / 100)
    return found


def quote_has_number(quote: str, value: float) -> bool:
    return any(math.isclose(value, n, rel_tol=1e-9, abs_tol=1e-12) for n in numbers_in(quote))


def hedges_in(quote: str) -> list[str]:
    """The approximate words of a quote, in the order written."""
    return [m.group(0) for m in HEDGES.finditer(quote)]
