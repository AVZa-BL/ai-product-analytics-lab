"""Power calculations: agreement with statsmodels, textbook values, and the planning rules."""

import copy
import dataclasses
import itertools
import math

import pytest
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import samplesize_proportions_2indep_onetail

from referee.power import (
    PowerError,
    control_n_means,
    control_n_proportions,
    plan_power,
)
from referee.spec import ExperimentSpec

# --- The formulas against statsmodels (design section 17.1 explains the references) -----


def test_proportion_sizes_match_statsmodels_exactly() -> None:
    """Every case must agree to the unit, for both directions, both sidedness and unequal sizes.

    Convention pinned here: in samplesize_proportions_2indep_onetail the returned size is
    the FIRST group, which is prop2 + diff (the treatment), and `ratio` is the second group's
    size over the first's. Referee's control is statsmodels' second group, so its ratio is
    the inverse of ours and the control size is `ratio_sm * nobs1`. A two-sided test is run
    as a one-sided test at alpha / 2, because statsmodels' two-sided power also counts the
    opposite tail, which the classical formula ignores.
    """
    mismatches = []
    cases = 0
    for baseline, mde, alpha, power, ratio, sided, direction in itertools.product(
        [0.005, 0.032, 0.1, 0.3, 0.6],
        [0.02, 0.05, 0.1, 0.2],
        [0.01, 0.05, 0.1],
        [0.8, 0.9],
        [1.0, 0.5, 2.0, 3.0],
        ["two_sided", "one_sided"],
        ["increase", "decrease"],
    ):
        cases += 1
        sign = 1 if direction == "increase" else -1
        treated = baseline * (1 + sign * mde)
        mine = control_n_proportions(
            baseline=baseline,
            mde_relative=mde,
            direction=direction,
            alpha=alpha,
            power=power,
            ratio=ratio,
            sided=sided,
        )
        first_group = float(
            samplesize_proportions_2indep_onetail(
                diff=treated - baseline,
                prop2=baseline,
                power=power,
                ratio=1 / ratio,
                alpha=alpha / 2 if sided == "two_sided" else alpha,
                value=0,
                alternative="larger" if direction == "increase" else "smaller",
            )
        )
        if math.ceil(mine) != math.ceil(first_group / ratio):
            mismatches.append((baseline, mde, alpha, power, ratio, sided, direction))

    assert cases == 1920
    assert not mismatches, f"{len(mismatches)} of {cases} disagree, first: {mismatches[0]}"


def test_mean_sizes_match_statsmodels_exactly() -> None:
    """A z-test with known sigma is NormalIndPower on Cohen's d, one-sided at alpha / 2."""
    mismatches = []
    cases = 0
    for cv, mde, alpha, power, ratio, sided in itertools.product(
        [0.5, 1, 2, 5],
        [0.02, 0.05, 0.1, 0.2],
        [0.01, 0.05, 0.1],
        [0.8, 0.9],
        [1.0, 0.5, 2.0, 3.0],
        ["two_sided", "one_sided"],
    ):
        cases += 1
        mine = control_n_means(
            mean=10.0,
            std=10.0 * cv,
            mde_relative=mde,
            alpha=alpha,
            power=power,
            ratio=ratio,
            sided=sided,
        )
        reference = NormalIndPower().solve_power(
            effect_size=mde / cv,
            alpha=alpha / 2 if sided == "two_sided" else alpha,
            power=power,
            ratio=ratio,
            alternative="larger",
        )
        if math.ceil(mine) != math.ceil(reference):
            mismatches.append((cv, mde, alpha, power, ratio, sided))

    assert cases == 768
    assert not mismatches, f"{len(mismatches)} of {cases} disagree, first: {mismatches[0]}"


def test_textbook_sample_sizes() -> None:
    """10% against 12% at alpha .05 and power .8 needs 3,841 per arm; Cohen's d = 0.2 needs 393."""
    proportions = control_n_proportions(
        baseline=0.10, mde_relative=0.2, direction="increase", alpha=0.05, power=0.8
    )
    means = control_n_means(mean=5, std=1, mde_relative=0.04, alpha=0.05, power=0.8)

    assert math.ceil(proportions) == 3841
    assert math.ceil(means) == 393


