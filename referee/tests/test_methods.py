"""The statistics: each function against an independent implementation or a known answer."""

import itertools
import math
import random

import pytest
from scipy import stats
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest
from statsmodels.stats.weightstats import CompareMeans, DescrStatsW

from referee.methods import (
    SRM_ALPHA,
    StatsError,
    srm_test,
    two_proportion_difference,
    welch_difference,
)

# --- Sample ratio mismatch ---------------------------------------------------------------


def test_the_planted_mismatch_gives_the_figure_the_experiment_document_publishes() -> None:
    # Arms 997 / 1,046 / 781 of 2,824 assigned players: "p = 6.7e-10" in the lab's readout.
    result = srm_test([997, 1046, 781], [1 / 3, 1 / 3, 1 / 3])

    assert result.chi_square == pytest.approx(42.23866855524079, rel=1e-12)
    assert result.degrees_of_freedom == 2
    assert result.p_value == pytest.approx(6.729606364817086e-10, rel=1e-9)
    assert f"{result.p_value:.1e}" == "6.7e-10" and result.flagged


def test_with_three_arms_the_p_value_is_the_closed_form_the_lab_sql_uses() -> None:
    for counts in ([997, 1046, 781], [340, 330, 331], [100, 200, 300]):
        result = srm_test(counts, [1 / 3] * 3)

        assert result.p_value == pytest.approx(math.exp(-result.chi_square / 2), rel=1e-12)


@pytest.mark.parametrize("seed", range(12))
def test_it_agrees_with_scipy_for_two_to_five_arms_and_unequal_allocations(seed: int) -> None:
    rng = random.Random(seed)
    arms = rng.randint(2, 5)
    raw = [rng.uniform(0.5, 2.0) for _ in range(arms)]
    allocation = [value / sum(raw) for value in raw]
    counts = [rng.randint(50, 900) for _ in range(arms)]
    total = sum(counts)

    ours = srm_test(counts, allocation)
    reference = stats.chisquare(counts, f_exp=[total * share for share in allocation])

    assert ours.chi_square == pytest.approx(reference.statistic, rel=1e-12)
    assert ours.p_value == pytest.approx(reference.pvalue, rel=1e-9)
    assert ours.degrees_of_freedom == arms - 1
    assert ours.expected == pytest.approx([total * share for share in allocation])


def test_counts_that_match_the_allocation_exactly_give_chi_square_zero_and_p_one() -> None:
    result = srm_test([500, 300, 200], [0.5, 0.3, 0.2])

    assert result.chi_square == 0.0 and result.p_value == 1.0 and not result.flagged


def test_the_flag_is_strictly_below_the_threshold() -> None:
    p = srm_test([60, 40], [0.5, 0.5]).p_value

    assert srm_test([60, 40], [0.5, 0.5], alpha=p).flagged is False
    assert srm_test([60, 40], [0.5, 0.5], alpha=p * 1.0001).flagged is True
    assert SRM_ALPHA == 0.001


def test_an_arm_with_no_assignments_counts_as_zero_and_is_the_strongest_mismatch() -> None:
    result = srm_test([100, 100, 0], [1 / 3, 1 / 3, 1 / 3])

    assert result.flagged and result.chi_square == pytest.approx(100.0)
    assert result.chi_square == pytest.approx(stats.chisquare([100, 100, 0]).statistic)


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


def test_a_hand_worked_difference_in_means() -> None:
    # treatment [2, 4, 6]: mean 4, variance 4; control [1, 3]: mean 2, variance 2
    result = welch_difference([2, 4, 6], [1, 3])

    assert result.difference == 2.0
    assert result.std_error == pytest.approx(math.sqrt(4 / 3 + 2 / 2))
    assert result.t_statistic == pytest.approx(2.0 / math.sqrt(7 / 3))
    assert result.degrees_of_freedom == pytest.approx((7 / 3) ** 2 / ((4 / 3) ** 2 / 2 + 1 / 1))
    assert (result.n_treatment, result.n_control) == (3, 2)
    assert (result.mean_treatment, result.mean_control) == (4.0, 2.0)


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
    assert ours.p_value == pytest.approx(scipy_result.pvalue, rel=1e-8)
    assert ours.degrees_of_freedom == pytest.approx(scipy_result.df, rel=1e-10)
    assert (ours.ci_low, ours.ci_high) == pytest.approx((low, high), rel=1e-9)
    assert ours.confidence == 0.95


