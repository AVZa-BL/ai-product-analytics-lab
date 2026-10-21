"""Power calculations: agreement with statsmodels, textbook values, and the planning rules."""

import copy
import dataclasses
import itertools
import math

import pytest
from statsmodels.stats.power import NormalIndPower

from referee.power import (
    PowerError,
    control_n_means,
    control_n_proportions,
    plan_power,
)
from referee.spec import ExperimentSpec

# --- The formulas against statsmodels (design section 17.1 explains the references) -----


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


@pytest.mark.parametrize(
    "call",
    [
        lambda: _n(alpha=1.0),
        lambda: _n(power=0),
        lambda: _n(mde_relative=0),
        lambda: _n(ratio=0),
        lambda: _n(direction="decrease", mde_relative=1.5),  # -0.5 is not a rate
        lambda: control_n_means(mean=10, std=0, mde_relative=0.1, alpha=0.05, power=0.8),
        lambda: control_n_means(mean=0, std=1, mde_relative=0.1, alpha=0.05, power=0.8),
    ],
    ids=[
        "alpha_one",
        "power_zero",
        "mde_zero",
        "ratio_zero",
        "rate_below_zero",
        "std_zero",
        "mean_zero",
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


def test_no_alpha_adjustment_keeps_the_full_alpha(raw_spec: dict) -> None:
    two_arms = copy.deepcopy(raw_spec)
    spec = ExperimentSpec.from_dict(_three_arms(raw_spec))

    unadjusted = plan_power(spec, alpha_adjustment="none")

    assert unadjusted.alpha_per_comparison == 0.05
    assert unadjusted.required_per_arm[0][1] == _plan(two_arms).required_per_arm[0][1]
    assert plan_power(spec).required_total > unadjusted.required_total


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
