"""Sample size, duration and detectable-effect calculations for an experiment spec.

Everything here is a closed-form normal approximation built on the standard library
(`statistics.NormalDist`), so results are deterministic and need no dependencies. The
tests check the two building blocks against statsmodels, which is a development tool only.

Sizes are always for the whole experiment: the control arm and every variant must reach the
target power against the control, so the most demanding variant-versus-control comparison
sets the total. Relative effects follow the spec: `mde_relative` is a fraction of the
baseline, and `hypothesis.direction` says which way the treatment moves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

from referee.spec import ExperimentSpec, Sidedness

AlphaAdjustment = Literal["bonferroni", "none"]
EffectDirection = Literal["increase", "decrease"]

_Z = NormalDist().inv_cdf
_DAYS_PER_WEEK = 7


class PowerError(ValueError):
    """The parameters cannot be turned into a sample size, e.g. a rate that leaves (0, 1)."""


def _require_probability(name: str, value: float) -> None:
    if not 0 < value < 1:
        raise PowerError(f"{name} must satisfy 0 < {name} < 1, got {value!r}")


def _require_positive(name: str, value: float) -> None:
    # A positive test, so NaN (which fails every comparison) is rejected too.
    if not value > 0:
        raise PowerError(f"{name} must be > 0, got {value!r}")


def _z_alpha(alpha: float, sided: Sidedness) -> float:
    return _Z(1 - alpha / 2) if sided == "two_sided" else _Z(1 - alpha)


def _target_rate(baseline: float, mde_relative: float, direction: EffectDirection) -> float | None:
    """The treatment rate a relative effect implies, or None if it leaves (0, 1)."""
    sign = 1 if direction == "increase" else -1
    rate = baseline * (1 + sign * mde_relative)
    return rate if 0 < rate < 1 else None


def control_n_proportions(
    *,
    baseline: float,
    mde_relative: float,
    direction: EffectDirection,
    alpha: float,
    power: float,
    ratio: float = 1.0,
    sided: Sidedness = "two_sided",
) -> float:
    """Control-arm size for a two-proportion test whose variant is `ratio` times as large.

    The classical formula, with the variance pooled under the null and separate under the
    alternative. Returned unrounded; the variant needs `ratio` times this many units.
    """
    _require_probability("baseline", baseline)
    _require_positive("mde_relative", mde_relative)
    _require_probability("alpha", alpha)
    _require_probability("power", power)
    _require_positive("ratio", ratio)
    treated = _target_rate(baseline, mde_relative, direction)
    if treated is None:
        raise PowerError(
            f"a relative {direction} of {mde_relative:g} on a rate of {baseline:g} "
            "leaves the range 0 to 1"
        )
    pooled = (baseline + ratio * treated) / (1 + ratio)
    spread = _z_alpha(alpha, sided) * math.sqrt(pooled * (1 - pooled) * (1 + 1 / ratio)) + _Z(
        power
    ) * math.sqrt(baseline * (1 - baseline) + treated * (1 - treated) / ratio)
    return spread**2 / (treated - baseline) ** 2


def control_n_means(
    *,
    mean: float,
    std: float,
    mde_relative: float,
    alpha: float,
    power: float,
    ratio: float = 1.0,
    sided: Sidedness = "two_sided",
) -> float:
    """Control-arm size for a two-mean z-test whose variant is `ratio` times as large.

    Assumes a known standard deviation, the same in both arms. The t-test needs a few units
    more at small sizes, which is immaterial next to the uncertainty in `std` itself.
    """
    _require_positive("std", std)
    _require_positive("mde_relative", mde_relative)
    _require_probability("alpha", alpha)
    _require_probability("power", power)
    _require_positive("ratio", ratio)
    shift = abs(mean) * mde_relative
    if not shift > 0:
        raise PowerError("a relative effect on a baseline mean of 0 is an absolute effect of 0")
    return (1 + 1 / ratio) * std**2 * (_z_alpha(alpha, sided) + _Z(power)) ** 2 / shift**2


def _allowed_directions(spec: ExperimentSpec) -> tuple[EffectDirection, ...]:
    direction = spec.hypothesis.direction
    return ("increase", "decrease") if direction == "two_sided" else (direction,)


def _control_n(spec: ExperimentSpec, *, alpha: float, mde_relative: float, ratio: float) -> float:
    metric, design = spec.primary_metric, spec.design
    if metric.kind != "binary":
        # For a ratio metric, `baseline_std` is the standard deviation of the ratio itself
        # (its delta-method spread), so it is treated like a continuous metric's.
        return control_n_means(
            mean=metric.baseline,
            std=metric.baseline_std,
            mde_relative=mde_relative,
            alpha=alpha,
            power=design.power,
            ratio=ratio,
            sided=design.sided,
        )
    # A two-sided hypothesis is planned for the direction that needs more units.
    sizes = [
        control_n_proportions(
            baseline=metric.baseline,
            mde_relative=mde_relative,
            direction=direction,
            alpha=alpha,
            power=design.power,
            ratio=ratio,
            sided=design.sided,
        )
        for direction in _allowed_directions(spec)
        if _target_rate(metric.baseline, mde_relative, direction) is not None
    ]
    if not sizes:
        raise PowerError(
            f"a relative effect of {mde_relative:g} on a rate of {metric.baseline:g} "
            "leaves the range 0 to 1 in every direction the hypothesis allows"
        )
    return max(sizes)


def _per_arm_units(
    spec: ExperimentSpec, *, alpha: float, mde_relative: float, shares: tuple[float, ...]
) -> tuple[int, ...]:
    """Units each arm needs so that every variant-versus-control comparison is powered."""
    control_share = next(
        share for arm, share in zip(spec.arms, shares, strict=True) if arm.is_control
    )
    total = max(
        _control_n(spec, alpha=alpha, mde_relative=mde_relative, ratio=share / control_share)
        / control_share
        for arm, share in zip(spec.arms, shares, strict=True)
        if not arm.is_control
    )
    return tuple(math.ceil(share * total) for share in shares)


def _mde_search_ceiling(spec: ExperimentSpec) -> float | None:
    """The largest relative effect a binary metric can express, or None if unbounded."""
    if spec.primary_metric.kind != "binary":
        return None
    baseline = spec.primary_metric.baseline
    room = {"increase": (1 - baseline) / baseline, "decrease": 1.0}
    return max(room[direction] for direction in _allowed_directions(spec)) * (1 - 1e-9)


def _achievable_mde(
    spec: ExperimentSpec, *, alpha: float, shares: tuple[float, ...], achievable_total: int
) -> float | None:
    """The smallest relative effect the achievable sample can detect, by bisection.

    Required units fall as the effect grows, so the smallest feasible effect is a single
    crossing point. Returns None if even the largest expressible effect is out of reach.
    """

    def affordable(mde_relative: float) -> bool:
        units = _per_arm_units(spec, alpha=alpha, mde_relative=mde_relative, shares=shares)
        return sum(units) <= achievable_total

    high = _mde_search_ceiling(spec)
    if high is None:
        high = spec.design.mde_relative
        while not affordable(high):
            high *= 2
            if high > 1e6:
                return None
    elif not affordable(high):
        return None

    low = 0.0
    for _ in range(200):
        middle = (low + high) / 2
        if affordable(middle):
            high = middle
        else:
            low = middle
        if high - low <= 1e-12 * high:
            break
    return high


@dataclass(frozen=True, kw_only=True)
class PowerPlan:
    """What the spec's design needs, and what its planned duration can deliver."""

    comparisons: int
    alpha_per_comparison: float
    required_per_arm: tuple[tuple[str, int], ...]
    required_total: int
    equal_split_total: int
    required_days: int
    required_days_whole_weeks: int
    achievable_total: int
    achievable_mde_relative: float | None

    @property
    def is_powered(self) -> bool:
        return self.required_total <= self.achievable_total

    @property
    def extra_units_vs_equal_split(self) -> float:
        """Fraction of extra units this allocation needs over an equal split (0.18 is +18%)."""
        return self.required_total / self.equal_split_total - 1


