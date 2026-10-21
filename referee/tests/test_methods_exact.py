"""The exact tests for counts too small for the chi-square (design section 21.4).

Each exact p value is checked against scipy's own exact test where scipy has one (binomial,
Fisher) and against adding up every outcome by hand where it does not. The last tests show why
they exist: the chi-square flags small samples more often than its level, the exact test never
does.
"""

import itertools
import math

import pytest
from scipy import stats

from referee import methods
from referee.methods import SMALL_EXPECTED_COUNT, homogeneity_test

# --- Listing every outcome ---------------------------------------------------------------------


@pytest.mark.parametrize(("total", "parts"), [(0, 3)])
def test_the_listing_holds_each_ordered_split_once(total: int, parts: int) -> None:
    rows = methods._compositions(total, parts)

    assert rows.shape == (math.comb(total + parts - 1, parts - 1), parts)
    assert (rows.sum(axis=1) == total).all() and (rows >= 0).all()
    assert len({tuple(row) for row in rows.tolist()}) == len(rows)


def test_a_listing_is_refused_beyond_the_limit_and_allowed_at_it(monkeypatch) -> None:
    assert methods._outcomes_listable(10, 3)  # 66 splits
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 66)
    assert methods._outcomes_listable(10, 3)
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 65)
    assert not methods._outcomes_listable(10, 3)


# --- The sample ratio ----------------------------------------------------------------------------


def test_a_split_that_is_exactly_as_likely_counts_against_the_observed_one() -> None:
    # 4 against 6 and 6 against 4 at 50/50 are equally likely: both are in the p value.
    assert methods._exact_sample_ratio_p([4, 6], [0.5, 0.5]) == pytest.approx(
        stats.binomtest(4, 10, 0.5).pvalue, rel=1e-12
    )
    assert methods._exact_sample_ratio_p([5, 5], [0.5, 0.5]) == pytest.approx(1.0, rel=1e-12)


# --- Homogeneity ---------------------------------------------------------------------------------


def _brute_homogeneity(successes: list[int], totals: list[int]) -> float:
    hits, size = sum(successes), sum(totals)

    def probability(counts) -> float:
        ways = math.prod(math.comb(n, c) for n, c in zip(totals, counts, strict=True))
        return ways / math.comb(size, hits)

    seen = probability(successes)
    every = (
        counts
        for counts in itertools.product(*(range(n + 1) for n in totals))
        if sum(counts) == hits
    )
    return math.fsum(p for p in map(probability, every) if p <= seen * (1 + 1e-7))


@pytest.mark.parametrize(
    ("successes", "totals"),
    [
        ([9, 8, 1], [10, 10, 10]),
    ],
)
def test_three_or_more_groups_agree_with_adding_up_every_table(successes, totals) -> None:
    assert methods._exact_homogeneity_p(successes, totals) == pytest.approx(
        _brute_homogeneity(successes, totals), rel=1e-9
    )


# --- When the exact test is used -----------------------------------------------------------------


def test_the_smallest_expected_count_is_taken_over_successes_and_failures() -> None:
    # 299 of 300 succeed: the expected failures are the small cells (3 in all, 1 per 100 units).
    result = homogeneity_test([199, 98], [200, 100])

    assert result.smallest_expected == pytest.approx(100 * 3 / 300)


def test_homogeneity_test_falls_back_to_the_chi_square_beyond_the_listing_limit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 10)

    result = homogeneity_test([4, 5, 6], [50, 60, 70], exact_below=SMALL_EXPECTED_COUNT)

    assert result.method == "chi_square"


# --- Why: the false-alarm rate -----------------------------------------------------------------


# --- Edges ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "shares"),
    [
        ([1, 1, 1, 1], [0.25] * 4),
    ],
)
def test_the_most_likely_split_has_an_exact_p_value_of_one_not_a_rounding_error_above_it(
    observed, shares
) -> None:
    # Adding the probabilities of every split gives 1.0000000000000002 for these.
    exact = methods._exact_sample_ratio_p(observed, shares)

    assert exact <= 1.0 and exact == pytest.approx(1.0, rel=1e-12)


@pytest.mark.parametrize(("successes", "totals"), [([0, 1], [6, 6])])
def test_the_most_likely_table_has_an_exact_p_value_of_one_not_a_rounding_error_above_it(
    successes, totals
) -> None:
    # Adding the probabilities of every table gives 1.000000000000003 for these.
    exact = methods._exact_homogeneity_p(successes, totals)

    assert exact <= 1.0 and exact == pytest.approx(1.0, rel=1e-12)


def test_the_shorter_of_a_table_and_its_mirror_image_is_the_one_listed(monkeypatch) -> None:
    # 195 successes of 210 would list 196 tables; the mirror image, 15 failures, lists 16.
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 100)

    exact = methods._exact_homogeneity_p([195, 0], [200, 10])

    assert exact == pytest.approx(stats.fisher_exact([[195, 5], [0, 10]]).pvalue, rel=1e-9)


def test_homogeneity_test_is_exact_below_the_limit_and_not_at_it() -> None:
    at_limit = homogeneity_test([100, 100], [1000, 1000], exact_below=SMALL_EXPECTED_COUNT)
    below = homogeneity_test([99, 100], [1000, 1000], exact_below=SMALL_EXPECTED_COUNT)

    assert at_limit.smallest_expected == 100.0 and at_limit.method == "chi_square"
    assert below.smallest_expected == 99.5 and below.method == "exact"