# --- Properties of the formulas ---------------------------------------------------------

PROPORTION = {"baseline": 0.05, "direction": "increase", "alpha": 0.05, "power": 0.8}


def _n(**overrides: object) -> float:
    return control_n_proportions(**{"mde_relative": 0.1, **PROPORTION, **overrides})


def test_size_falls_as_the_effect_grows_and_rises_with_stricter_settings() -> None:
    assert _n(mde_relative=0.2) < _n(mde_relative=0.1) < _n(mde_relative=0.05)
    assert _n(power=0.9) > _n(power=0.8)
    assert _n(alpha=0.01) > _n(alpha=0.05)


def test_a_one_sided_test_needs_fewer_units_than_a_two_sided_one() -> None:
    assert _n(sided="one_sided") < _n(sided="two_sided")


def test_for_means_an_equal_split_is_the_cheapest_allocation() -> None:
    def total(ratio: float) -> float:
        n = control_n_means(mean=10, std=5, mde_relative=0.1, alpha=0.05, power=0.8, ratio=ratio)
        return n * (1 + ratio)

    assert total(1.0) < total(0.5) and total(1.0) < total(2.0) and total(1.0) < total(4.0)
    assert total(0.5) == pytest.approx(total(2.0))  # swapping the arms changes nothing


@pytest.mark.parametrize(
    "call",
    [
        lambda: _n(alpha=1.0),
        lambda: _n(alpha=0),
        lambda: _n(power=0),
        lambda: _n(power=1),
        lambda: _n(mde_relative=0),
        lambda: _n(mde_relative=math.nan),
        lambda: _n(ratio=0),
        lambda: _n(baseline=0),
        lambda: _n(baseline=1),
        lambda: _n(baseline=0.9, mde_relative=0.2),  # 1.08 is not a rate
        lambda: _n(direction="decrease", mde_relative=1.5),  # -0.5 is not a rate
        lambda: control_n_means(mean=10, std=0, mde_relative=0.1, alpha=0.05, power=0.8),
        lambda: control_n_means(mean=0, std=1, mde_relative=0.1, alpha=0.05, power=0.8),
        lambda: control_n_means(mean=10, std=1, mde_relative=-0.1, alpha=0.05, power=0.8),
    ],
    ids=[
        "alpha_one",
        "alpha_zero",
        "power_zero",
        "power_one",
        "mde_zero",
        "mde_nan",
        "ratio_zero",
        "baseline_zero",
        "baseline_one",
        "rate_above_one",
        "rate_below_zero",
        "std_zero",
        "mean_zero",
        "negative_mde",
    ],
)
def test_impossible_inputs_raise_power_error(call) -> None:
    with pytest.raises(PowerError):
        call()


# --- plan_power ---------------------------------------------------------------------------


def _plan(raw_spec: dict, **changes: object):
    """plan_power after applying changes keyed like `design__alpha` or `arms__0__allocation`."""
    for path, value in changes.items():
        *parents, leaf = path.split("__")
        node = raw_spec
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(leaf) if leaf.isdigit() else leaf] = value
    return plan_power(ExperimentSpec.from_dict(raw_spec))


def test_the_design_example_is_underpowered(raw_spec: dict) -> None:
    """Section 6's example: 3.2% baseline, a 5% relative lift, 4,200 units a day for 14 days."""
    plan = _plan(raw_spec)

    assert plan.required_per_arm == (("control", 194_530), ("variant_b", 194_530))
    assert plan.required_total == 389_060
    assert plan.achievable_total == 58_800
    assert plan.required_days == 93
    assert plan.required_days_whole_weeks == 98
    assert not plan.is_powered
    assert plan.alpha_per_comparison == 0.05
    assert plan.comparisons == 1
    assert plan.achievable_mde_relative == pytest.approx(0.131042, abs=1e-5)


def test_the_achievable_effect_is_exactly_what_the_duration_can_pay_for(raw_spec: dict) -> None:
    achievable = _plan(raw_spec).achievable_mde_relative
    assert achievable is not None

    at_limit = _plan(raw_spec, design__mde_relative=achievable)
    just_below = _plan(raw_spec, design__mde_relative=achievable * 0.999)

    assert at_limit.required_total <= at_limit.achievable_total
    assert just_below.required_total > just_below.achievable_total


