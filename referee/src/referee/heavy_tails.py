"""The signs of a heavy tail that RES-008 looks for, group by group (design section 21.11).

A metric whose values are mostly zero, with a few large ones, has a mean that is far from
normal in a sample the size of an experiment, and the usual interval for a difference of means
(Welch's) is then wrong more or less often than it says. Referee does not test for that. It
looks for three signs in the analysed players of each group (an arm, or control):

- `kohavi`: the rule of thumb of Kohavi, Deng, Longbotham and Xu (2014) for when the mean of a
  sample is nearly normal: a group needs at least 355 times its squared skewness in players,
  and the sample skewness is above 1 in size;
- `kurtosis`: an excess kurtosis above 100;
- `top_share`: the top 1% of players holding more than half of the total.

The first is the paper's. The levels of the other two are Referee's judgement (section 21.11):
the study of section 21.10 could not place them, because the first or the second sign
appeared in every simulated run of a revenue-like metric.

The decisions use the numbers as they are stored, rounded to `DIGITS` places, so that the
evidence and the decision cannot disagree. A group that cannot be read says why, and the
pair is judged on the group that can.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from referee.cohorts import units_independent
from referee.methods import NoVariationError, StatsError, heavy_tail_measures
from referee.pooled_rates import Case, Effects, Larger, SimulatedRange, hull, lookup
from referee.results import METRIC_FAMILIES, ExportMetric, ResultsContext, difference_summary

KOHAVI_MULTIPLE = 355  # players wanted per unit of squared skewness
SKEWNESS_OVER = 1  # the rule applies to a skewness above this in size
KURTOSIS_OVER = 100  # excess kurtosis; judgement
TOP_PERCENT = 1  # the share of players whose part of the total is measured
TOP_SHARE_OVER = 0.5  # judgement
DIGITS = 6
# Up to this split the groups are "about equal in size": halfway from 1 to the next simulated
# split, 1.5 to 1. (`cohort_effects.FADE_MAX_ALLOCATION_RATIO` is the same number.)
EQUAL_ARMS_SPLIT = Fraction(5, 4)
# The effects simulated were none, +20%, +50% and +100%, each the arm's mean over control's
# minus 1 with the arm the group with the higher mean. A difference seen whose higher mean is
# less than this share above the lower one, halfway from +20% to +50%, is nearer the first two.
LARGE_EFFECT_FROM = 0.35
# A difference between the means above this share is not printed or measured: it is without
# bound for the purpose (the effects simulated were at most +100%).
EFFECT_CAP = 1e6
# Two simulated cases on either side of a comparison are "far apart" when their numbers of
# players who spend differ by this factor, or their splits by the second.
FAR_APART_PAYERS = 5
FAR_APART_SPLIT = Fraction(5, 2)

Limb = Literal["kohavi", "kurtosis", "top_share"]
LIMBS: tuple[Limb, ...] = ("kohavi", "kurtosis", "top_share")
Unread = Literal["too_few_players", "all_zero", "no_variation", "negative_value", "not_computable"]
Status = Literal["tripped", "not_tripped", "not_evaluated"]
NotSimulated = Literal[
    "metric_not_simulated",
    "unit_not_independent",
    "a_group_has_no_players",
    "no_players_who_spend",
]


def kohavi_minimum(skewness: float) -> float:
    """The players a group needs, by the rule of thumb, at a given sample skewness."""
    return KOHAVI_MULTIPLE * skewness**2


def kohavi_trips(n: int, skewness: float) -> bool:
    """A skewness above 1 in size, in a group of fewer players than the rule asks for (the
    figure the evidence shows, rounded to `DIGITS` places)."""
    return abs(skewness) > SKEWNESS_OVER and n < round(kohavi_minimum(skewness), DIGITS)


def kurtosis_trips(excess_kurtosis: float) -> bool:
    return excess_kurtosis > KURTOSIS_OVER


def share_trips(top_share: float) -> bool:
    return top_share > TOP_SHARE_OVER


@dataclass(frozen=True, kw_only=True)
class GroupShape:
    """What one group of analysed players looks like on one metric.

    `payers` are the players with a value other than 0 (players who spend, for money). When
    the group cannot be read, `unread` says why and the measures are None.
    """

    arm: str
    n: int
    payers: int
    unread: Unread | None
    mean: float | None = None
    skewness: float | None = None
    excess_kurtosis: float | None = None
    top_share: float | None = None
    top_count: int | None = None
    limbs: tuple[Limb, ...] = ()

    @property
    def read(self) -> bool:
        return self.unread is None

    @property
    def kohavi_minimum(self) -> float | None:
        return None if self.skewness is None else round(kohavi_minimum(self.skewness), DIGITS)


def _unreadable(values: Sequence[float]) -> Unread | None:
    """Why the values cannot be measured, found before they are measured: too few, not finite,
    negative or all 0. That they do not vary, or are too large or small, is found by
    `heavy_tail_measures` itself."""
    if len(values) < 2:
        return "too_few_players"
    if not all(math.isfinite(value) for value in values):
        return "not_computable"
    if min(values) < 0:
        return "negative_value"
    if all(value == 0 for value in values):
        return "all_zero"
    return None


def _mean(values: Sequence[float]) -> float | None:
    """The mean of `values` to `DIGITS` significant figures (a metric can be in any unit), or
    None when there is none to give: no values, a value that is not finite or is negative, or a
    sum too large to hold."""
    if not values or not all(math.isfinite(value) and value >= 0 for value in values):
        return None
    try:
        mean = math.fsum(values) / len(values)
    except OverflowError:
        return None
    return float(f"{mean:.{DIGITS}g}") if math.isfinite(mean) else None


def group_shape(arm: str, values: Sequence[float]) -> GroupShape:
    """The shape of `values`, the metric of the analysed players of `arm`.

    A group that cannot be read still has a mean when its values allow one (all 0, all the same,
    a single player), because the size of the difference between the groups needs it.
    """
    n = len(values)
    payers = sum(1 for value in values if value != 0)
    unread = _unreadable(values)
    if unread is None:
        try:
            found = heavy_tail_measures(values, top_percent=TOP_PERCENT)
        except NoVariationError:
            unread = "no_variation"
        except StatsError:
            unread = "not_computable"  # values too large or too small to measure
    if unread is not None:
        return GroupShape(arm=arm, n=n, payers=payers, unread=unread, mean=_mean(values))
    skewness = round(found.skewness, DIGITS)
    kurtosis = round(found.excess_kurtosis, DIGITS)
    share = round(found.top_share, DIGITS)
    tripped = {
        "kohavi": kohavi_trips(n, skewness),
        "kurtosis": kurtosis_trips(kurtosis),
        "top_share": share_trips(share),
    }
    return GroupShape(
        arm=arm,
        n=n,
        payers=payers,
        unread=None,
        mean=_mean(values),
        skewness=skewness,
        excess_kurtosis=kurtosis,
        top_share=share,
        top_count=found.top_count,
        limbs=tuple(limb for limb in LIMBS if tripped[limb]),
    )


@dataclass(frozen=True, kw_only=True)
class Comparison:
    """What a rule can see of an arm and control that the simulations were indexed by.

    `split` is the larger group's analysed players over the smaller's, `larger` which group
    that is (`equal` when they are the same size), `smaller` the name of the smaller group and
    `payers` its players with a value other than 0. Of two groups of the same size the smaller
    is the one with fewer such players, and then control.
    """

    split: Fraction
    larger: Larger
    smaller: str
    payers: int

    @property
    def placed_as_equal(self) -> bool:
        """Whether the groups are "about equal in size" (up to `EQUAL_ARMS_SPLIT`), and are
        placed among the cases of two groups of the same size."""
        return self.split <= EQUAL_ARMS_SPLIT

    @property
    def placed_split(self) -> Fraction:
        """The split the comparison is placed at: 1 for groups about equal in size."""
        return Fraction(1) if self.placed_as_equal else self.split


def compare(arm: GroupShape, control: GroupShape) -> Comparison | None:
    """The comparison of an arm with control, or None when a group has no players at all."""
    if arm.n == 0 or control.n == 0:
        return None
    split = Fraction(max(arm.n, control.n), min(arm.n, control.n))
    if arm.n == control.n:
        smaller = arm if arm.payers < control.payers else control
        larger: Larger = "equal"
    elif arm.n < control.n:
        smaller, larger = arm, "control"
    else:
        smaller, larger = control, "arm"
    return Comparison(split=split, larger=larger, smaller=smaller.arm, payers=smaller.payers)


@dataclass(frozen=True, kw_only=True)
class Pair:
    """An arm against control on one metric: both shapes, the signs found, the comparison and
    Welch's 95% interval for the difference (as `difference_summary` gives it)."""

    arm: GroupShape
    control: GroupShape
    status: Status
    limbs: tuple[Limb, ...]
    comparison: Comparison | None
    estimate: dict[str, Any]

    @property
    def groups(self) -> tuple[GroupShape, GroupShape]:
        return self.arm, self.control

    @property
    def relative_difference(self) -> float | None:
        """The difference seen (arm less control) as a share of control's mean, from the means
        the evidence shows (so that it and `effect_seen` agree). None when a mean is missing,
        control's is not above 0, or the share is beyond `EFFECT_CAP`."""
        arm, control = self.arm.mean, self.control.mean
        if arm is None or control is None or control <= 0:
            return None
        share = (arm - control) / control
        return share if abs(share) <= EFFECT_CAP else None

    @property
    def effect_seen(self) -> float | None:
        """The effect seen in the terms of the simulations: the higher mean over the lower one,
        minus 1, rounded to `DIGITS` places. None when a mean is missing or the lower one is 0
        (the effect is then without bound: see `nearer_effects`)."""
        arm, control = self.arm.mean, self.control.mean
        if arm is None or control is None or min(arm, control) <= 0:
            return None
        effect = max(arm, control) / min(arm, control) - 1
        return round(effect, DIGITS) if effect <= EFFECT_CAP else None

    @property
    def nearer_effects(self) -> Effects | None:
        """The set of simulated effects nearer the difference seen: `large` (+50% and +100%)
        from `LARGE_EFFECT_FROM`, else `small` (none and +20%). The effect is measured as the
        simulations do (the higher mean over the lower one, minus 1), so swapping which group is
        called control changes nothing. A lower mean of 0 with a higher one above it is `large`;
        None when a mean is missing or both are 0."""
        arm, control = self.arm.mean, self.control.mean
        if arm is None or control is None or max(arm, control) <= 0:
            return None
        effect = self.effect_seen
        return "large" if effect is None or effect >= LARGE_EFFECT_FROM else "small"


