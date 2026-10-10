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

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from referee.cohorts import MIN_COHORTS, CohortPlan
from referee.methods import (
    CohortHeterogeneity,
    NonPositiveMeanError,
    NoVariationError,
    StatsError,
    cohort_heterogeneity,
    log_mean_ratio,
    welch_correction,
    welch_difference,
)
from referee.results import ExportMetric, ResultsContext

TRIGGER_LEVEL = 0.025  # per statistic, before dividing by the number of non-control arms
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