def power_alpha_adjustment(spec: ExperimentSpec) -> AlphaAdjustment:
    """The adjustment the power plan uses for what the spec declares.

    Only an explicit "none" turns the adjustment off. An absent field and "bonferroni" plan
    with Bonferroni, and so does "dunnett", which is slightly less conservative but is not
    implemented here: the plan may ask for a few more units than Dunnett would.
    """
    return "none" if spec.design.alpha_adjustment == "none" else "bonferroni"


def plan_power(
    spec: ExperimentSpec, *, alpha_adjustment: AlphaAdjustment = "bonferroni"
) -> PowerPlan:
    """Size the experiment described by `spec`.

    With more than two arms, Bonferroni divides alpha by the number of variant-versus-control
    comparisons. Raises PowerError if the target effect cannot exist (a rate above 1).
    """
    arms, design = spec.arms, spec.design
    comparisons = len(arms) - 1
    alpha = design.alpha / comparisons if alpha_adjustment == "bonferroni" else design.alpha
    shares = tuple(arm.allocation for arm in arms)
    equal_shares = tuple(1 / len(arms) for _ in arms)

    per_arm = _per_arm_units(spec, alpha=alpha, mde_relative=design.mde_relative, shares=shares)
    required_total = sum(per_arm)
    equal_split_total = sum(
        _per_arm_units(spec, alpha=alpha, mde_relative=design.mde_relative, shares=equal_shares)
    )
    daily = spec.population.daily_eligible_units
    required_days = math.ceil(required_total / daily)
    achievable_total = daily * design.planned_duration_days
    return PowerPlan(
        comparisons=comparisons,
        alpha_per_comparison=alpha,
        required_per_arm=tuple((arm.name, units) for arm, units in zip(arms, per_arm, strict=True)),
        required_total=required_total,
        equal_split_total=equal_split_total,
        required_days=required_days,
        required_days_whole_weeks=math.ceil(required_days / _DAYS_PER_WEEK) * _DAYS_PER_WEEK,
        achievable_total=achievable_total,
        achievable_mde_relative=_achievable_mde(
            spec, alpha=alpha, shares=shares, achievable_total=achievable_total
        ),
    )
