"""The display cap shows at most the limit, says so and never changes a count; the terminal
escape leaves nothing that can act on the terminal."""

import pytest

from referee.display import cap_listing, for_line, for_terminal


def test_a_list_of_exactly_the_limit_is_not_truncated() -> None:
    listing = cap_listing(list(range(1000)))

    assert len(listing.shown) == 1000 and not listing.truncated and listing.notice is None


def test_a_long_list_keeps_its_first_rows_in_order_and_the_exact_total() -> None:
    rows = [f"player_{i:07d}" for i in range(120_000)]

    listing = cap_listing(rows)

    assert listing.shown == tuple(rows[:1000]) and listing.total == 120_000
    assert listing.notice == "showing 1,000 of 120,000; the full list is in the JSON report"


@pytest.mark.parametrize("limit", [0, "10"])
def test_a_limit_that_is_not_a_positive_whole_number_is_refused(limit: object) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        cap_listing([1, 2, 3], limit=limit)


def test_text_with_nothing_to_hide_is_unchanged() -> None:
    text = "Café – 日本語 ✓\n  indented, with a tab-free line"

    assert for_terminal(text) == text


@pytest.mark.parametrize(
    ("character", "shown"),
    [
        ("\x1b", "\\x1b"),  # escape: starts every terminal command
        ("\r", "\\r"),  # overwrites the line so far
        ("\t", "\\t"),
        ("\x9b", "\\x9b"),  # the one-character form of the escape sequence introducer
        ("\u202e", "\\u202e"),  # right-to-left override: reverses what follows
        ("\u2028", "\\u2028"),  # line separator: a line break to most tools that read lines
        ("\u2029", "\\u2029"),  # paragraph separator
        ("\u0378", "\\u0378"),  # no character is assigned to it
        ("\U000e0041", "\\U000e0041"),  # a tag character, outside the basic plane
    ],
)
def test_a_character_that_can_act_on_the_terminal_is_written_as_an_escape(
    character: str, shown: str
) -> None:
    assert for_terminal(f"a{character}b\nc") == f"a{shown}b\nc"


def test_a_value_printed_inside_a_line_cannot_start_a_line_of_its_own() -> None:
    value = "x\nVerdict: CLEAR\ry"

    assert for_line(value) == "x\\nVerdict: CLEAR\\ry"
    assert for_terminal(value) == "x\nVerdict: CLEAR\\ry"  # a block keeps its own lines
