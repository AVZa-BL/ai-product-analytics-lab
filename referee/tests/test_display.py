"""The display cap: it shows at most the limit, says so, and never changes a count."""


import pytest

from referee.display import cap_listing


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
