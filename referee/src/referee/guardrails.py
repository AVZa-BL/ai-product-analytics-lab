"""Whether a guardrail was breached, measured two ways (design section 21.12).

A guardrail is a metric that must not get worse by more than a registered share: it has a
`harmful_direction`, a `tolerance_relative` and a registered `baseline`, and the spec says it is
breached "when worse than baseline x (1 +- tolerance)". Whether it was is a question about the
true value, and the data give an estimate with an interval, so a breach comes in two strengths:

- `shown`: the whole 95% interval for the harm lies beyond the tolerance;
- `possible`: only the point estimate does, and the interval still reaches inside the tolerance.

A comparison whose point estimate is within the tolerance is `within`, even when the harmful end
of its interval is beyond it (`not_verified`): that is not enough to call a breach and does not
show the guardrail to be unharmed, and the rule says nothing about it.

"Worse than baseline" is read against two references, and the stricter one decides:

- `control`: the arm's mean against the control's observed mean, as a ratio (the change that
  the experiment caused, whatever the world did to the baseline since it was registered);
- `baseline`: the arm's own mean against the registered baseline (the spec as written).

Both are unadjusted 95% intervals for each arm and guardrail. Harm is a share of the reference,
positive when worse. Decisions use the shares rounded to `DIGITS` places, so that the evidence
and the decision cannot disagree.

Three kinds of reading are not allowed to be `shown`: two because their intervals cannot carry
that claim there, and one because the arm may owe it nothing:

- a group whose values are all the same has an interval with no width. That is believed only
  when chance cannot explain it: if the other group, which the group would be drawn from had
  the arm changed nothing, has the group's value in a share of its players that makes `n`
  players all alike at least `CHANCE_LEVEL` of the time (all players of a revenue arm at 0,
  with a few percent of control's buying), the interval is held to `possible`;
- the arm's own mean of a revenue-like guardrail (most players at 0, a few large) against the
  registered baseline when a fall is harmful and the group has some spread. The t interval for
  the mean of such data lies
  wholly below the true mean far more often than 2.5% of the time, which for a guardrail whose
  fall is harmful is a false breach; the reading against control's mean is not held;
- the arm's reading against the registered baseline when control itself is shown beyond the
  baseline's tolerance and the reading against control's mean is within it
  (`hold_for_a_moved_baseline`): the arm may be what control is, and the baseline no longer what
  the traffic gives.

A held reading is counted as `possible` (its point estimate is beyond the tolerance) and the
evidence says why.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from referee.methods import (
    NonPositiveMeanError,
    NoVariationError,
    mean_interval,
    mean_ratio,
    proportion_interval,
    values_are_constant,
)
from referee.results import METRIC_FAMILIES, ResultsContext, window_is_open
from referee.spec import Guardrail

ALPHA = 0.05
CONFIDENCE = 1 - ALPHA
DIGITS = 6
# A group of players who all have one value is as alike as chance allows if, drawn from the other
# group, it would be so at least this often (one tail of the 95% interval; judgement).
CHANCE_LEVEL = ALPHA / 2
# Fewer than this many players on either side of a rate (or of its complement) make the normal
# approximations behind the intervals of a binary guardrail rough (judgement; the usual rule of
# thumb for the normal approximation to a binomial is 10).
SMALL_COUNT = 10

Reference = Literal["control", "baseline"]
Tier = Literal["within", "possible", "shown"]
Status = Literal["breach_shown", "breach_possible", "within_tolerance", "not_evaluated"]
Cap = Literal["no_variation", "heavy_tail", "moved_baseline"]  # why `shown` is `possible`
REFERENCES: tuple[Reference, ...] = ("control", "baseline")
TIERS: tuple[Tier, ...] = ("within", "possible", "shown")  # least to most serious
_UNMEASURABLE = "cannot be measured (a value is not a finite number, or is too large or too small)"
_STATUS: dict[Tier, Status] = {
    "shown": "breach_shown",
    "possible": "breach_possible",
    "within": "within_tolerance",
}


@dataclass(frozen=True, kw_only=True)
class Harm:
    """The harmful change on one reference, as a share of the reference value.

    Positive is worse. `point`, `low` and `high` are the estimate and the ends of its 95%
    interval, rounded to `DIGITS` places; `reference_value` is what the share is of (the
    control's mean, or the registered baseline); `measured` is the quantity the interval was
    made for (the ratio of means, or the arm's own mean or rate), with its ends.
    `tier` is the tier after the cap `capped_by` names, if any.
    """

    point: float
    low: float
    high: float
    tier: Tier
    not_verified: bool  # the point estimate is within the tolerance but the interval is not
    reference_value: float
    measured: tuple[float, float, float]
    no_variation: bool = False  # every value of a group is the same: the interval has no width
    constant_group: Literal["arm", "control"] | None = None  # which group that is
    chance_all_alike: float | None = None  # the chance that so many players alike arise by chance
    capped_by: Cap | None = None  # why `shown` was counted as `possible`, when it was
    uncapped_tier: Tier | None = None  # the tier before that cap


@dataclass(frozen=True, kw_only=True)
class ReferenceResult:
    """One reference's answer: the harm, or why there is none."""

    reference: Reference
    harm: Harm | None
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class GuardrailTest:
    """A non-control arm against control on one guardrail, read against both references."""

    arm: str
    guardrail: str
    kind: Literal["binary", "continuous"]
    harmful_direction: Literal["increase", "decrease"]
    tolerance: float
    baseline: float
    n_arm: int
    n_control: int
    mean_arm: float | None
    mean_control: float | None
    events_arm: int | None  # players with the outcome, for a binary guardrail
    events_control: int | None
    control: ReferenceResult
    baseline_reference: ReferenceResult
    control_on_baseline: ReferenceResult  # the control's own place against the registered baseline

    @property
    def results(self) -> tuple[ReferenceResult, ReferenceResult]:
        return self.control, self.baseline_reference

    @property
    def tier(self) -> Tier | None:
        """The stricter of the two references' tiers; None when neither could be measured."""
        found = [r.harm.tier for r in self.results if r.harm is not None]
        return max(found, key=TIERS.index) if found else None

    @property
    def status(self) -> Status:
        tier = self.tier
        return "not_evaluated" if tier is None else _STATUS[tier]

    @property
    def decided_by(self) -> tuple[Reference, ...]:
        """The references whose tier is the one that counts."""
        tier = self.tier
        return tuple(
            r.reference for r in self.results if r.harm is not None and r.harm.tier == tier
        )

    @property
    def references_agree(self) -> bool | None:
        """Whether the two references give the same tier; None when one could not be measured."""
        tiers = [r.harm.tier for r in self.results if r.harm is not None]
        return None if len(tiers) < 2 else tiers[0] == tiers[1]

    @property
    def baseline_has_moved(self) -> bool:
        """Whether the control itself is beyond the tolerance of the registered baseline, so that
        a breach on that reference may owe nothing to the arm."""
        harm = self.control_on_baseline.harm
        return harm is not None and harm.tier != "within"

    @property
    def unreachable(self) -> tuple[Reference, ...]:
        """The references that cannot show a breach whatever the data, because the harm they can
        measure is bounded below the tolerance.

        A fall of a non-negative metric is at most 100% of any reference value, so a tolerance
        of 100% or more is out of reach on both; and a rate cannot rise above 1, so against a
        registered baseline of a binary guardrail the harm of an increase is at most
        (1 - baseline) / baseline, so a tolerance at or above that, which is baseline x
        (1 + tolerance) >= 1, can never be exceeded. (Control's own rate can still be exceeded by
        the tolerance if it is below 1 / (1 + tolerance), which the data decide.)
        """
        if self.harmful_direction == "decrease":
            return REFERENCES if self.tolerance >= 1 else ()
        if self.kind == "binary" and self.baseline * (1 + self.tolerance) >= 1:
            return ("baseline",)
        return ()

    @property
    def small_counts(self) -> bool:
        """Whether a binary guardrail has fewer than `SMALL_COUNT` players on either side of its
        rate in the arm or in control."""
        if self.kind != "binary":
            return False
        for events, n in ((self.events_arm, self.n_arm), (self.events_control, self.n_control)):
            if events is not None and n and min(events, n - events) < SMALL_COUNT:
                return True  # an empty group has no rate to be rough
        return False


def tier_of(point: float, low: float, tolerance: float) -> Tier:
    """`shown` when the whole interval is beyond the tolerance (its less harmful end is),
    `possible` when only the point estimate is, else `within`. Beyond means strictly worse."""
    if low > tolerance:
        return "shown"
    if point > tolerance:
        return "possible"
    return "within"


def _harm(
    direction: str,
    change: tuple[float, float, float],
    *,
    tolerance: float,
    reference_value: float,
    measured: tuple[float, float, float],
    constant_group: Literal["arm", "control"] | None = None,
    chance_all_alike: float | None = None,
    heavy_tail: bool = False,
) -> Harm:
    """The harm from a relative change (point, low, high): its sign flipped when a decrease is
    the harmful direction (the ends then swap too).

    A reading that would be `shown` is counted as `possible` when a group has no variation (its
    interval has no width) and chance could explain that (`chance_all_alike` is not below
    `CHANCE_LEVEL`; None means unknown, which holds it), or when `heavy_tail` says the t interval
    of a group with some spread is not to be trusted to show a breach on its own; `capped_by` and
    `uncapped_tier` say so.
    """
    point, low, high = change
    if direction == "decrease":
        point, low, high = -point, -high, -low
    # Adding 0.0 turns -0.0 (a decrease flipped from 0, or a tiny negative rounded) into 0.0.
    point, low, high = (round(x, DIGITS) + 0.0 for x in (point, low, high))
    tier = tier_of(point, low, tolerance)
    capped_by: Cap | None = None
    uncapped_tier: Tier | None = None
    if tier == "shown":
        if constant_group is not None and chance_could_explain(chance_all_alike):
            capped_by = "no_variation"
        elif heavy_tail and constant_group is None:  # a group with no spread has no t interval
            capped_by = "heavy_tail"
        if capped_by:
            uncapped_tier, tier = tier, "possible"
    # The fall of a non-negative metric is at most the whole of the reference: an interval that
    # runs past it (a t interval below 0) does not leave a breach open that cannot happen.
    reach = min(high, 1.0) if direction == "decrease" else high
    return Harm(
        point=point,
        low=low,
        high=high,
        tier=tier,
        not_verified=tier == "within" and reach > tolerance,
        reference_value=reference_value,
        measured=measured,
        no_variation=constant_group is not None,
        constant_group=constant_group,
        chance_all_alike=chance_all_alike,
        capped_by=capped_by,
        uncapped_tier=uncapped_tier,
    )


def chance_could_explain(chance: float | None) -> bool:
    """Whether so many players alike are not rare enough to rule out chance: the chance is not
    below `CHANCE_LEVEL`, or is unknown (None)."""
    return chance is None or chance >= CHANCE_LEVEL


def _chance_all_alike(group: Sequence[float], other: Sequence[float]) -> float:
    """The chance that `len(group)` players drawn from `other` all have the value of `group`.

    `other` stands for what the group would be drawn from had the arm changed nothing: the share
    of its players at that value, to the power of the number of players. 1.0 when `other` is
    empty, so that nothing is concluded from the absence of a comparison.
    """
    if not other:
        return 1.0
    value = group[0]
    share = sum(math.isclose(x, value, rel_tol=1e-9) for x in other) / len(other)
    return share ** len(group)


def _finite(*numbers: float) -> bool:
    return all(math.isfinite(number) for number in numbers)


def control_reference(
    arm: Sequence[float],
    control: Sequence[float],
    *,
    direction: str,
    tolerance: float,
    arm_name: str = "the arm",
) -> ReferenceResult:
    """The arm against the control's observed mean: the ratio of the means and its interval.

    The change is ratio - 1, and its interval is the ratio's. When one group has no variation
    the interval takes its width from the other alone, which is held to `possible` if chance
    could explain that group (see `_harm`). Not measurable when a group has fewer than 2
    players, when neither varies, when a mean is not above 0 (the ratio has no logarithm, and a
    share of a control mean of 0 is undefined; the other reference may still measure it) or
    when the numbers are too large or too small. Every reason names the group.
    """

    def unmeasured(reason: str) -> ReferenceResult:
        return ReferenceResult(reference="control", harm=None, reason=reason)

    short = [name for name, group in ((arm_name, arm), ("control", control)) if len(group) < 2]
    if short:
        verb = "has" if len(short) == 1 else "have"
        return unmeasured(f"{' and '.join(short)} {verb} fewer than 2 players")
    try:
        found = mean_ratio(arm, control, alpha=ALPHA)
    except NonPositiveMeanError:
        control_mean = _mean(control)  # a number: both means were worked out to get here
        if control_mean is not None and not control_mean > 0:
            return unmeasured("control's mean is not above 0, so a share of it is undefined")
        return unmeasured(
            f"the mean of {arm_name} is not above 0, so the ratio of the means has no logarithm "
            "and no interval can be formed"
        )
    except NoVariationError:
        return unmeasured(
            f"neither {arm_name} nor control varies, so the standard error of the ratio is 0 and "
            "nothing can be tested"
        )
    except (OverflowError, ValueError):  # a StatsError is a ValueError
        return unmeasured(f"the values of {arm_name} or control {_UNMEASURABLE}")
    if not _finite(found.ratio, found.ci_low, found.ci_high):
        return unmeasured(
            f"the ratio of the means of {arm_name} and control is too large to represent"
        )
    constant_group: Literal["arm", "control"] | None = None
    chance: float | None = None
    if values_are_constant(arm):
        constant_group, chance = "arm", _chance_all_alike(arm, control)
    elif values_are_constant(control):
        constant_group, chance = "control", _chance_all_alike(control, arm)
    change = (found.ratio - 1, found.ci_low - 1, found.ci_high - 1)
    return ReferenceResult(
        reference="control",
        harm=_harm(
            direction,
            change,
            tolerance=tolerance,
            reference_value=found.mean_control,
            measured=(found.ratio, found.ci_low, found.ci_high),
            constant_group=constant_group,
            chance_all_alike=chance,
        ),
    )


def baseline_reference(
    values: Sequence[float],
    *,
    baseline: float,
    kind: str,
    direction: str,
    tolerance: float,
    group: str = "the group",
    right_skewed: bool = False,
    against: Sequence[float] | None = None,
) -> ReferenceResult:
    """One group's own mean (or rate) against the registered baseline.

    The interval is the group's own: the t interval for the mean of a continuous metric, the
    Wilson interval for the rate of a binary one. Values that are all the same give an interval
    with no width, which says so; it is held to `possible` if chance could explain it, judged
    against `against` (what the group would be drawn from had the arm changed nothing: control's
    values for an arm, the arms' for control; None holds it always). `right_skewed` says the
    metric is revenue-like (most players at 0, a few large): when a fall is harmful the t
    interval for the mean of such data lies wholly below the true mean far too often, so for a
    group with some spread the reading is never `shown`. Not measurable for fewer than 2 players
    (1 for a rate), when the registered baseline is not above 0, or when the numbers are too
    large, too small or too close together to measure. Every reason names the group.
    """

    def unmeasured(reason: str) -> ReferenceResult:
        return ReferenceResult(reference="baseline", harm=None, reason=reason)

    if not baseline > 0:
        return unmeasured("the registered baseline is not above 0, so a share of it is undefined")
    if len(values) < (1 if kind == "binary" else 2):
        return unmeasured(
            f"{group} has no players" if not values else f"{group} has fewer than 2 players"
        )
    constant = False
    try:
        if kind == "binary":
            rate = proportion_interval(round(math.fsum(values)), len(values), alpha=ALPHA)
            measured = (rate.rate, rate.ci_low, rate.ci_high)
        else:
            try:
                found = mean_interval(values, alpha=ALPHA)
                measured = (found.mean, found.ci_low, found.ci_high)
            except NoVariationError:
                if not values_are_constant(values):  # the spread is there but underflows
                    return unmeasured(f"the spread of {group} is too small to measure")
                constant = True
                mean = _mean(values)
                if mean is None:
                    return unmeasured(f"the values of {group} {_UNMEASURABLE}")
                measured = (mean, mean, mean)
    except (OverflowError, ValueError):  # a StatsError is a ValueError
        return unmeasured(f"the values of {group} {_UNMEASURABLE}")
    change = tuple((x - baseline) / baseline for x in measured)
    if not _finite(*change):  # an end that is not finite, or a share beyond any float
        return unmeasured(f"the values of {group} {_UNMEASURABLE}")
    return ReferenceResult(
        reference="baseline",
        harm=_harm(
            direction,
            change,  # type: ignore[arg-type]
            tolerance=tolerance,
            reference_value=baseline,
            measured=measured,
            constant_group=("control" if group == "control" else "arm") if constant else None,
            chance_all_alike=(
                _chance_all_alike(values, against) if constant and against is not None else None
            ),
            heavy_tail=right_skewed and direction == "decrease" and kind == "continuous",
        ),
    )


def _mean(values: Sequence[float]) -> float | None:
    """The mean, or None for no values or one that cannot be represented; a group whose values
    are all the same has that value for its mean even where their sum overflows (as in
    `methods`)."""
    if not values:
        return None
    try:
        mean = math.fsum(values) / len(values)
    except OverflowError:
        return float(values[0]) if values_are_constant(values) else None
    return mean if math.isfinite(mean) else None


def _events(values: Sequence[float]) -> int:
    return round(math.fsum(values))


def hold_for_a_moved_baseline(
    reading: ReferenceResult, versus: ReferenceResult, own: ReferenceResult
) -> ReferenceResult:
    """The reading of an arm against the registered baseline, held to `possible` when it can owe
    nothing to the arm.

    Control itself is shown beyond the tolerance of the baseline (`own`) and the reading against
    control's mean (`versus`) is within it: the arm may be what control is, and the baseline no
    longer what the traffic gives. A reading that is not `shown`, or a control reading that is
    possible, shown or unmeasured, is left as it is.
    """
    harm = reading.harm
    if harm is None or harm.tier != "shown" or own.harm is None or own.harm.tier != "shown":
        return reading
    if versus.harm is None or versus.harm.tier != "within":
        return reading
    held = replace(harm, tier="possible", capped_by="moved_baseline", uncapped_tier="shown")
    return replace(reading, harm=held)


def guardrail_tests(context: ResultsContext) -> list[GuardrailTest]:
    """Every non-control arm against control on every guardrail, in the spec's order.

    The guardrails come in the order the spec lists them and the arms inside each in the spec's
    order. The players are the analysed ones (design section 21.3) whose outcome window had
    closed when the export was taken, where its time is known (section 21.12).
    """
    tests: list[GuardrailTest] = []
    for guardrail in context.spec.guardrails:
        tests += _tests_of(context, guardrail)
    return tests


def _tests_of(context: ResultsContext, guardrail: Guardrail) -> list[GuardrailTest]:
    metric = context.metrics[guardrail.name]
    values: dict[str, list[float]] = {name: [] for name in context.arm_names}
    for player in context.analysed:
        # A window still open holds part of a week of sessions, purchases or revenue: its mean
        # falls short of a registered baseline that is a whole week's, whatever the arm did.
        if not window_is_open(player, context.exported_at):
            values[player.arm].append(metric.value(player))
    control = values[context.control]
    options = {
        "direction": guardrail.harmful_direction,
        "tolerance": guardrail.tolerance_relative,
    }
    baseline_options = {
        **options,
        "baseline": guardrail.baseline,
        "kind": guardrail.kind,
        "right_skewed": METRIC_FAMILIES.get(guardrail.name) == "revenue_like",
    }
    # The comparison group for control's own place against the baseline is the arms taken
    # together: what control would be drawn from had no arm differed.
    others = [
        value for name in context.arm_names if name != context.control for value in values[name]
    ]
    own = baseline_reference(control, group="control", against=others, **baseline_options)
    binary = guardrail.kind == "binary"
    tests = []
    for arm in context.arm_names:
        if arm == context.control:
            continue
        versus = control_reference(values[arm], control, arm_name=arm, **options)
        reading = baseline_reference(values[arm], group=arm, against=control, **baseline_options)
        tests.append(
            GuardrailTest(
                arm=arm,
                guardrail=guardrail.name,
                kind=guardrail.kind,
                harmful_direction=guardrail.harmful_direction,
                tolerance=guardrail.tolerance_relative,
                baseline=guardrail.baseline,
                n_arm=len(values[arm]),
                n_control=len(control),
                mean_arm=_mean(values[arm]),
                mean_control=_mean(control),
                events_arm=_events(values[arm]) if binary else None,
                events_control=_events(control) if binary else None,
                control=versus,
                baseline_reference=hold_for_a_moved_baseline(reading, versus, own),
                control_on_baseline=own,
            )
        )
    return tests