def test_for_means_the_achievable_effect_follows_the_inverse_square_law(raw_spec: dict) -> None:
    """n scales as 1 / effect^2 for means, an independent check on the bisection."""
    plan = _plan(
        raw_spec,
        primary_metric__kind="continuous",
        primary_metric__baseline=12.5,
        primary_metric__baseline_std=30.0,
    )
    expected = 0.05 * math.sqrt(plan.required_total / plan.achievable_total)

    assert plan.achievable_mde_relative == pytest.approx(expected, rel=1e-3)


def test_a_powered_design_says_so(raw_spec: dict) -> None:
    plan = _plan(raw_spec, population__daily_eligible_units=20_000, design__mde_relative=0.10)

    assert plan.is_powered
    assert plan.required_total == 99_554
    assert plan.required_days == 5
    assert plan.achievable_total == 280_000
    assert plan.achievable_mde_relative < 0.10


@pytest.mark.parametrize(
    ("daily", "days", "weeks"),
    [(27_790, 14, 14), (27_789, 15, 21), (4_200, 93, 98), (500_000, 1, 7)],
    ids=["exact_multiple", "one_unit_short", "design_example", "under_a_week"],
)
def test_required_days_round_up_to_whole_weeks(
    raw_spec: dict, daily: int, days: int, weeks: int
) -> None:
    """389,060 units over 27,790 a day is exactly 14 days; one unit fewer a day is 15."""
    plan = _plan(raw_spec, population__daily_eligible_units=daily)

    assert (plan.required_days, plan.required_days_whole_weeks) == (days, weeks)


def _three_arms(raw_spec: dict) -> dict:
    raw_spec["arms"] = [
        {"name": "control", "allocation": 1 / 3, "is_control": True},
        {"name": "b", "allocation": 1 / 3},
        {"name": "c", "allocation": 1 / 3},
    ]
    return raw_spec


def test_exactly_enough_units_counts_as_powered(raw_spec: dict) -> None:
    """389,060 needed; 27,790 a day for 14 days delivers exactly that, one unit less does not."""
    exact = _plan(copy.deepcopy(raw_spec), population__daily_eligible_units=27_790)
    short = _plan(raw_spec, population__daily_eligible_units=27_789)

    assert exact.required_total == exact.achievable_total == 389_060
    assert exact.is_powered
    assert short.required_total > short.achievable_total
    assert not short.is_powered


def test_with_more_arms_alpha_is_split_across_the_comparisons(raw_spec: dict) -> None:
    two_arms = copy.deepcopy(raw_spec)
    three_arms = _plan(_three_arms(raw_spec))
    two_arms_at_half_alpha = _plan(two_arms, design__alpha=0.025)

    assert three_arms.comparisons == 2
    assert three_arms.alpha_per_comparison == 0.025
    assert three_arms.required_per_arm[0][1] == two_arms_at_half_alpha.required_per_arm[0][1]
    assert [name for name, _ in three_arms.required_per_arm] == ["control", "b", "c"]


def test_the_most_demanding_variant_sets_the_total(raw_spec: dict) -> None:
    """A 10% variant is far harder to power against a 50% control than a 40% one.

    With equal arms every comparison needs the same total, so this needs unequal shares to
    tell "the largest requirement" from "any requirement".
    """
    raw_spec["arms"] = [
        {"name": "control", "allocation": 0.5, "is_control": True},
        {"name": "b", "allocation": 0.4},
        {"name": "c", "allocation": 0.1},
    ]
    plan = plan_power(ExperimentSpec.from_dict(raw_spec))

    def control_n(variant_share: float) -> float:
        return control_n_proportions(
            baseline=0.032,
            mde_relative=0.05,
            direction="increase",
            alpha=0.05 / 2,  # Bonferroni across two comparisons
            power=0.8,
            ratio=variant_share / 0.5,
        )

    total = max(control_n(0.4), control_n(0.1)) / 0.5
    assert control_n(0.1) > control_n(0.4)
    assert plan.required_per_arm == (
        ("control", math.ceil(0.5 * total)),
        ("b", math.ceil(0.4 * total)),
        ("c", math.ceil(0.1 * total)),
    )
    assert (
        plan.required_total
        > plan_power(ExperimentSpec.from_dict(_three_arms(copy.deepcopy(raw_spec)))).required_total
    )


