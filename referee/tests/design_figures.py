"""The figure tripwire of the design sections that are written around sentences made from code.

A section of the design text (21.10 to 21.13) says its figures in sentences that its test makes
from the constants of the code. `figures_outside` takes those sentences out of the section, once
each, and returns the figures that are left, which no constant stands behind.
"""

import re

_FIGURE = re.compile(r"\d[\d,.]*%?|\b(?:third|half|quarter|twice|double)\b")


def figures_outside(
    text: str,
    phrases: list[str],
    *,
    names: tuple[str, ...] = (),
    patterns: tuple[str, ...] = (),
    last_section: int = 13,
) -> list[str]:
    """The figures left in `text` once each phrase has been taken out of it, once.

    A phrase that is not in the text exactly once raises `AssertionError`. What is not a figure of
    the code is left out first: the `names` (a milestone, a rule id), whatever the `patterns`
    match (an ordinal), and a reference to a section of the design, "21.1" to "21.<last_section>".
    """
    for phrase in sorted(phrases, key=len, reverse=True):
        assert text.count(phrase) == 1, phrase
        text = text.replace(phrase, " ", 1)
    for name in names:
        text = text.replace(name, " ")
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    text = re.sub(rf"(?<![\d.])21\.(?:[1-9]|1[0-{last_section - 10}])(?![\d%])", " ", text)
    return _FIGURE.findall(text)
