"""The small helpers the rule texts share."""

import pytest

from referee.rules.text import join_and, percent_exact, percent_near, sig, sig_up


@pytest.mark.parametrize(
    ("items", "text"),
    [([], ""), (["a"], "a"), (["a", "b"], "a and b"), (["a", "b", "c"], "a, b and c")],
)
def test_a_list_is_joined_with_commas_and_an_and(items: list[str], text: str) -> None:
    assert join_and(items) == text


@pytest.mark.parametrize(
    ("value", "digits", "text"),
    [
        (0, 3, "0"),
        (1.673, 3, "1.67"),
        (-0.247, 3, "-0.247"),
        (131649, 3, "132,000"),
        (0.00005123, 3, "0.0000512"),
        (-0.00005123, 3, "-0.0000512"),
        (-0.00005, 3, "-0.0000500"),
        (
            9.996,
            3,
            "10.0",
        ),  # the carry: 9.996 rounds to 10, which has one more place before the point
        (1234.5, 4, "1,234"),
        (3.0, 3, "3.00"),
        (1e-6, 3, "0.00000100"),  # the smallest size that is written out
        (9.99e-7, 3, "9.99e-07"),  # below it, with an exponent
        (-2.5e-300, 3, "-2.50e-300"),
        (1e15, 3, "1.00e+15"),  # from here on, with an exponent: not 300 digits of float noise
        (123456789012345.0, 3, "123,000,000,000,000"),
        (1e300, 4, "1.000e+300"),
    ],
)
def test_a_figure_is_shown_to_a_number_of_significant_figures(value, digits, text) -> None:
    assert sig(value, digits) == text


@pytest.mark.parametrize(
    ("share", "level", "text"),
    [
        (0.133333, 0.10, "13.3%"),
        (0.10, 0.10, "10.0%"),
        (0.1004, 0.10, "10.04%"),  # beyond the level: 10.0% would look to be at it
        (0.0996, 0.10, "10.0%"),  # at the level is not beyond it, as the exact figure is not
        (0.09999, 0.10, "10.0%"),
        (-0.042, 0.10, "-4.2%"),
        (-0.0001, 0.10, "0.0%"),  # no negative zero
        (0.0, 0.10, "0.0%"),
        (1.2222, 0.10, "122.2%"),
    ],
)
def test_a_share_keeps_the_side_of_the_level_that_it_is_on(share, level, text) -> None:
    assert percent_near(share, level) == text


@pytest.mark.parametrize(
    ("share", "level", "text"),
    [
        (0.072, 0.072, "7.2%"),  # 100 * 0.072 is 7.199999999999999 in floats; the decimal is 7.2
        (0.1444, 0.144, "14.44%"),
        (0.1441, 0.144, "14.41%"),
        (0.072001, 0.072, "7.2001%"),
        (0.29, 0.29, "29.0%"),
        (0.0125, 0.0125, "1.25%"),  # at the level, in the level's own words
        (0.018, 0.018, "1.8%"),
        (0.0124, 0.0125, "1.2%"),  # under it, and 1.2 is under it
        (0.0126, 0.0125, "1.3%"),  # past it, and 1.3 is past it
        (0.0134, 0.013, "1.34%"),  # 1.3 would read as at the level, not past it
        (1e12, 0.10, "1.000e+14%"),  # beyond the digits worth writing out
        (1e10, 0.10, "1.000e+12%"),  # from a hundred billion percent
        (9.9e9, 0.10, "990000000000.0%"),  # and not before
        (1.8e306, 0.10, "1.800e+308%"),  # 100 * share would be infinity: the decimal is not
        (3e307, 0.10, "3.000e+309%"),
        (1e308, 0.10, "1.000e+310%"),
        (-3e307, 0.10, "-3.000e+309%"),
    ],
)
def test_a_share_is_compared_with_the_level_on_the_decimals_they_are_written_with(
    share, level, text
) -> None:
    assert percent_near(share, level) == text


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_a_figure_that_is_not_a_finite_number_cannot_be_shown(value) -> None:
    with pytest.raises(ValueError, match="not a finite number"):
        sig(value)


@pytest.mark.parametrize(
    ("share", "text"),
    [
        (1e-300, "1e-298%"),
        (1e300, "1e+302%"),
        (5e-324, "5e-322%"),
        (0.0001, "0.01%"),
        (0.0333, "3.33%"),
        (1.0, "100.0%"),
        (10.0, "1000.0%"),
        (0.0, "0.0%"),
        (1e-8, "0.000001%"),  # the smallest percentage that is written out
        (9e-9, "9e-7%"),
        (9.99e12, "999000000000000.0%"),  # the largest sizes that are written out
        (1e13, "1e+15%"),
    ],
)
def test_a_registered_share_is_written_as_it_was_registered(share, text) -> None:
    assert percent_exact(share) == text


@pytest.mark.parametrize(
    ("value", "digits", "text"),
    [
        (50.0, 3, "50.0"),
        (100 / 1.7, 3, "58.9"),  # 58.8235 is shown as 58.9: never under the limit it states
        (58.82, 3, "58.9"),
        (58.8, 3, "58.8"),
        (0.0004567, 3, "0.000457"),
        (1234.5, 3, "1,240"),
        (1e-300, 3, "1.00e-300"),
    ],
)
def test_a_limit_is_rounded_up_never_down(value, digits, text) -> None:
    assert sig_up(value, digits) == text
    assert float(sig_up(value, digits).replace(",", "")) >= value * (1 - 1e-12)


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_a_limit_must_be_a_finite_number_above_zero(value) -> None:
    with pytest.raises(ValueError, match="finite number above 0"):
        sig_up(value)
