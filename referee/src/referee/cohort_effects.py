"""The statistics of the cohort test: an arm's effect in each cohort, and whether it varies.

For one arm and one metric over the cohorts a `CohortPlan` allows, the effect is estimated on
two scales in every cohort: the absolute difference of means (Welch) and the log of the ratio
of means (delta method). Each standard error is multiplied by the small-sample correction of
design section 21.1, and Cochran's Q and the weighted slope over the cohorts' positions are
computed on each scale. This module computes; it does not decide. The levels at which a scale
counts as heterogeneous, and what a finding says, belong to RES-007.

A cohort that cannot give an estimate on a scale is dropped from that scale with a reason and
listed, never silently: no variation, a mean that is not above 0 (log scale), or numbers the
statistics cannot handle. A scale left with fewer than 3 cohorts is not evaluated.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from scipy import stats

from referee.cohorts import MIN_COHORTS, CohortPlan
from referee.methods import (
    SMALL_EXPECTED_COUNT,
    CohortHeterogeneity,
    CohortShape,
    NonPositiveMeanError,
    NoVariationError,
    StatsError,
    cohort_detectable_shift,
    cohort_heterogeneity,
    homogeneity_test,
    log_mean_ratio,
    welch_correction,
    welch_difference,
)
from referee.results import ExportMetric, ResultsContext

TRIGGER_LEVEL = 0.025  # per statistic, before dividing by the number of non-control arms
POWER = 0.8  # the chance with which a quiet result could have seen the shifts it reports
MDE_MULTIPLE = 4  # a shift above this many registered minimum detectable effects is low information
MIN_EXPECTED_EVENTS = 5  # fewer events than this per arm and cohort is low information
BASELINE_LEVEL = 0.05  # a control baseline that changes across cohorts, at this p value
# The share of tests the trigger flagged when nothing changes over time, two arms, in the 96
# cells of design section 21.5 (mean and maximum); a test checks them against the saved study.
NULL_FLAG_RATE_MEAN = 0.0346
NULL_FLAG_RATE_MAX = 0.0508
SHAPES: tuple[CohortShape, CohortShape] = ("linear_fade", "step")
LowInformation = Literal[
    "shift_exceeds_control_mean",
    "shift_exceeds_4_times_registered_mde",
    "fewer_than_5_expected_events",
]
Scale = Literal["absolute", "log_ratio"]
DropReason = Literal["no_variation", "non_positive_mean", "not_estimable"]
SCALES: tuple[Scale, Scale] = ("absolute", "log_ratio")


@dataclass(frozen=True, kw_only=True)
class CohortEstimate:
    """One cohort's effect on one scale, before and after the small-sample correction."""

    block: int
    n_arm: int
    n_control: int
    mean_arm: float
    mean_control: float
    estimate: float
    std_error: float
    degrees_of_freedom: float
    corrected_std_error: float


@dataclass(frozen=True, kw_only=True)
class ScaleTest:
    """The cohorts of one scale and what Q and the slope make of them.

    `heterogeneity` is None when the scale is not evaluated, and then `reason` says why. A
    cohort left out of the scale is in `dropped` with its block and reason.
    """

    scale: Scale
    cohorts: tuple[CohortEstimate, ...]
    dropped: tuple[tuple[int, DropReason], ...]
    reason: DropReason | None
    error: str | None
    heterogeneity: CohortHeterogeneity | None


@dataclass(frozen=True, kw_only=True)
class CohortTest:
    """One arm's cohort test on one metric, on both scales."""

    arm: str
    control: str
    metric: str
    block_days: int
    absolute: ScaleTest
    log_ratio: ScaleTest

    @property
    def scales(self) -> tuple[ScaleTest, ScaleTest]:
        return self.absolute, self.log_ratio


@dataclass(frozen=True, kw_only=True)
class Trigger:
    """Whether the cohort test flags an arm, and on which scales.

    A scale shows heterogeneity when Cochran's Q or the slope has p below `level`; `None` means
    the scale was not evaluated. The arm is flagged only when both scales show it.
    """

    level: float
    absolute: bool | None
    log_ratio: bool | None

    @property
    def flagged(self) -> bool:
        return self.absolute is True and self.log_ratio is True


def shows_heterogeneity(scale: ScaleTest, level: float) -> bool | None:
    """Whether Q or the slope of `scale` has p below `level`; None if it is not evaluated."""
    found = scale.heterogeneity
    if found is None:
        return None
    return found.q_p_value < level or found.slope_p_value < level


def trigger(test: CohortTest, non_control_arms: int) -> Trigger:
    """The trigger of design section 21.5 for one arm's test.

    The level of each statistic is `TRIGGER_LEVEL` divided by the number of non-control arms
    (Bonferroni, as `plan_power` divides alpha), and the arm is flagged only when both scales
    show heterogeneity. The false-alarm rate and the power of this rule were measured by
    simulation (`tests/cohort_simulation.py`, section 21.5).
    """
    if non_control_arms < 1:
        raise ValueError(f"an experiment has at least one non-control arm, got {non_control_arms}")
    level = TRIGGER_LEVEL / non_control_arms
    return Trigger(
        level=level,
        absolute=shows_heterogeneity(test.absolute, level),
        log_ratio=shows_heterogeneity(test.log_ratio, level),
    )


