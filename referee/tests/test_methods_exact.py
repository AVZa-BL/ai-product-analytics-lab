"""The exact tests for counts too small for the chi-square (design section 21.4).

Each exact p value is checked against scipy's own exact test where scipy has one (binomial,
Fisher) and against adding up every outcome by hand where it does not. The last tests show why
they exist: the chi-square flags small samples more often than its level, the exact test never
does.
"""

import itertools
import math

import numpy as np
import pytest
from scipy import stats

from referee import methods
from referee.methods import SMALL_EXPECTED_COUNT, SRM_ALPHA, homogeneity_test, srm_test

# --- Listing every outcome ---------------------------------------------------------------------


@pytest.mark.parametrize(("total", "parts"), [(0, 3), (1, 1), (5, 2), (6, 3), (4, 5), (12, 4)])
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


@pytest.mark.parametrize("n", [1, 2, 5, 10, 37, 100, 400])
@pytest.mark.parametrize("share", [0.5, 0.3, 0.1, 0.02])
def test_two_arms_agree_with_scipys_exact_binomial_test(n: int, share: float) -> None:
    for x in range(0, n + 1, max(1, n // 25)):
        ours = methods._exact_sample_ratio_p([x, n - x], [share, 1 - share])

        assert ours == pytest.approx(stats.binomtest(x, n, share).pvalue, rel=1e-9, abs=1e-300)


def _brute_multinomial(observed: list[int], shares: list[float]) -> float:
    total = sum(observed)

    def probability(counts) -> float:
        coefficient = math.factorial(total)
        for count in counts:
            coefficient //= math.factorial(count)
        return coefficient * math.prod(s**c for s, c in zip(shares, counts, strict=True))

    seen = probability(observed)
    every = (
        counts
        for counts in itertools.product(range(total + 1), repeat=len(observed))
        if sum(counts) == total
    )
    return math.fsum(p for p in map(probability, every) if p <= seen * (1 + 1e-7))


@pytest.mark.parametrize(
    ("observed", "shares"),
    [
        ([3, 5, 12], [0.2, 0.3, 0.5]),
        ([0, 0, 9], [1 / 3, 1 / 3, 1 / 3]),
        ([4, 4, 4, 0], [0.25, 0.25, 0.25, 0.25]),
        ([1, 8, 3, 2], [0.1, 0.4, 0.3, 0.2]),
    ],
)
def test_three_or_more_arms_agree_with_adding_up_every_split(observed, shares) -> None:
    assert methods._exact_sample_ratio_p(observed, shares) == pytest.approx(
        _brute_multinomial(observed, shares), rel=1e-9
    )


def test_a_split_that_is_exactly_as_likely_counts_against_the_observed_one() -> None:
    # 4 against 6 and 6 against 4 at 50/50 are equally likely: both are in the p value.
    assert methods._exact_sample_ratio_p([4, 6], [0.5, 0.5]) == pytest.approx(
        stats.binomtest(4, 10, 0.5).pvalue, rel=1e-12
    )
    assert methods._exact_sample_ratio_p([5, 5], [0.5, 0.5]) == pytest.approx(1.0, rel=1e-12)


def test_there_is_no_exact_sample_ratio_p_beyond_the_listing_limit(monkeypatch) -> None:
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 10)

    assert methods._exact_sample_ratio_p([2, 3, 4], [0.2, 0.3, 0.5]) is None


# --- Homogeneity ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("first", "second"), [(10, 10), (30, 5), (100, 8), (500, 40), (900, 100)])
def test_two_groups_agree_with_scipys_fisher_exact_test(first: int, second: int) -> None:
    for a in range(0, min(first, 8) + 1):
        for b in range(0, min(second, 8) + 1):
            if a + b in (0, first + second):
                continue
            ours = methods._exact_homogeneity_p([a, b], [first, second])
            reference = stats.fisher_exact([[a, first - a], [b, second - b]]).pvalue

            assert ours == pytest.approx(reference, rel=1e-9, abs=0)


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
        ([2, 0, 5], [10, 8, 12]),
        ([0, 0, 3], [6, 6, 6]),
        ([3, 1, 1, 4], [7, 5, 9, 6]),
        ([9, 8, 1], [10, 10, 10]),
    ],
)
def test_three_or_more_groups_agree_with_adding_up_every_table(successes, totals) -> None:
    assert methods._exact_homogeneity_p(successes, totals) == pytest.approx(
        _brute_homogeneity(successes, totals), rel=1e-9
    )


def test_a_table_and_its_mirror_image_have_one_p_value() -> None:
    successes, totals = [2, 7, 1], [30, 25, 20]
    mirror = [n - s for s, n in zip(successes, totals, strict=True)]

    assert methods._exact_homogeneity_p(successes, totals) == pytest.approx(
        methods._exact_homogeneity_p(mirror, totals), rel=1e-12
    )


def test_the_exact_homogeneity_p_of_the_committed_exports_late_exposure() -> None:
    # 71 / 77 / 50 late of 997 / 1,046 / 781 exposed: 19,900 tables to add up.
    exact = methods._exact_homogeneity_p([71, 77, 50], [997, 1046, 781])

    assert exact == pytest.approx(0.7215426614, rel=1e-8)


def test_there_is_no_exact_homogeneity_p_beyond_the_listing_limit(monkeypatch) -> None:
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 10)

    assert methods._exact_homogeneity_p([4, 5, 6], [50, 60, 70]) is None


# --- When the exact test is used -----------------------------------------------------------------


