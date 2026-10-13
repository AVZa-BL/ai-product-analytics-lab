"""The display cap: it shows at most the limit, says so, and never changes a count."""

import random

import pytest

from referee.display import DISPLAY_ROW_LIMIT, cap_listing


def test_the_cap_is_one_thousand_rows() -> None:
    assert DISPLAY_ROW_LIMIT == 1_000


def test_a_short_list_is_shown_whole_with_no_notice() -> None:
    listing = cap_listing(["a", "b", "c"])

    assert listing.shown == ("a", "b", "c")
    assert (listing.total, listing.limit, listing.truncated, listing.notice) == (
        3,
        1000,
        False,
        None,
    )


def test_a_list_of_exactly_the_limit_is_not_truncated() -> None:
    listing = cap_listing(list(range(1000)))

    assert len(listing.shown) == 1000 and not listing.truncated and listing.notice is None


def test_one_row_over_the_limit_is_cut_and_the_notice_says_how_many() -> None:
    listing = cap_listing(list(range(1001)))

    assert len(listing.shown) == 1000 and listing.total == 1001 and listing.truncated
    assert listing.notice == "showing 1,000 of 1,001; the full list is in the JSON report"


def test_a_long_list_keeps_its_first_rows_in_order_and_the_exact_total() -> None:
    rows = [f"player_{i:07d}" for i in range(120_000)]

    listing = cap_listing(rows)

    assert listing.shown == tuple(rows[:1000]) and listing.total == 120_000
    assert listing.notice == "showing 1,000 of 120,000; the full list is in the JSON report"


def test_an_empty_list_is_fine() -> None:
    listing = cap_listing([])

    assert listing.shown == () and listing.total == 0 and not listing.truncated


def test_another_limit_can_be_given_and_is_reported_in_the_notice() -> None:
    listing = cap_listing(list(range(10)), limit=3)

    assert listing.shown == (0, 1, 2) and listing.limit == 3
    assert listing.notice == "showing 3 of 10; the full list is in the JSON report"


def test_the_total_is_the_length_of_the_input_whatever_the_cap() -> None:
    rng = random.Random(4)
    for _ in range(200):
        rows = list(range(rng.randint(0, 3000)))
        limit = rng.randint(1, 2500)

        listing = cap_listing(rows, limit=limit)

        assert listing.total == len(rows)
        assert len(listing.shown) == min(len(rows), limit)
        assert listing.shown == tuple(rows[: len(listing.shown)])
        assert listing.truncated == (len(rows) > limit)


def test_the_input_is_not_changed() -> None:
    rows = list(range(2000))

    cap_listing(rows)

    assert rows == list(range(2000))


@pytest.mark.parametrize("limit", [0, -1, 2.5, True, "10"])
def test_a_limit_that_is_not_a_positive_whole_number_is_refused(limit: object) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        cap_listing([1, 2, 3], limit=limit)