def _estimate(
    scale: Scale, treatment: list[float], control: list[float], block: int
) -> CohortEstimate | DropReason:
    """One cohort's estimate on `scale`, or the reason it has none."""
    try:
        if scale == "absolute":
            welch = welch_difference(treatment, control)
            value, error, dof = welch.difference, welch.std_error, welch.degrees_of_freedom
            mean_arm, mean_control = welch.mean_treatment, welch.mean_control
        else:
            ratio = log_mean_ratio(treatment, control)
            value, error, dof = ratio.log_ratio, ratio.std_error, ratio.degrees_of_freedom
            mean_arm, mean_control = ratio.mean_treatment, ratio.mean_control
        corrected = error * welch_correction(dof)
    except NoVariationError:
        return "no_variation"
    except NonPositiveMeanError:
        return "non_positive_mean"
    except StatsError:
        return "not_estimable"
    return CohortEstimate(
        block=block,
        n_arm=len(treatment),
        n_control=len(control),
        mean_arm=mean_arm,
        mean_control=mean_control,
        estimate=value,
        std_error=error,
        degrees_of_freedom=dof,
        corrected_std_error=corrected,
    )


def _scale_test(
    scale: Scale, blocks: list[int], arm: dict[int, list[float]], control: dict[int, list[float]]
) -> ScaleTest:
    kept: list[CohortEstimate] = []
    dropped: list[tuple[int, DropReason]] = []
    for block in blocks:
        found = _estimate(scale, arm[block], control[block], block)
        if isinstance(found, CohortEstimate):
            kept.append(found)
        else:
            dropped.append((block, found))
    if len(kept) < MIN_COHORTS:
        counts = Counter(reason for _, reason in dropped)
        reason = min(counts, key=lambda code: (-counts[code], code)) if counts else "not_estimable"
        return ScaleTest(
            scale=scale,
            cohorts=tuple(kept),
            dropped=tuple(dropped),
            reason=reason,
            error=None,
            heterogeneity=None,
        )
    try:
        heterogeneity = cohort_heterogeneity(
            [c.estimate for c in kept],
            [c.corrected_std_error for c in kept],
            positions=[c.block for c in kept],
        )
    except StatsError as error:
        return ScaleTest(
            scale=scale,
            cohorts=tuple(kept),
            dropped=tuple(dropped),
            reason="not_estimable",
            error=str(error),
            heterogeneity=None,
        )
    return ScaleTest(
        scale=scale,
        cohorts=tuple(kept),
        dropped=tuple(dropped),
        reason=None,
        error=None,
        heterogeneity=heterogeneity,
    )


def cohort_test(context: ResultsContext, plan: CohortPlan, metric: ExportMetric) -> CohortTest:
    """The cohort test of `plan.arm` on `metric`, over the cohorts the plan allows.

    The values of a cohort are the metric over its analysed players, the arm's and control's
    separately. Raises `ValueError` when the plan is not evaluated: there is nothing to test.
    """
    if not plan.evaluated or plan.block_days is None:
        raise ValueError(f"the plan for {plan.arm!r} is not evaluated: {plan.reason}")
    values: dict[str, dict[int, list[float]]] = {
        plan.arm: defaultdict(list),
        plan.control: defaultdict(list),
    }
    wanted = set(plan.usable)
    for player in context.analysed:
        if player.arm not in values:
            continue
        block = context.block_of(player.first_exposed_at, plan.block_days)
        if block in wanted:
            values[player.arm][block].append(metric.value(player))
    blocks = sorted(plan.usable)
    scales = {
        scale: _scale_test(scale, blocks, values[plan.arm], values[plan.control])
        for scale in SCALES
    }
    return CohortTest(
        arm=plan.arm,
        control=plan.control,
        metric=metric.name,
        block_days=plan.block_days,
        absolute=scales["absolute"],
        log_ratio=scales["log_ratio"],
    )


# --- What a finding needs besides the trigger -------------------------------------------------


def detectable_shifts(scale: ScaleTest, level: float) -> dict[CohortShape, float] | None:
    """The smallest change of each shape that Q-or-slope would flag with 80% probability.

    Worked out from the standard errors the trigger used (the corrected ones) and the block
    numbers of the cohorts it used, in the units of `scale`: the metric's for the absolute scale
    and a log ratio for the relative one. None when the scale was not evaluated.
    """
    if scale.heterogeneity is None:
        return None
    errors = [c.corrected_std_error for c in scale.cohorts]
    blocks = [c.block for c in scale.cohorts]
    return {
        shape: cohort_detectable_shift(
            errors, positions=blocks, shape=shape, level=level, power=POWER
        )
        for shape in SHAPES
    }