def test_a_heavy_tailed_sample_still_matches_scipy() -> None:
    rng = random.Random(3)
    treatment = [rng.lognormvariate(0.0, 1.7) for _ in range(300)]
    control = [rng.lognormvariate(0.0, 1.7) for _ in range(500)]

    ours = welch_difference(treatment, control)

    assert ours.p_value == pytest.approx(
        stats.ttest_ind(treatment, control, equal_var=False).pvalue
    )


def test_the_interval_narrows_as_alpha_grows_and_contains_the_difference() -> None:
    rng = random.Random(5)
    a = [rng.gauss(1.0, 2.0) for _ in range(200)]
    b = [rng.gauss(0.0, 2.0) for _ in range(200)]

    wide, narrow = welch_difference(a, b, alpha=0.01), welch_difference(a, b, alpha=0.20)

    assert wide.ci_low < narrow.ci_low < narrow.difference < narrow.ci_high < wide.ci_high


def test_swapping_the_groups_negates_the_difference_and_keeps_the_p_value() -> None:
    a, b = [1.0, 2.0, 4.0, 9.0], [2.0, 2.5, 3.0]

    forward, backward = welch_difference(a, b), welch_difference(b, a)

    assert backward.difference == -forward.difference
    assert backward.t_statistic == -forward.t_statistic
    assert backward.p_value == forward.p_value


def test_the_order_of_the_values_does_not_change_a_single_digit() -> None:
    rng = random.Random(11)
    a = [rng.lognormvariate(0.0, 1.7) for _ in range(500)]
    b = [rng.lognormvariate(0.1, 1.7) for _ in range(400)]
    shuffled_a, shuffled_b = a[:], b[:]
    rng.shuffle(shuffled_a)
    rng.shuffle(shuffled_b)

    assert welch_difference(a, b) == welch_difference(shuffled_a, shuffled_b)


def test_values_whose_naive_sum_depends_on_order_still_give_one_exact_answer() -> None:
    # 1e16 + 1.0 loses the 1.0 when added first, so a plain sum changes with the order.
    values = [1e16, 1.0, -1e16, 2.0, 3.0, 0.5]
    control = [0.0, 1.0, 2.0, 5.0]

    answers = {welch_difference(list(order), control) for order in itertools.permutations(values)}

    assert len(answers) == 1


def test_one_group_may_be_constant_when_the_other_varies() -> None:
    result = welch_difference([5.0, 5.0, 5.0, 5.0], [1.0, 2.0, 3.0])

    assert result.std_error == pytest.approx(math.sqrt(1.0 / 3))


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


def test_a_hand_worked_difference_in_proportions() -> None:
    # 30 of 200 against 20 of 200: pooled rate 0.125
    result = two_proportion_difference(30, 200, 20, 200)

    assert result.rate_treatment == 0.15 and result.rate_control == 0.10
    assert result.difference == pytest.approx(0.05)
    assert result.z_statistic == pytest.approx(0.05 / math.sqrt(0.125 * 0.875 * (2 / 200)))
    assert result.std_error == pytest.approx(math.sqrt(0.15 * 0.85 / 200 + 0.10 * 0.90 / 200))
    assert result.p_value == pytest.approx(0.1304, abs=5e-4)


@pytest.mark.parametrize("seed", range(10))
def test_it_agrees_with_statsmodels_on_random_counts(seed: int) -> None:
    rng = random.Random(seed)
    n1, n2 = rng.randint(200, 5000), rng.randint(200, 5000)
    x1, x2 = rng.randint(5, n1 // 2), rng.randint(5, n2 // 2)

    ours = two_proportion_difference(x1, n1, x2, n2, alpha=0.05)
    z, p = proportions_ztest([x1, x2], [n1, n2])
    low, high = confint_proportions_2indep(x1, n1, x2, n2, method="wald", alpha=0.05)

    assert ours.z_statistic == pytest.approx(z, rel=1e-10)
    assert ours.p_value == pytest.approx(p, rel=1e-8)
    assert (ours.ci_low, ours.ci_high) == pytest.approx((low, high), rel=1e-9)


def test_swapping_the_groups_negates_the_difference_and_keeps_the_p_value_for_proportions() -> None:
    forward = two_proportion_difference(30, 200, 20, 250)
    backward = two_proportion_difference(20, 250, 30, 200)

    assert backward.difference == -forward.difference
    assert backward.z_statistic == -forward.z_statistic
    assert backward.p_value == pytest.approx(forward.p_value, rel=1e-12)
    assert (backward.ci_low, backward.ci_high) == pytest.approx(
        (-forward.ci_high, -forward.ci_low), rel=1e-12
    )


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