def pair_of(arm: GroupShape, control: GroupShape, estimate: dict[str, Any] | None = None) -> Pair:
    """The pair trips when any group that can be read does; it is not evaluated when none does
    and some group could not be read."""
    read = [group for group in (arm, control) if group.read]
    limbs = tuple(limb for limb in LIMBS if any(limb in group.limbs for group in read))
    status: Status
    if limbs:
        status = "tripped"
    elif len(read) < 2:
        status = "not_evaluated"
    else:
        status = "not_tripped"
    return Pair(
        arm=arm,
        control=control,
        status=status,
        limbs=limbs,
        comparison=compare(arm, control),
        estimate={} if estimate is None else estimate,
    )


def pairs(context: ResultsContext, metric: ExportMetric) -> list[Pair]:
    """Every non-control arm against control on `metric`, in the spec's order of arms.

    The analysed players are read (design section 21.3), the control's shape once.
    """
    values: dict[str, list[float]] = {name: [] for name in context.arm_names}
    for player in context.analysed:
        values[player.arm].append(metric.value(player))
    control = group_shape(context.control, values[context.control])
    return [
        pair_of(
            group_shape(name, values[name]),
            control,
            difference_summary(metric, values[name], values[context.control]),
        )
        for name in context.arm_names
        if name != context.control
    ]