def min_expected_events(scale: ScaleTest) -> float | None:
    """The fewest events (players times the cohort's rate) in any arm and cohort of the scale.

    Meant for a binary metric, where the mean is a rate. None when no cohort was used.
    """
    if not scale.cohorts:
        return None
    return min(min(c.n_arm * c.mean_arm, c.n_control * c.mean_control) for c in scale.cohorts)


def registered_mde(context: ResultsContext, metric: ExportMetric) -> float | None:
    """The minimum detectable effect the spec registered for `metric`, in its units.

    Only the primary metric has one: `design.mde_relative` times its baseline. None for a
    guardrail, which registers a tolerance and not a target effect.
    """
    primary = context.spec.primary_metric
    if metric.name != primary.name:
        return None
    return context.spec.design.mde_relative * primary.baseline


def low_information(
    *,
    shift: float,
    control_mean: float,
    registered_mde: float | None,
    expected_events: float | None,
) -> tuple[LowInformation, ...]:
    """Why a result tells little: the change it could have seen is large, or its counts are few.

    `shift` is the detectable linear fade on the absolute scale. A result is low information
    when that shift exceeds the control mean, when it exceeds 4 times the registered minimum
    detectable effect (if there is one), or when a binary metric has fewer than 5 expected
    events in some arm and cohort (`expected_events`, None for a metric that is not binary).
    """
    found: list[LowInformation] = []
    if shift > control_mean:
        found.append("shift_exceeds_control_mean")
    if registered_mde is not None and shift > MDE_MULTIPLE * registered_mde:
        found.append("shift_exceeds_4_times_registered_mde")
    if expected_events is not None and expected_events < MIN_EXPECTED_EVENTS:
        found.append("fewer_than_5_expected_events")
    return tuple(found)


@dataclass(frozen=True, kw_only=True)
class ControlCohort:
    """The control arm in one cohort: its players, mean and 95% interval."""

    block: int
    n: int
    mean: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True, kw_only=True)
class ControlBaseline:
    """The control arm's mean in each cohort the test used, and whether it moves.

    `homogeneity_p` tests that the control's mean is the same in every cohort (the chi-squared
    test of homogeneity for a binary metric, Cochran's Q of the means for another); None when
    that cannot be worked out. `moves` is true when it is below 0.05: a baseline that changes
    across cohorts can raise Q on a scale that is not invariant (design section 21.5).
    """

    cohorts: tuple[ControlCohort, ...]
    pooled_mean: float
    homogeneity_p: float | None

    @property
    def moves(self) -> bool:
        return self.homogeneity_p is not None and self.homogeneity_p < BASELINE_LEVEL


def control_baseline(
    context: ResultsContext, plan: CohortPlan, metric: ExportMetric
) -> ControlBaseline:
    """The control arm's mean by cohort over the blocks `plan` uses, and its homogeneity."""
    if not plan.evaluated or plan.block_days is None:
        raise ValueError(f"the plan for {plan.arm!r} is not evaluated: {plan.reason}")
    wanted = set(plan.usable)
    values: dict[int, list[float]] = defaultdict(list)
    for player in context.analysed:
        if player.arm != plan.control:
            continue
        block = context.block_of(player.first_exposed_at, plan.block_days)
        if block in wanted:
            values[block].append(metric.value(player))
    cohorts, errors = [], []
    for block in sorted(values):
        found = values[block]
        n = len(found)
        mean = math.fsum(found) / n
        variance = math.fsum((v - mean) ** 2 for v in found) / (n - 1)
        error = math.sqrt(variance / n)
        margin = float(stats.t.ppf(0.975, n - 1)) * error
        cohorts.append(
            ControlCohort(block=block, n=n, mean=mean, ci_low=mean - margin, ci_high=mean + margin)
        )
        errors.append(error)
    everyone = [v for block in sorted(values) for v in values[block]]
    return ControlBaseline(
        cohorts=tuple(cohorts),
        pooled_mean=math.fsum(everyone) / len(everyone),
        homogeneity_p=_baseline_p(metric, values, cohorts, errors),
    )


def _baseline_p(
    metric: ExportMetric,
    values: dict[int, list[float]],
    cohorts: list[ControlCohort],
    errors: list[float],
) -> float | None:
    try:
        if metric.kind == "binary":
            blocks = sorted(values)
            return homogeneity_test(
                [round(sum(values[b])) for b in blocks],
                [len(values[b]) for b in blocks],
                exact_below=SMALL_EXPECTED_COUNT,
            ).p_value
        corrected = [e * welch_correction(c.n - 1) for e, c in zip(errors, cohorts, strict=True)]
        return cohort_heterogeneity(
            [c.mean for c in cohorts], corrected, positions=[c.block for c in cohorts]
        ).q_p_value
    except StatsError:
        return None
