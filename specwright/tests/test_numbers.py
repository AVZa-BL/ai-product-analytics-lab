"""Is a number in its quote, and is the quote approximate? Reference cases for both."""

import pytest

from specwright.numbers import hedges_in, quote_has_number


@pytest.mark.parametrize(
    ("quote", "value", "found"),
    [
        ("Today it is 4.2%.", 0.042, True),  # a percentage is a fraction
        ("Today it is 4.2%.", 4.2, True),
        ("3.0% today", 0.03, True),
        ("12,000 players a day", 12000, True),
        ("5k players", 5000, True),
        ("The test runs for 3 weeks (21 days)", 21, True),
        ("run it for 2 weeks", 14, True),  # an explicit number of weeks is days times 7
        ("Assignment is per player, 50/50", 0.5, True),
        ("Alpha 0.05, power 80%, two-sided", 0.8, True),
        ("a ten percent lift", 0.1, False),  # a number in words is not found: it must be inferred
        ("12,000 players a day", 1200, False),
        ("12,000 players a day", 12, False),
        ("we need 20,000 players", 2000, False),
        ("4.2%", 0.0421, False),
    ],
)
def test_a_number_is_found_only_when_the_quote_writes_it_in_digits(
    quote: str, value: float, found: bool
) -> None:
    assert quote_has_number(quote, value) is found


@pytest.mark.parametrize(
    ("quote", "hedged"),
    [
        ("about 10%", True),
        ("roughly a 10% relative lift", True),
        ("approximately 14 days", True),
        ("A few thousand players open it every day", True),
        ("several weeks", True),
        ("up to 14 days", True),
        ("at least 7 days", True),
        ("between 5,000 and 7,000 players", True),
        ("~14 days", True),
        ("30 or so players", True),
        ("We care about a 10% relative lift", False),  # "about" not straight before a number
        ("12,000 players a day open the shop", False),
        ("Today it is 4.2%.", False),
        ("The test runs for 3 weeks (21 days)", False),
        ("not less than 14 days in any case", False),
    ],
)
def test_approximate_wording_is_recognised_and_plain_wording_is_not(
    quote: str, hedged: bool
) -> None:
    assert bool(hedges_in(quote)) is hedged