def test_srm_test_keeps_the_chi_square_unless_asked_for_the_exact_test() -> None:
    result = srm_test([2, 8], [0.5, 0.5])

    assert result.method == "chi_square"
    assert result.p_value == pytest.approx(stats.chi2.sf(3.6, 1), rel=1e-12)


def test_srm_test_uses_the_exact_test_when_an_expected_count_is_below_the_limit() -> None:
    result = srm_test([2, 8], [0.5, 0.5], exact_below=SMALL_EXPECTED_COUNT)

    assert result.method == "exact"
    assert result.p_value == pytest.approx(stats.binomtest(2, 10, 0.5).pvalue, rel=1e-12)
    assert result.chi_square == pytest.approx(3.6, rel=1e-12)  # still reported, as a description
    assert result.expected == (5.0, 5.0) and result.degrees_of_freedom == 1


def test_the_limit_is_on_the_smallest_expected_count_and_it_is_open_at_the_limit() -> None:
    at_limit = srm_test([100, 100], [0.5, 0.5], exact_below=SMALL_EXPECTED_COUNT)
    just_below = srm_test([99, 100], [0.5, 0.5], exact_below=SMALL_EXPECTED_COUNT)

    assert at_limit.method == "chi_square"  # the smallest expected count is 100, not below it
    assert just_below.method == "exact"  # 99.5


def test_a_lopsided_allocation_makes_the_test_exact_although_the_total_is_large() -> None:
    lopsided = srm_test([9950, 50], [0.995, 0.005], exact_below=SMALL_EXPECTED_COUNT)
    balanced = srm_test([500, 500], [0.5, 0.5], exact_below=SMALL_EXPECTED_COUNT)

    assert lopsided.method == "exact" and balanced.method == "chi_square"


def test_srm_test_keeps_the_chi_square_when_there_are_too_many_splits_to_list(monkeypatch) -> None:
    monkeypatch.setattr(methods, "_ENUMERATION_LIMIT", 10)

    result = srm_test([2, 3, 4], [0.2, 0.3, 0.5], exact_below=SMALL_EXPECTED_COUNT)

    assert result.method == "chi_square"
    assert result.p_value == pytest.approx(stats.chi2.sf(result.chi_square, 2), rel=1e-12)


def test_homogeneity_test_keeps_the_chi_square_unless_asked_for_the_exact_test() -> None:
    result = homogeneity_test([0, 1], [900, 100])

    assert result.method == "chi_square"
    assert result.smallest_expected == pytest.approx(100 * 1 / 1000)


def test_homogeneity_test_uses_the_exact_test_when_an_expected_count_is_below_the_limit() -> None:
    result = homogeneity_test([0, 2], [9000, 1000], exact_below=SMALL_EXPECTED_COUNT)

    assert result.method == "exact"
    assert result.p_value == pytest.approx(
        stats.fisher_exact([[0, 9000], [2, 998]]).pvalue, rel=1e-9
    )
    assert result.smallest_expected == pytest.approx(2 * 1000 / 10000)


def test_homogeneity_test_keeps_the_chi_square_when_every_expected_count_reaches_the_limit() -> (
    None
):
    result = homogeneity_test([300, 400], [2000, 2000], exact_below=SMALL_EXPECTED_COUNT)

    assert result.method == "chi_square" and result.smallest_expected == pytest.approx(350.0)


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


def _flag_probability(n: int, share: float, alpha: float, **options) -> float:
    """P(srm_test flags) for n units split by chance at the registered share (exact sum)."""
    counts = range(n + 1)
    flags = [
        srm_test([n - k, k], [1 - share, share], alpha=alpha, **options).flagged for k in counts
    ]
    pmf = stats.binom.pmf(np.arange(n + 1), n, share)
    return float(pmf[np.array(flags)].sum())


@pytest.mark.parametrize(("n", "share"), [(50, 0.1), (200, 0.05), (400, 0.01), (80, 0.5)])
def test_the_exact_test_never_flags_more_often_than_its_level_where_the_chi_square_does(
    n: int, share: float
) -> None:
    alpha = SRM_ALPHA / 4

    exact = _flag_probability(n, share, alpha, exact_below=SMALL_EXPECTED_COUNT)

    assert exact <= alpha


def test_the_chi_square_flags_a_small_sample_more_often_than_its_level() -> None:
    # 50 units at 10%: 5 expected in the small arm. The chi-square at 0.00025 flags 4 times as
    # often as it promises (section 21.4); the exact test no more often than it promises.
    alpha = SRM_ALPHA / 4

    chi_square = _flag_probability(50, 0.1, alpha)
    exact = _flag_probability(50, 0.1, alpha, exact_below=SMALL_EXPECTED_COUNT)

    assert chi_square > 3 * alpha and exact <= alpha


# --- Edges ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observed", "shares"),
    [
        ([2, 2], [0.5, 0.5]),
        ([4, 0], [0.9, 0.1]),
        ([1, 1, 1, 1], [0.25] * 4),
        ([0, 1, 1], [1 / 3] * 3),
    ],
)
def test_the_most_likely_split_has_an_exact_p_value_of_one_not_a_rounding_error_above_it(
    observed, shares
) -> None:
    # Adding the probabilities of every split gives 1.0000000000000002 for these.
    exact = methods._exact_sample_ratio_p(observed, shares)

    assert exact <= 1.0 and exact == pytest.approx(1.0, rel=1e-12)


@pytest.mark.parametrize(
    ("successes", "totals"), [([0, 1], [6, 6]), ([2, 2], [6, 6]), ([3, 3], [6, 6])]
)
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