def not_simulated(
    context: ResultsContext, metric: ExportMetric, comparison: Comparison | None
) -> NotSimulated | None:
    """Why the simulated rates do not apply to this spec, metric and comparison, or None.

    They were found for revenue-like metrics of independent players, and are indexed by the
    players who spend in the smaller group, so they say nothing for another kind of metric, for
    units that are not independent players, or when a group is empty or nobody spends in the
    smaller one.
    """
    if METRIC_FAMILIES.get(metric.name) != "revenue_like":
        return "metric_not_simulated"
    if not units_independent(context):
        return "unit_not_independent"
    if comparison is None:
        return "a_group_has_no_players"
    if comparison.payers == 0:
        return "no_players_who_spend"
    return None


def simulated(comparison: Comparison) -> dict[Effects, SimulatedRange]:
    """The ranges of the pooled-effect study around a comparison, for a small effect (none or
    +20%) and a large one (+50% or +100%). The caller has checked `not_simulated`.

    Groups about equal in size are placed among the cases of two groups of the same size. For
    other groups the range covers both orders: in the simulated cases the arm is the group with
    the higher mean, and the sample does not show which group that is (with few players who
    spend the group with the higher mean seen can be the one with the lower true mean), so
    the cases with the arm the larger and with control the larger are both read."""
    out: dict[Effects, SimulatedRange] = {}
    for effects in ("small", "large"):
        if comparison.placed_as_equal:
            out[effects] = lookup(effects, "equal", Fraction(1), comparison.payers)
        else:
            out[effects] = hull(
                lookup(effects, "arm", comparison.split, comparison.payers),
                lookup(effects, "control", comparison.split, comparison.payers),
            )
    return out


def nearest_cases(found: SimulatedRange, comparison: Comparison) -> tuple[Case, ...]:
    """The cases of `found` nearest the comparison: least distance in the logs of the split and
    of the players who spend added up. Cases at the same distance are all returned (a range
    read both ways round holds each case twice over, once for each order)."""

    def distance(case: Case) -> float:
        return abs(math.log(float(case.split / comparison.placed_split))) + abs(
            math.log(case.payers / comparison.payers)
        )

    nearest = min(distance(case) for case in found.cases)
    return tuple(case for case in found.cases if distance(case) <= nearest + 1e-9)


def far_apart(found: SimulatedRange) -> bool:
    """Whether the cases on the two sides of the comparison lie far from each other, so that
    the ends of the range come from cases further from it than the nearest one."""
    splits = [case.split for case in found.cases]
    counts = [case.payers for case in found.cases]
    return max(counts) >= FAR_APART_PAYERS * min(counts) or max(splits) >= FAR_APART_SPLIT * min(
        splits
    )
