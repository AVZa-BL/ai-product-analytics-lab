"""The statistics: each function against an independent implementation or a known answer."""

import itertools
import math
import random

import numpy as np
import pytest
from scipy import stats
from statsmodels.stats.meta_analysis import combine_effects
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest
from statsmodels.stats.weightstats import CompareMeans, DescrStatsW

from referee.methods import (
    SRM_ALPHA,
    StatsError,
    benjamini_hochberg,
    benjamini_yekutieli,
    bonferroni,
    bootstrap_difference,
    cohort_heterogeneity,
    heavy_tail_measures,
    homogeneity_test,
    ratio_difference,
    ratio_estimate,
    srm_test,
    two_proportion_difference,
    welch_difference,
)

# --- Sample ratio mismatch ---------------------------------------------------------------


def test_the_flag_is_strictly_below_the_threshold() -> None:
    p = srm_test([60, 40], [0.5, 0.5]).p_value

    assert srm_test([60, 40], [0.5, 0.5], alpha=p).flagged is False
    assert srm_test([60, 40], [0.5, 0.5], alpha=p * 1.0001).flagged is True
    assert SRM_ALPHA == 0.001


@pytest.mark.parametrize(
    ("observed", "allocation", "alpha", "fragment"),
    [
        ([1, 2], [0.5, 0.25, 0.25], 0.001, "one count per arm"),
        ([10], [1.0], 0.001, "at least two arms"),
        ([10, -1], [0.5, 0.5], 0.001, "whole numbers of at least 0"),
        ([10, 2.5], [0.5, 0.5], 0.001, "whole numbers of at least 0"),
        ([10, True], [0.5, 0.5], 0.001, "whole numbers of at least 0"),
        ([10, 10], [0.5, 0.6], 0.001, "sum to 1"),
        ([10, 10], [1.0, 0.0], 0.001, "positive"),
        ([10, 10], [0.5, math.nan], 0.001, "finite"),
        ([0, 0], [0.5, 0.5], 0.001, "nothing to test"),
        ([10, 10], [0.5, 0.5], 0.0, "alpha"),
        ([10, 10], [0.5, 0.5], 1.0, "alpha"),
    ],
)
def test_input_that_cannot_be_tested_is_refused_with_the_reason(
    observed: list, allocation: list, alpha: float, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        srm_test(observed, allocation, alpha=alpha)


# --- Welch's t test ----------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_it_agrees_with_scipy_and_statsmodels_on_unequal_groups_and_variances(seed: int) -> None:
    rng = random.Random(seed)
    treatment = [rng.gauss(10.5, 4.0) for _ in range(rng.randint(20, 400))]
    control = [rng.gauss(10.0, 1.5) for _ in range(rng.randint(20, 400))]

    ours = welch_difference(treatment, control, alpha=0.05)
    scipy_result = stats.ttest_ind(treatment, control, equal_var=False)
    low, high = CompareMeans(DescrStatsW(treatment), DescrStatsW(control)).tconfint_diff(
        alpha=0.05, usevar="unequal"
    )

    assert ours.t_statistic == pytest.approx(scipy_result.statistic, rel=1e-10)
    assert ours.p_value == pytest.approx(scipy_result.pvalue, rel=1e-8, abs=0)
    assert ours.degrees_of_freedom == pytest.approx(scipy_result.df, rel=1e-10)
    assert (ours.ci_low, ours.ci_high) == pytest.approx((low, high), rel=1e-9)
    assert ours.confidence == 0.95


def test_values_whose_naive_sum_depends_on_order_still_give_one_exact_answer() -> None:
    # 1e16 + 1.0 loses the 1.0 when added first, so a plain sum changes with the order.
    values = [1e16, 1.0, -1e16, 2.0, 3.0, 0.5]
    control = [0.0, 1.0, 2.0, 5.0]

    answers = {welch_difference(list(order), control) for order in itertools.permutations(values)}

    assert len(answers) == 1


@pytest.mark.parametrize(
    ("treatment", "control", "fragment"),
    [
        ([1.0], [1.0, 2.0], "at least 2 values"),
        ([1.0, 2.0], [], "at least 2 values"),
        ([3.0, 3.0], [3.0, 3.0, 3.0], "neither group varies"),
        ([1.0, math.nan], [1.0, 2.0], "finite"),
        ([1.0, 2.0], [1.0, math.inf], "finite"),
    ],
)
def test_groups_that_cannot_be_compared_are_refused_with_the_reason(
    treatment: list, control: list, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        welch_difference(treatment, control)


def test_an_alpha_outside_zero_to_one_is_refused() -> None:
    for alpha in (0.0, 1.0, -0.1, 2.0):
        with pytest.raises(StatsError, match="alpha"):
            welch_difference([1.0, 2.0], [2.0, 3.0], alpha=alpha)


# --- Two proportions ---------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_it_agrees_with_statsmodels_on_random_counts(seed: int) -> None:
    rng = random.Random(seed)
    n1, n2 = rng.randint(200, 5000), rng.randint(200, 5000)
    x1, x2 = rng.randint(5, n1 // 2), rng.randint(5, n2 // 2)

    ours = two_proportion_difference(x1, n1, x2, n2, alpha=0.05)
    z, p = proportions_ztest([x1, x2], [n1, n2])
    low, high = confint_proportions_2indep(x1, n1, x2, n2, method="wald", alpha=0.05)

    assert ours.z_statistic == pytest.approx(z, rel=1e-10)
    assert ours.p_value == pytest.approx(p, rel=1e-8, abs=0)
    assert (ours.ci_low, ours.ci_high) == pytest.approx((low, high), rel=1e-9)


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ((0, 0, 1, 10), "not possible"),
        ((11, 10, 1, 10), "not possible"),
        ((-1, 10, 1, 10), "not possible"),
        ((1, 10, 11, 10), "not possible"),
        ((0, 10, 0, 20), "same outcome"),
        ((10, 10, 20, 20), "same outcome"),
        ((10, 10, 0, 20), "no width"),
    ],
)
def test_counts_that_cannot_be_tested_are_refused_with_the_reason(
    args: tuple, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        two_proportion_difference(*args)


def test_an_alpha_outside_zero_to_one_is_refused_for_proportions() -> None:
    with pytest.raises(StatsError, match="alpha"):
        two_proportion_difference(3, 10, 2, 10, alpha=1.5)


# --- Heavy tails -------------------------------------------------------------------------


def _lognormal(seed: int, n: int, sigma: float = 1.7) -> list[float]:
    rng = random.Random(seed)
    return [rng.lognormvariate(0.0, sigma) for _ in range(n)]


@pytest.mark.parametrize(
    ("n", "top_count"),
    [(2, 1), (99, 1), (100, 1), (101, 2), (199, 2), (200, 2), (201, 3), (1000, 10)],
)
def test_the_top_percent_is_the_ceiling_of_the_count_the_lab_readout_uses(
    n: int, top_count: int
) -> None:
    result = heavy_tail_measures([float(i) for i in range(1, n + 1)])

    assert result.top_count == top_count == (n + 99) // 100
    assert result.top_share == pytest.approx(
        sum(range(n - top_count + 1, n + 1)) / sum(range(1, n + 1))
    )


@pytest.mark.parametrize(
    ("values", "top_percent", "fragment"),
    [
        ([1.0], 1, "at least 2"),
        ([3.0, 3.0, 3.0], 1, "do not vary"),
        ([0.0, 0.0, 0.0], 1, "sum to 0"),
        ([1.0, -2.0, 5.0], 1, "non-negative"),
        ([1.0, math.nan, 5.0], 1, "finite"),
        ([1.0, 2.0, 5.0], 0, "from 1 to 99"),
        ([1.0, 2.0, 5.0], 100, "from 1 to 99"),
        ([1.0, 2.0, 5.0], 2.5, "from 1 to 99"),
        ([1.0, 2.0, 5.0], True, "from 1 to 99"),
    ],
)
def test_values_that_have_no_tail_to_describe_are_refused_with_the_reason(
    values: list, top_percent: object, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        heavy_tail_measures(values, top_percent=top_percent)


# --- The bootstrap -----------------------------------------------------------------------

GOLDEN_TREATMENT = [1.0, 2.0, 4.0, 8.0, 16.0, 3.0, 5.0, 9.0]
GOLDEN_CONTROL = [2.0, 2.5, 3.0, 3.5, 1.0, 6.0, 0.5]


def test_one_answer_is_pinned_so_a_changed_random_stream_is_noticed() -> None:
    result = bootstrap_difference(GOLDEN_TREATMENT, GOLDEN_CONTROL, seed=12345, resamples=1000)

    assert result.difference == pytest.approx(3.357142857142857, rel=1e-14)
    assert result.ci_low == pytest.approx(0.14241071428571425, rel=1e-12)
    assert result.ci_high == pytest.approx(6.929910714285714, rel=1e-12)
    assert (result.confidence, result.resamples, result.seed) == (0.95, 1000, 12345)


def test_it_is_close_to_welchs_interval_on_a_normal_sample() -> None:
    rng = random.Random(8)
    a = [rng.gauss(1.0, 2.0) for _ in range(500)]
    b = [rng.gauss(0.0, 2.0) for _ in range(500)]

    boot, welch = bootstrap_difference(a, b, seed=1, resamples=10_000), welch_difference(a, b)

    width = welch.ci_high - welch.ci_low
    assert boot.difference == welch.difference
    assert boot.ci_low == pytest.approx(welch.ci_low, abs=0.05 * width)
    assert boot.ci_high == pytest.approx(welch.ci_high, abs=0.05 * width)


def test_the_interval_covers_the_true_difference_about_as_often_as_it_claims() -> None:
    rng = random.Random(10)
    covered = 0
    runs = 200
    for run in range(runs):
        a = [rng.gauss(0.5, 1.0) for _ in range(40)]
        b = [rng.gauss(0.0, 1.0) for _ in range(40)]
        result = bootstrap_difference(a, b, seed=run, alpha=0.10, resamples=1000)
        covered += result.ci_low <= 0.5 <= result.ci_high

    assert 0.82 <= covered / runs <= 0.97  # a 90% interval; 3 binomial errors either side


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"seed": -1}, "seed"),
        ({"seed": 1.5}, "seed"),
        ({"seed": True}, "seed"),
        ({"seed": 1, "resamples": 100}, "fewer than 5 resamples"),
        ({"seed": 1, "alpha": 0.0}, "alpha"),
        ({"seed": 1, "alpha": 1.0}, "alpha"),
    ],
)
def test_a_bootstrap_that_cannot_be_trusted_is_refused_with_the_reason(
    kwargs: dict, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        bootstrap_difference([1.0, 2.0, 3.0], [2.0, 3.0, 4.0], **kwargs)


def test_groups_too_small_or_not_finite_are_refused_by_the_bootstrap() -> None:
    with pytest.raises(StatsError, match="at least 2"):
        bootstrap_difference([1.0], [1.0, 2.0], seed=1)
    with pytest.raises(StatsError, match="at least 2"):
        bootstrap_difference([1.0, 2.0], [], seed=1)
    with pytest.raises(StatsError, match="finite"):
        bootstrap_difference([1.0, math.inf], [1.0, 2.0], seed=1)


# --- The delta method --------------------------------------------------------------------


def _units(seed: int, n: int, ratio: float) -> tuple[list[float], list[float]]:
    """Per-unit denominators that vary a lot and numerators that follow them noisily."""
    rng = random.Random(seed)
    denominator = [rng.lognormvariate(1.0, 0.8) for _ in range(n)]
    numerator = [ratio * x + rng.gauss(0.0, 1.5) for x in denominator]
    return numerator, denominator


def test_with_a_constant_denominator_it_reduces_to_the_error_of_a_mean() -> None:
    numerator = [1.0, 4.0, 2.0, 8.0, 5.0]
    denominator = [2.0] * 5

    estimate = ratio_estimate(numerator, denominator)

    sample_sd = float(np.std(numerator, ddof=1))
    assert estimate.ratio == pytest.approx(np.mean(numerator) / 2.0)
    assert estimate.std_error == pytest.approx(sample_sd / math.sqrt(5) / 2.0)


def test_a_difference_of_ratios_combines_the_two_errors_and_detects_a_real_difference() -> None:
    y1, x1 = _units(3, 3000, 0.9)
    y0, x0 = _units(4, 3000, 0.8)

    result = ratio_difference(y1, x1, y0, x0)
    one, zero = ratio_estimate(y1, x1), ratio_estimate(y0, x0)

    assert result.difference == pytest.approx(one.ratio - zero.ratio)
    assert result.std_error == pytest.approx(math.sqrt(one.std_error**2 + zero.std_error**2))
    assert result.z_statistic == pytest.approx(result.difference / result.std_error)
    assert result.p_value == pytest.approx(
        2 * stats.norm.sf(abs(result.z_statistic)), rel=1e-9, abs=0
    )
    assert result.ci_low < 0.1 < result.ci_high and result.p_value < 0.05
    assert result.confidence == 0.95


@pytest.mark.parametrize(
    ("numerator", "denominator", "fragment"),
    [
        ([1.0, 2.0], [1.0], "one denominator per numerator"),
        ([1.0], [1.0], "at least 2 units"),
        ([1.0, 2.0], [1.0, -1.0], "mean denominator is 0"),
        ([2.0, 4.0, 6.0], [1.0, 2.0, 3.0], "does not vary"),
        ([1.0, math.nan], [1.0, 2.0], "finite"),
    ],
)
def test_a_ratio_that_cannot_be_estimated_is_refused_with_the_reason(
    numerator: list, denominator: list, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        ratio_estimate(numerator, denominator)


def test_an_alpha_outside_zero_to_one_is_refused_for_ratios() -> None:
    with pytest.raises(StatsError, match="alpha"):
        ratio_difference([1.0, 3.0], [1.0, 2.0], [2.0, 5.0], [1.0, 2.0], alpha=0.0)


# --- Cohort heterogeneity ----------------------------------------------------------------

# variant_b and variant_c against control by assignment week in the lab's seed-42 5,000-player
# data: the readout's published differences (+1.52, +0.64, -0.17 for variant_b), to 3 places.
PLANTED_FADE = ([1.519, 0.645, -0.174], [0.257, 0.239, 0.260])
NO_FADE = ([0.080, 0.158, 0.823], [0.254, 0.247, 0.315])


def test_a_hand_worked_example_with_unequal_weights() -> None:
    # weights 1 and 1/4: pooled 0.6, Q = 0.36 + 0.25 * 2.4^2 = 1.8; slope 3 with error 1/sqrt(0.2)
    result = cohort_heterogeneity([0.0, 3.0], [1.0, 2.0])

    assert result.pooled_difference == pytest.approx(0.6)
    assert result.q_statistic == pytest.approx(1.8)
    assert result.slope == pytest.approx(3.0)
    assert result.slope_std_error == pytest.approx(1 / math.sqrt(0.2))
    assert result.q_p_value == pytest.approx(result.slope_p_value, rel=1e-9)  # two cohorts: z^2 = Q


@pytest.mark.parametrize("seed", range(10))
def test_q_and_i_squared_agree_with_statsmodels_meta_analysis(seed: int) -> None:
    rng = random.Random(seed)
    k = rng.randint(2, 8)
    differences = [rng.gauss(0.5, 1.0) for _ in range(k)]
    errors = [rng.uniform(0.1, 0.8) for _ in range(k)]

    ours = cohort_heterogeneity(differences, errors)
    reference = combine_effects(np.asarray(differences), np.asarray(errors) ** 2)
    test = reference.test_homogeneity()
    fixed = reference.summary_frame().loc["fixed effect", "eff"]

    assert ours.q_statistic == pytest.approx(reference.q, rel=1e-10)
    assert ours.q_p_value == pytest.approx(test.pvalue, rel=1e-9, abs=0)
    assert ours.i_squared == pytest.approx(max(0.0, reference.i2), rel=1e-9, abs=1e-12)
    assert ours.pooled_difference == pytest.approx(fixed, rel=1e-10)


def test_identical_differences_give_q_zero_and_p_one() -> None:
    result = cohort_heterogeneity([0.5, 0.5, 0.5], [0.1, 0.2, 0.3])

    assert result.q_statistic == 0.0 and result.q_p_value == 1.0 and result.i_squared == 0.0
    assert result.slope == pytest.approx(0.0, abs=1e-12)  # rounding, not exactly 0.0
    assert result.slope_p_value == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize(
    ("args", "kwargs", "fragment"),
    [
        (([1.0], [0.1]), {}, "at least 2 cohorts"),
        (([1.0, 2.0], [0.1]), {}, "one standard error per difference"),
        (([1.0, 2.0], [0.1, 0.0]), {}, "above 0"),
        (([1.0, 2.0], [0.1, -0.2]), {}, "above 0"),
        (([1.0, math.nan], [0.1, 0.1]), {}, "finite"),
        (([1.0, 2.0], [0.1, math.inf]), {}, "finite"),
        (([1.0, 2.0, 3.0], [0.1, 0.1, 0.1]), {"positions": [0, 1]}, "one position per cohort"),
        (([1.0, 2.0, 3.0], [0.1, 0.1, 0.1]), {"positions": [4, 4, 4]}, "2 different positions"),
    ],
)
def test_cohorts_that_cannot_be_compared_are_refused_with_the_reason(
    args: tuple, kwargs: dict, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        cohort_heterogeneity(*args, **kwargs)


# --- Several comparisons at once ---------------------------------------------------------


def test_a_hand_worked_example_of_both_corrections() -> None:
    raw = [0.01, 0.04, 0.03, 0.005]

    bonf, bh = bonferroni(raw), benjamini_hochberg(raw)

    assert bonf.adjusted == pytest.approx((0.04, 0.16, 0.12, 0.02))
    assert bonf.rejected == (True, False, False, True)
    assert bh.adjusted == pytest.approx((0.02, 0.04, 0.04, 0.02))
    assert bh.rejected == (True, True, True, True)
    assert bonf.p_values == bh.p_values == tuple(raw)
    assert (bonf.method, bh.method, bonf.alpha) == ("bonferroni", "benjamini_hochberg", 0.05)


def test_adjusted_p_values_keep_the_order_of_the_input_and_never_fall_below_the_raw_ones() -> None:
    raw = [0.2, 0.001, 0.5, 0.03, 0.03, 0.9]

    for method in (bonferroni, benjamini_hochberg):
        adjusted = method(raw).adjusted

        assert all(a >= p for a, p in zip(adjusted, raw, strict=True))
        assert all(a <= 1.0 for a in adjusted)
        for i, first in enumerate(raw):  # a smaller p-value never gets a larger adjusted one
            for j, second in enumerate(raw):
                if first <= second:
                    assert adjusted[i] <= adjusted[j] + 1e-15
    assert all(
        bh <= bf
        for bh, bf in zip(benjamini_hochberg(raw).adjusted, bonferroni(raw).adjusted, strict=True)
    )


def test_the_decision_is_at_most_alpha_not_below_it() -> None:
    assert bonferroni([0.025, 0.9], alpha=0.05).rejected == (True, False)  # adjusted is 0.05
    assert benjamini_hochberg([0.025, 0.9], alpha=0.05).rejected == (True, False)


@pytest.mark.parametrize("method", [bonferroni, benjamini_hochberg])
@pytest.mark.parametrize(
    ("p_values", "alpha", "fragment"),
    [
        ([], 0.05, "at least one"),
        ([0.5, -0.1], 0.05, "between 0 and 1"),
        ([0.5, 1.1], 0.05, "between 0 and 1"),
        ([0.5, math.nan], 0.05, "finite"),
        ([0.5], 0.0, "alpha"),
        ([0.5], 1.0, "alpha"),
    ],
)
def test_input_that_cannot_be_corrected_is_refused_with_the_reason(
    method, p_values: list, alpha: float, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        method(p_values, alpha=alpha)


# --- Groups with no variation, whose floating-point mean is not their value -----------------

# Non-round constants such as 0.7: fsum([0.7] * 3) / 3 is not 0.7, so an exact test for a zero
# variance misses them. About one in ten of these cents values and sizes is affected.
CONSTANTS = [(cents / 100, n) for cents in range(1, 200) for n in (2, 3, 5, 10, 29)]


def test_a_constant_sample_has_no_kurtosis_whatever_the_value() -> None:
    for value, n in CONSTANTS:
        with pytest.raises(StatsError, match="do not vary"):
            heavy_tail_measures([value] * n)


def test_a_ratio_that_is_exactly_proportional_to_its_denominator_has_no_error() -> None:
    denominators = [0.1 * k for k in (1, 2, 3, 4, 5, 7)]
    for factor_cents in range(1, 150):
        factor = factor_cents / 100
        with pytest.raises(StatsError, match="does not vary"):
            ratio_estimate([factor * d for d in denominators], denominators)


def test_a_ratio_of_two_constants_has_no_error_whatever_the_values() -> None:
    for value, n in CONSTANTS:  # all of them: some sizes leave no rounding residue to catch
        with pytest.raises(StatsError, match="does not vary"):
            ratio_estimate([value] * n, [value / 3 + 0.1] * n)


def test_two_constant_groups_have_no_bootstrap_interval() -> None:
    for value, n in CONSTANTS[::9]:
        with pytest.raises(StatsError, match="neither group varies"):
            bootstrap_difference([value] * n, [value] * n, seed=1)


@pytest.mark.parametrize("scale", [1e-15, 1e-9, 1.0, 1e9])
@pytest.mark.parametrize("offset", [0.0, 1.0])
def test_real_spread_is_never_mistaken_for_no_variation_at_any_scale(
    scale: float, offset: float
) -> None:
    rng = random.Random(31)
    a = [offset * scale + scale * rng.gauss(0.0, 1e-3) for _ in range(40)]
    b = [offset * scale + scale * rng.gauss(0.0, 1e-3) for _ in range(35)]

    welch = welch_difference(a, b)
    reference = stats.ttest_ind(a, b, equal_var=False)

    assert welch.p_value == pytest.approx(reference.pvalue, rel=1e-6, abs=0)
    assert heavy_tail_measures([abs(v) + scale for v in a]).excess_kurtosis == pytest.approx(
        stats.kurtosis([abs(v) + scale for v in a]), rel=1e-9
    )
    assert bootstrap_difference(a, b, seed=2, resamples=400).ci_low < welch.ci_high


def test_a_ratio_with_a_little_real_noise_still_has_an_error_at_any_scale() -> None:
    for scale in (1e-9, 1.0, 1e9):
        rng = random.Random(5)
        denominators = [scale * (1 + rng.random()) for _ in range(200)]
        numerators = [0.8 * d + scale * rng.gauss(0, 1e-3) for d in denominators]

        assert ratio_estimate(numerators, denominators).std_error > 0


# --- Counts must be whole numbers --------------------------------------------------------


def test_a_fractional_count_is_refused_by_the_proportion_test_and_the_sample_ratio_test() -> None:
    with pytest.raises(StatsError, match="whole numbers"):
        two_proportion_difference(1.5, 10, 2, 10)
    with pytest.raises(StatsError, match="whole numbers"):
        two_proportion_difference(1, 10.5, 2, 10)
    with pytest.raises(StatsError, match="whole numbers"):
        srm_test([10.5, 12], [0.5, 0.5])


@pytest.mark.parametrize("bad", [math.nan, math.inf, np.bool_(True), True, "7"])
def test_counts_that_are_not_numbers_or_are_booleans_are_refused(bad: object) -> None:
    with pytest.raises(StatsError):
        srm_test([10, bad], [0.5, 0.5])
    with pytest.raises(StatsError):
        two_proportion_difference(bad, 10, 2, 10)


def test_a_tiny_real_spread_on_a_large_offset_is_still_a_spread() -> None:
    small = [k * 1e-9 for k in range(1, 11)]
    other = [k * 1e-9 for k in range(2, 12)]

    shifted = welch_difference([1.0 + v for v in small], [1.0 + v for v in other])
    plain = welch_difference(small, other)

    assert shifted.t_statistic == pytest.approx(plain.t_statistic, rel=1e-4)  # 1e-9 is 1e6 ulps


def test_one_constant_group_against_a_varying_one_gets_a_bootstrap_interval() -> None:
    result = bootstrap_difference([5.0] * 10, [1.0, 2.0, 3.5], seed=1, resamples=400)

    assert result.ci_low < result.ci_high


# --- What the reviewers found unpinned: intervals, defaults and echoed fields -----------------


def test_the_interval_of_a_difference_of_ratios_is_the_difference_plus_or_minus_z_errors() -> None:
    y1, x1 = _units(3, 400, 0.9)
    y0, x0 = _units(4, 400, 0.8)

    for alpha in (0.05, 0.10, 0.01):
        result = ratio_difference(y1, x1, y0, x0, alpha=alpha)
        margin = stats.norm.ppf(1 - alpha / 2) * result.std_error

        assert result.ci_low == pytest.approx(result.difference - margin, rel=1e-12)
        assert result.ci_high == pytest.approx(result.difference + margin, rel=1e-12)
        assert result.confidence == pytest.approx(1 - alpha)


def test_the_default_confidence_of_every_interval_is_95_percent() -> None:
    a, b = _lognormal(1, 60, 1.0), _lognormal(2, 60, 1.0)
    y1, x1 = _units(3, 80, 0.9)
    y0, x0 = _units(4, 80, 0.8)

    assert welch_difference(a, b).confidence == 0.95
    assert two_proportion_difference(30, 200, 20, 200).confidence == 0.95
    assert bootstrap_difference(a, b, seed=1).confidence == 0.95
    assert ratio_difference(y1, x1, y0, x0).confidence == 0.95
    assert bonferroni([0.01]).alpha == 0.05 and benjamini_hochberg([0.01]).alpha == 0.05
    assert srm_test([10, 10], [0.5, 0.5]).flagged is False  # the default threshold is 0.001
    assert srm_test([50, 150], [0.5, 0.5]).flagged is True


def test_the_bootstrap_defaults_to_ten_thousand_resamples() -> None:
    result = bootstrap_difference([1.0, 2.0, 4.0], [2.0, 3.0, 3.5], seed=1)

    assert result.resamples == 10_000


@pytest.mark.parametrize(("resamples", "accepted"), [(199, False), (200, True)])
def test_the_bootstrap_needs_five_resamples_in_each_tail_exactly(
    resamples: int, accepted: bool
) -> None:
    def call() -> object:
        return bootstrap_difference([1.0, 2.0, 4.0], [2.0, 3.0, 3.5], seed=1, resamples=resamples)

    if accepted:
        assert call().resamples == resamples
    else:
        with pytest.raises(StatsError, match="fewer than 5 resamples"):
            call()


def test_the_delta_method_error_for_varying_denominators_is_exact_on_a_hand_worked_case() -> None:
    # y = 1, 2, 4, 5 and x = 1, 2, 3, 4: means 3 and 2.5, variances 10/3 and 5/3, covariance 7/3,
    # ratio 1.2, so Var = (10/3 - 2 * 1.2 * 7/3 + 1.44 * 5/3) / (4 * 2.5^2) = 2/375
    estimate = ratio_estimate([1.0, 2.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0])

    assert estimate.ratio == pytest.approx(1.2, rel=1e-12)
    assert estimate.std_error == pytest.approx(math.sqrt(2 / 375), rel=1e-12)


# --- Any scale, and a correction that assumes nothing about dependence ----------------------


@pytest.mark.parametrize("size", [1e-200, 1e-160, 1e-154, 1e200])
def test_standard_errors_outside_floating_point_range_give_a_clear_error_not_a_crash(
    size: float,
) -> None:
    with pytest.raises(StatsError, match="too small or too large"):
        cohort_heterogeneity([1.0, 2.0, 3.0], [size, size, size])
    with pytest.raises(StatsError, match="too small or too large"):
        cohort_heterogeneity([1.0, 2.0], [1.0, size])


def test_a_hand_worked_benjamini_yekutieli() -> None:
    raw = [0.01, 0.04, 0.03, 0.005]
    harmonic = 1 + 1 / 2 + 1 / 3 + 1 / 4

    result = benjamini_yekutieli(raw)

    assert result.method == "benjamini_yekutieli" and result.alpha == 0.05
    assert result.adjusted == pytest.approx(tuple(a * harmonic for a in (0.02, 0.04, 0.04, 0.02)))
    assert result.rejected == (True, False, False, True)
    assert result.p_values == tuple(raw)


@pytest.mark.parametrize("seed", range(12))
def test_benjamini_yekutieli_agrees_with_statsmodels(seed: int) -> None:
    rng = random.Random(500 + seed)
    raw = [
        rng.choice([0.0, 1.0, rng.random() ** 3, rng.random()]) for _ in range(rng.randint(1, 15))
    ]
    raw += raw[:2]
    alpha = rng.choice([0.01, 0.05, 0.1])

    ours = benjamini_yekutieli(raw, alpha=alpha)
    reject, adjusted, _, _ = multipletests(raw, alpha=alpha, method="fdr_by")

    assert ours.adjusted == pytest.approx(adjusted, rel=1e-12, abs=0)
    assert list(ours.rejected) == list(reject)


@pytest.mark.parametrize(
    ("p_values", "alpha", "fragment"),
    [([], 0.05, "at least one"), ([0.5, 1.1], 0.05, "between 0 and 1"), ([0.5], 0.0, "alpha")],
)
def test_benjamini_yekutieli_refuses_what_the_others_refuse(
    p_values: list, alpha: float, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        benjamini_yekutieli(p_values, alpha=alpha)


# --- Do groups share one rate? -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("successes", "totals", "fragment"),
    [
        ([5], [10], "at least two groups"),
        ([5, 5], [10], "at least two groups"),
        ([0, 0], [10, 10], "same outcome"),
        ([10, 10], [10, 10], "same outcome"),
        ([1, 1], [10, 0], "not possible"),
        ([1, 11], [10, 10], "not possible"),
        ([-1, 1], [10, 10], "not possible"),
        ([1.5, 1], [10, 10], "whole numbers"),
        ([1, 1], [10.5, 10], "whole numbers"),
    ],
)
def test_a_homogeneity_test_refuses_what_it_cannot_answer(
    successes: list, totals: list, fragment: str
) -> None:
    with pytest.raises(StatsError, match=fragment):
        homogeneity_test(successes, totals)


# --- Edges found by the independent review of 4b-1 -----------------------------------------------


def _exact_homogeneity_chi_square(successes: list[int], totals: list[int]):
    """Pearson's statistic in exact rational arithmetic, rounded once."""
    from fractions import Fraction

    pooled = Fraction(sum(successes), sum(totals))
    total = sum(
        (Fraction(s) - n * pooled) ** 2 / (n * pooled * (1 - pooled))
        for s, n in zip(successes, totals, strict=True)
    )
    return float(total)


@pytest.mark.parametrize(
    ("treatment", "control"),
    [
        ([1e160, 1e160, 3.0], [1.0, 2.0, 3.0]),
        ([3e154, -3e154, 1.0], [1.0, 2.0, 3.0]),
        ([1.7e308, -1.7e308, 1.7e308], [1.7e308, -1.7e308, 5.0]),
        ([1.5e308, -1.5e308, 1.5e308], [1.0, 2.0, 3.0]),
    ],
)
def test_values_too_large_to_square_are_a_stats_error_not_an_overflow(
    treatment: list[float], control: list[float]
) -> None:
    with pytest.raises(StatsError, match="too large"):
        welch_difference(treatment, control)


def test_an_integer_beyond_any_float_is_not_a_finite_number() -> None:
    with pytest.raises(StatsError, match="finite"):
        welch_difference([10**400, 1, 2], [1, 2, 3])


