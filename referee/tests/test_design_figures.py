"""The figure tripwire of the design sections finds a figure that is there and only that."""

import pytest
from design_figures import figures_outside

SENTENCES = ["the 95% interval", "fewer than 10 players"]
TEXT = f"A: {SENTENCES[0]}. See 21.3, 21.12 and 4b-2 (RES-004). B: {SENTENCES[1]}."
NAMES = ("4b-2", "RES-004")


@pytest.mark.parametrize(
    ("extra", "found"),
    [
        ("", []),
        (" It fires at 10%.", ["10%"]),
        (" It is 0.35 times that.", ["0.35"]),
        (" See 21.14 now.", ["21.14"]),
        (" In 12 cases.", ["12"]),
        (" At a third of it.", ["third"]),
        (" It is half of it, twice that.", ["half", "twice"]),
    ],
)
def test_a_figure_that_no_sentence_stands_behind_is_found(extra: str, found: list[str]) -> None:
    assert figures_outside(TEXT + extra, SENTENCES, names=NAMES) == found


def test_what_is_not_a_figure_of_the_code_is_left_out() -> None:
    text = "the 5th and 95th percentile, 21.9 and 21.12 and the milestone 4b-2 of RES-004."

    assert (
        figures_outside(text, [], names=("4b-2", "RES-004"), patterns=(r"(?<!\d)(5|95)th\b",)) == []
    )
    assert figures_outside(text, [], names=("4b-2", "RES-004")) == ["5", "95"]
    assert figures_outside(text, [], names=("4b-2", "RES-004"), last_section=11) == [
        "5",
        "95",
        "21.12",
    ]


def test_a_sentence_that_the_text_does_not_hold_exactly_once_is_an_error() -> None:
    with pytest.raises(AssertionError):
        figures_outside(TEXT, [*SENTENCES, "not in the text"])
    with pytest.raises(AssertionError):
        figures_outside(TEXT + " " + SENTENCES[0], SENTENCES)