def test_no_alpha_adjustment_keeps_the_full_alpha(raw_spec: dict) -> None:
    two_arms = copy.deepcopy(raw_spec)
    spec = ExperimentSpec.from_dict(_three_arms(raw_spec))

    unadjusted = plan_power(spec, alpha_adjustment="none")

    assert unadjusted.alpha_per_comparison == 0.05
    assert unadjusted.required_per_arm[0][1] == _plan(two_arms).required_per_arm[0][1]
    assert plan_power(spec).required_total > unadjusted.required_total


def test_an_unequal_allocation_costs_extra_units_over_an_equal_split(raw_spec: dict) -> None:
    equal = _plan(copy.deepcopy(raw_spec), design__mde_relative=0.10)
    skewed = _plan(
        raw_spec,
        design__mde_relative=0.10,
        arms__0__allocation=0.7,
        arms__1__allocation=0.3,
    )

    assert equal.extra_units_vs_equal_split == 0
    assert skewed.equal_split_total == equal.required_total
    assert skewed.extra_units_vs_equal_split == pytest.approx(0.182, abs=0.001)
    control, variant = (units for _, units in skewed.required_per_arm)
    assert control / variant == pytest.approx(7 / 3, rel=1e-3)
    assert skewed.required_total == control + variant


@pytest.mark.parametrize("kind", ["continuous", "ratio"])
def test_continuous_and_ratio_metrics_are_sized_as_means(raw_spec: dict, kind: str) -> None:
    plan = _plan(
        raw_spec,
        primary_metric__kind=kind,
        primary_metric__baseline=12.5,
        primary_metric__baseline_std=30.0,
    )
    expected = control_n_means(mean=12.5, std=30.0, mde_relative=0.05, alpha=0.05, power=0.8)

    assert plan.required_per_arm[0][1] == math.ceil(expected)


def test_the_hypothesis_direction_selects_the_treatment_rate(raw_spec: dict) -> None:
    up = _plan(copy.deepcopy(raw_spec), hypothesis__direction="increase")
    down = _plan(copy.deepcopy(raw_spec), hypothesis__direction="decrease")
    either = _plan(raw_spec, hypothesis__direction="two_sided")

    assert up.required_total != down.required_total
    assert either.required_total == max(up.required_total, down.required_total)


def test_a_two_sided_hypothesis_survives_when_only_one_direction_is_expressible(
    raw_spec: dict,
) -> None:
    """A rate of 0.9 cannot rise by 20%, but it can fall by 20%."""
    raw_spec["primary_metric"]["baseline"] = 0.9
    raw_spec["design"]["mde_relative"] = 0.2
    raw_spec["hypothesis"]["direction"] = "two_sided"
    two_sided = plan_power(ExperimentSpec.from_dict(copy.deepcopy(raw_spec)))
    raw_spec["hypothesis"]["direction"] = "decrease"
    decrease = plan_power(ExperimentSpec.from_dict(raw_spec))

    assert two_sided.required_total == decrease.required_total


def test_an_effect_that_cannot_exist_raises_power_error(raw_spec: dict) -> None:
    raw_spec["primary_metric"]["baseline"] = 0.9
    raw_spec["design"]["mde_relative"] = 0.2

    with pytest.raises(PowerError, match="0 to 1"):
        plan_power(ExperimentSpec.from_dict(raw_spec))


def test_an_unreachable_design_has_no_achievable_effect(raw_spec: dict) -> None:
    """One unit a day for one day cannot detect anything, however large the effect."""
    plan = _plan(
        raw_spec,
        population__daily_eligible_units=1,
        design__planned_duration_days=1,
        design__min_duration_days=1,
    )

    assert plan.achievable_mde_relative is None
    assert not plan.is_powered


def test_a_plan_is_immutable_hashable_and_repeatable(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)

    first, second = plan_power(spec), plan_power(spec)

    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.required_total = 1
