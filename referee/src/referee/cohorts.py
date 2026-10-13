"""Which cohorts of first exposure the cohort test may use (design section 21.5 and 21.6).

A cohort is the analysed players of one arm whose first exposure falls in one block of days,
counted from the origin of the results context. This module only counts players and decides
which blocks are usable and how long a block is, and what traffic would let a plan pass; it never
looks at an outcome, so the choice cannot depend on the result. The test itself (the statistics
over the usable cohorts) is built on top of it.

The decisions are those of sections 21.5 and 21.6. Where those sections leave a detail open,
the choice made here is recorded there as well, and flagged as a judgement.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from typing import Literal

from referee.results import ExportMetric, ResultsContext

FLOOR = 30  # players per arm and cohort, never lowered (section 21.5)
PREFERRED_DIVISOR = 4  # the preferred minimum is a quarter of the planned share per block
KEEP_SHARE = 0.9  # the preferred minimum may drop at most 10% of the cohorts that reach the floor
MIN_COHORTS = 3
WEEKLY_MEDIAN_MINIMUM = 60  # median players of the smaller arm in a weekly block, to stay weekly
WEEK_DAYS = 7
FALLBACK_BLOCK_DAYS = 14
FALLBACK_MIN_PLAN_DAYS = 42
MAX_ALLOCATION_RATIO = 9.0  # beyond it the test is not evaluated
RATIO_FLOOR_KNEE = 1.5  # up to this ratio of the arms' sizes the floor stays at 30
RATIO_FLOOR_EXPONENT = 1.2

NotEvaluated = Literal[
    "window_holds_fewer_than_3_blocks",
    "fewer_than_3_cohorts_reach_minimum",
    "cohorts_do_not_cover_the_window",
    "cohorts_too_small_for_weekly_blocks",
    "allocation_too_unequal",
    "outcome_window_incomplete",
]
GateReason = Literal["unit_not_independent", "ratio_metric_not_validated"]
TrafficBlocker = Literal["plan_too_short", "arms_too_unequal", "empty_cohorts"]
BindingKind = Literal["floor", "preferred", "weekly_median"]

# `player` and `user` are one person; `device` is its own class. A session or a cluster holds
# several observations of one unit, so its players are not independent (section 21.6).
UNIT_CLASS = {"player": "person", "user": "person", "device": "device"}


@dataclass(frozen=True, kw_only=True)
class Minimum:
    """The smallest cohort of one arm that counts, and how it was reached.

    `registered` is the arm's required n from the power plan (None when the design cannot be
    sized), `achieved` the arm's analysed players, `preferred` the registered share of one
    block (never below the floor), and `used` the one that applies.
    """

    registered: int | None
    achieved: int
    preferred: int
    used: int


@dataclass(frozen=True, kw_only=True)
class Attempt:
    """One block length tried for one arm against control."""

    block_days: int
    window_blocks: int
    sizes: dict[int, dict[str, int]]
    usable: tuple[int, ...]
    usable_at_floor: tuple[int, ...]
    preferred_used: bool
    minimum_arm: Minimum
    minimum_control: Minimum
    median_smaller_arm: float
    covers_window: bool
    incomplete: tuple[int, ...]
    reason: NotEvaluated | None


@dataclass(frozen=True, kw_only=True)
class CohortPlan:
    """The cohorts RES-007 may use for one arm against control, or why it may not."""

    arm: str
    control: str
    block_days: int | None
    usable: tuple[int, ...]
    reason: NotEvaluated | None
    attempts: tuple[Attempt, ...]
    floor: int = FLOOR
    allocation_ratio: float | None = None
    as_of: datetime | None = None

    @property
    def evaluated(self) -> bool:
        return self.reason is None

    @property
    def completeness_checked(self) -> bool:
        """Whether an as-of time was known, so that unfinished outcome windows were looked for."""
        return self.as_of is not None


def cohort_sizes(context: ResultsContext, block_days: int) -> dict[int, dict[str, int]]:
    """Analysed players per block of first exposure and arm, in block order.

    Every arm of the spec appears in every block that holds anybody, with 0 where nobody is.
    """
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for player in context.analysed:
        counts[context.block_of(player.first_exposed_at, block_days)][player.arm] += 1
    return {
        block: {arm: found[arm] for arm in context.arm_names}
        for block, found in sorted(counts.items())
    }


def units_independent(context: ResultsContext) -> bool:
    """Whether the spec randomises and analyses one class of independent players.

    That is `player` and `user` (one person), or `device` for both. A session or a cluster
    holds several observations of one unit, and a mix of the two classes counts a unit once
    in one place and more than once in the other.
    """
    population = context.spec.population
    randomization = UNIT_CLASS.get(population.randomization_unit)
    analysis = UNIT_CLASS.get(population.analysis_unit)
    return randomization is not None and randomization == analysis


def cohort_gate(context: ResultsContext, metric: ExportMetric) -> GateReason | None:
    """Why the cohort test may not run on this spec and metric at all, or None.

    The units must be one class of independent players (`units_independent`), and the metric
    must not be a ratio, which the test was never validated for.
    """
    if not units_independent(context):
        return "unit_not_independent"
    if metric.kind == "ratio":
        return "ratio_metric_not_validated"
    return None


def allocation_ratio(context: ResultsContext, arm: str) -> float | None:
    """The larger over the smaller of the analysed players of `arm` and of control, or None
    when either has none."""
    analysed = context.count_by_arm(context.analysed)
    small, large = sorted((analysed[arm], analysed[context.control]))
    return None if small == 0 else large / small


def raised_floor(ratio: float) -> int:
    """The floor of players per arm and cohort when the arms differ in size by `ratio`.

    30 up to a ratio of 1.5, then ceil(30 * (ratio / 1.5) ** 1.2): about 43 at 2:1, 98 at 4:1
    and 258 at 9:1. A judgement fitted to the floors the studies found (section 21.6).
    """
    return math.ceil(FLOOR * max(1.0, (ratio / RATIO_FLOOR_KNEE) ** RATIO_FLOOR_EXPONENT))


def _minimum(
    context: ResultsContext, arm: str, block_days: int, achieved: int, floor: int
) -> Minimum:
    registered = context.required_n(arm)
    preferred = floor
    if registered is not None:
        planned_days = context.spec.design.planned_duration_days
        share = block_days * registered / (PREFERRED_DIVISOR * planned_days)
        preferred = max(floor, math.ceil(share))
    return Minimum(registered=registered, achieved=achieved, preferred=preferred, used=floor)


def _incomplete_blocks(
    context: ResultsContext, arm: str, block_days: int, as_of: datetime | None
) -> tuple[int, ...]:
    """Blocks in which some analysed player of the arm or of control has an outcome window
    that closes after `as_of`. Nothing is incomplete when no as-of time is known."""
    if as_of is None:
        return ()
    found: set[int] = set()
    for player in context.analysed:
        if player.arm in (arm, context.control) and player.window_closes_at > as_of:
            found.add(context.block_of(player.first_exposed_at, block_days))
    return tuple(sorted(found))


@dataclass(frozen=True, kw_only=True)
class _Selection:
    usable: tuple[int, ...]
    usable_at_floor: tuple[int, ...]
    preferred_used: bool
    minimum_arm: Minimum
    minimum_control: Minimum
    covers_window: bool


def _select(
    sizes: dict[int, dict[str, int]],
    arm: str,
    control: str,
    floor: int,
    minimum_arm: Minimum,
    minimum_control: Minimum,
    window_blocks: int,
    excluded: set[int],
) -> _Selection:
    """The usable blocks, leaving out `excluded`, and whether they reach both halves."""

    def reaching(need_arm: int, need_control: int) -> tuple[int, ...]:
        return tuple(
            block
            for block, found in sizes.items()
            if block not in excluded and found[arm] >= need_arm and found[control] >= need_control
        )

    at_floor = reaching(floor, floor)
    at_preferred = reaching(minimum_arm.preferred, minimum_control.preferred)
    keep_preferred = (
        (minimum_arm.preferred, minimum_control.preferred) != (floor, floor)
        and len(at_preferred) >= MIN_COHORTS
        and len(at_preferred) >= KEEP_SHARE * len(at_floor)
    )
    usable = at_preferred if keep_preferred else at_floor
    if keep_preferred:
        minimum_arm = replace(minimum_arm, used=minimum_arm.preferred)
        minimum_control = replace(minimum_control, used=minimum_control.preferred)
    half = window_blocks / 2
    return _Selection(
        usable=usable,
        usable_at_floor=at_floor,
        preferred_used=keep_preferred,
        minimum_arm=minimum_arm,
        minimum_control=minimum_control,
        covers_window=any(b < half for b in usable) and any(b >= half for b in usable),
    )


def _reason(
    selection: _Selection, window_blocks: int, block_days: int, median: float
) -> NotEvaluated | None:
    if window_blocks < MIN_COHORTS:
        return "window_holds_fewer_than_3_blocks"
    if len(selection.usable) < MIN_COHORTS:
        return "fewer_than_3_cohorts_reach_minimum"
    if not selection.covers_window:
        return "cohorts_do_not_cover_the_window"
    if block_days == WEEK_DAYS and median < WEEKLY_MEDIAN_MINIMUM:
        return "cohorts_too_small_for_weekly_blocks"
    return None


def _median_smaller(sizes: dict[int, dict[str, int]], arm: str, control: str, blocks: int):
    """The median over the blocks of the window of the smaller of the two arms' sizes (an
    empty block counts as 0). Exact for whatever numbers it is given, integers or fractions."""
    smaller = [
        min(sizes.get(b, {}).get(arm, 0), sizes.get(b, {}).get(control, 0)) for b in range(blocks)
    ]
    return statistics.median(smaller) if smaller else 0


def _attempt(
    context: ResultsContext, arm: str, block_days: int, floor: int, as_of: datetime | None
) -> Attempt:
    control = context.control
    sizes = cohort_sizes(context, block_days)
    window_blocks = context.spec.design.planned_duration_days // block_days
    analysed = context.count_by_arm(context.analysed)
    minimum_arm = _minimum(context, arm, block_days, analysed[arm], floor)
    minimum_control = _minimum(context, control, block_days, analysed[control], floor)
    incomplete = _incomplete_blocks(context, arm, block_days, as_of)

    def select(excluded: set[int]) -> _Selection:
        return _select(
            sizes, arm, control, floor, minimum_arm, minimum_control, window_blocks, excluded
        )

    median = float(_median_smaller(sizes, arm, control, window_blocks))
    chosen = select(set(incomplete))
    reason = _reason(chosen, window_blocks, block_days, median)
    if reason in ("fewer_than_3_cohorts_reach_minimum", "cohorts_do_not_cover_the_window"):
        # Only an unfinished window is to blame if the same sizes would have passed without it.
        if incomplete and _reason(select(set()), window_blocks, block_days, median) is None:
            reason = "outcome_window_incomplete"
    return Attempt(
        block_days=block_days,
        window_blocks=window_blocks,
        sizes=sizes,
        usable=chosen.usable,
        usable_at_floor=chosen.usable_at_floor,
        preferred_used=chosen.preferred_used,
        minimum_arm=chosen.minimum_arm,
        minimum_control=chosen.minimum_control,
        median_smaller_arm=median,
        covers_window=chosen.covers_window,
        incomplete=incomplete,
        reason=reason,
    )


def plan_cohorts(context: ResultsContext, arm: str, *, as_of: datetime | None = None) -> CohortPlan:
    """The block length and usable cohorts for `arm` against control, or why there are none.

    The arms must be within 9:1 in size, and the floor rises with the ratio (`raised_floor`).
    Where an as-of time is known (`as_of`, else the export's `exported_at`), a cohort with an
    outcome window that closes after it is left out and listed. Then weekly blocks when the
    weekly attempt passes; otherwise 14-day blocks, when the plan is at least 42 days and that
    attempt passes; otherwise the arm is not evaluated, with the reason of the weekly attempt.
    Both attempts are kept, so a finding can show what was tried.
    """
    known = as_of if as_of is not None else context.exported_at
    ratio = allocation_ratio(context, arm)
    floor = FLOOR if ratio is None else raised_floor(ratio)

    def plan(block_days, usable, reason, attempts) -> CohortPlan:
        return CohortPlan(
            arm=arm,
            control=context.control,
            block_days=block_days,
            usable=usable,
            reason=reason,
            attempts=tuple(attempts),
            floor=floor,
            allocation_ratio=ratio,
            as_of=known,
        )

    if ratio is not None and ratio > MAX_ALLOCATION_RATIO:
        return plan(None, (), "allocation_too_unequal", [])
    weekly = _attempt(context, arm, WEEK_DAYS, floor, known)
    attempts = [weekly]
    if weekly.reason is None:
        return plan(WEEK_DAYS, weekly.usable, None, attempts)
    if context.spec.design.planned_duration_days >= FALLBACK_MIN_PLAN_DAYS:
        fallback = _attempt(context, arm, FALLBACK_BLOCK_DAYS, floor, known)
        attempts.append(fallback)
        if fallback.reason is None:
            return plan(FALLBACK_BLOCK_DAYS, fallback.usable, None, attempts)
    return plan(None, (), weekly.reason, attempts)


# --- The traffic a test that could not run would need (design section 21.6) ---------------------


@dataclass(frozen=True, kw_only=True)
class Binding:
    """A size that reaches what a rule asks of it exactly at the traffic needed.

    `kind` says which rule asks: the floor, the preferred minimum, or the weekly median of 60.
    For the first two, `block` of the `block_days`-day cohorts has, on `side` ("arm" or
    "control"), `have` players where `need` are wanted. For the weekly median `block` is None,
    `side` is "smaller_arm" and `have` is the median over the weeks of the smaller arm's size.
    """

    kind: BindingKind
    block_days: int
    block: int | None
    side: Literal["arm", "control", "smaller_arm"]
    have: float
    need: int


@dataclass(frozen=True, kw_only=True)
class Price:
    """A multiple of the observed traffic that would let the cohort plan pass.

    `factor` is the least multiple, rounded up to a hundredth, from which the plan passes at
    every larger multiple; `block_days` is the block length the plan itself would use at that
    multiple (it may change at a larger one) and `binding` the sizes that reach what a rule asks
    of them exactly there. `first_pass` is the least multiple at which the plan passes at all
    when that is below `factor` (it fails at some multiple between), else None. A factor of 1.0
    for cohorts counted after their outcome windows close means only that the plan passes at the
    sizes observed; more traffic on top is not promised to keep it passing.
    """

    factor: float
    block_days: int
    binding: tuple[Binding, ...]
    first_pass: float | None = None


@dataclass(frozen=True, kw_only=True)
class TrafficAttempt:
    """One block length priced on its own.

    `reason` is why it failed as observed. `left_out` are the cohorts left out for an open
    outcome window. `now` is its price with them left out, `after_windows_close` its price once
    they are counted at the sizes observed (only when some were left out); None means that no
    multiple of the traffic would do.
    """

    block_days: int
    reason: NotEvaluated | None
    left_out: tuple[int, ...]
    now: float | None
    after_windows_close: float | None


@dataclass(frozen=True, kw_only=True)
class TrafficNeeded:
    """How much more traffic would let the cohort plan pass, worked out from the sizes observed.

    The prices are for the plan, which passes with weekly blocks or else with 14-day ones.
    `now` leaves out the cohorts whose outcome windows had not closed; `after_windows_close`
    counts them at the sizes observed (None when none was left out, or when no multiple of the
    traffic would do even so; each attempt's `left_out` says which), and 1.0 there means that
    exporting again later is enough. Counting them at the sizes observed is what exporting again
    would give if no player arrives in them meanwhile, as at the planned end; on an interim
    look the cohorts still filling, and those not yet begun, will hold more. `now` is None when
    no multiple would do with them left out. When not even counting them helps, or more traffic
    is not the remedy, `blocker` says why. `attempts` give each block length on its own.
    """

    now: Price | None
    after_windows_close: Price | None
    blocker: TrafficBlocker | None
    attempts: tuple[TrafficAttempt, ...]

    @property
    def waiting_suffices(self) -> bool:
        return self.after_windows_close is not None and self.after_windows_close.factor == 1.0


# Reasons for which more of the same traffic is not the remedy: the plan is too short for 3
# blocks, or the arms are more than 9 to 1 apart (section 21.6).
_NOT_A_MATTER_OF_TRAFFIC: dict[str, TrafficBlocker] = {
    "window_holds_fewer_than_3_blocks": "plan_too_short",
    "allocation_too_unequal": "arms_too_unequal",
}


def _runs(attempt: Attempt, plan: CohortPlan, factor: Fraction) -> bool:
    """Whether the attempt would pass with every observed size multiplied by `factor`.

    It applies the rules of the plan itself (`_select` and `_reason`) to exact fractions of the
    observed sizes, leaving out the same cohorts whose outcome windows were open.
    """
    sizes = {
        block: {name: factor * count for name, count in found.items()}
        for block, found in attempt.sizes.items()
    }
    selection = _select(
        sizes,
        plan.arm,
        plan.control,
        plan.floor,
        attempt.minimum_arm,
        attempt.minimum_control,
        attempt.window_blocks,
        set(attempt.incomplete),
    )
    # The weekly median is only judged for weekly blocks (`_reason`).
    median = (
        _median_smaller(sizes, plan.arm, plan.control, attempt.window_blocks)
        if attempt.block_days == WEEK_DAYS
        else 0
    )
    return _reason(selection, attempt.window_blocks, attempt.block_days, median) is None


def _breakpoints(attempt: Attempt, plan: CohortPlan) -> list[tuple[Fraction, Binding]]:
    """The factors at which some size first reaches what a rule asks of it.

    Every decision of the plan is a comparison of a size with a number, so the outcome can
    change only at one of these factors. A cohort with no player in one of the arms never
    reaches anything, and a cohort that was left out stays out. When both arms reach their
    minimum at the same factor, both are named.
    """
    found: list[tuple[Fraction, Binding]] = []
    needs = [("floor", plan.floor, plan.floor)]
    preferred = (attempt.minimum_arm.preferred, attempt.minimum_control.preferred)
    if preferred != (plan.floor, plan.floor):
        needs.append(("preferred", *preferred))
    for block, sizes in attempt.sizes.items():
        have_arm, have_control = sizes[plan.arm], sizes[plan.control]
        if block in attempt.incomplete or not have_arm or not have_control:
            continue
        for kind, need_arm, need_control in needs:
            by_arm, by_control = Fraction(need_arm, have_arm), Fraction(need_control, have_control)
            for side, by, have, need in (
                ("arm", by_arm, have_arm, need_arm),
                ("control", by_control, have_control, need_control),
            ):
                if by >= max(by_arm, by_control):
                    binding = Binding(
                        kind=kind,
                        block_days=attempt.block_days,
                        block=block,
                        side=side,
                        have=have,
                        need=need,
                    )
                    found.append((by, binding))
    if attempt.block_days == WEEK_DAYS:
        median = _median_smaller(attempt.sizes, plan.arm, plan.control, attempt.window_blocks)
        if median > 0:
            binding = Binding(
                kind="weekly_median",
                block_days=attempt.block_days,
                block=None,
                side="smaller_arm",
                have=median,
                need=WEEKLY_MEDIAN_MINIMUM,
            )
            found.append((Fraction(WEEKLY_MEDIAN_MINIMUM) / Fraction(median), binding))
    return found


def _least(
    attempts: Sequence[Attempt], plan: CohortPlan
) -> tuple[Fraction, tuple[Binding, ...]] | None:
    """The least factor from which the plan passes at every larger factor, with what binds.

    The plan passes at a factor when any of the attempts does (it tries weekly blocks, then
    14-day ones). If the plan passes at the observed sizes the answer is 1, whatever it does at
    a larger factor. None when no factor helps: the cohorts that would have to grow are empty.
    The outcome is constant between two
    neighbouring breakpoints, so it is judged at each breakpoint, from the largest down; the
    answer is the first breakpoint after the last at which the plan fails. (Judging the cohorts
    again as they grow can drop one that did not reach the preferred minimum, so passing at one
    factor does not always mean passing at every larger one.)
    """
    found = [(attempt, _breakpoints(attempt, plan)) for attempt in attempts]
    values = _values(found)

    def passes(factor: Fraction) -> bool:
        return any(_runs(attempt, plan, factor) for attempt in attempts)

    if passes(values[0]):
        return Fraction(1), ()
    if not passes(values[-1]):
        return None
    last = next(i for i in reversed(range(len(values))) if not passes(values[i]))
    least = values[last + 1]
    named = [
        binding
        for attempt, points in found
        if _runs(attempt, plan, least)
        for at, binding in points
        if at == least
    ]
    # A preferred minimum that equals the floor is the same size asked for twice: name it once.
    floors = {replace(b, kind="preferred") for b in named if b.kind == "floor"}
    return least, tuple(b for b in named if b not in floors)


def _values(found: Sequence[tuple[Attempt, list[tuple[Fraction, Binding]]]]) -> list[Fraction]:
    """The factors to judge: the observed traffic and every breakpoint above it, ascending."""
    return sorted({Fraction(1)} | {at for _, points in found for at, _ in points if at >= 1})


def _first_pass(attempts: Sequence[Attempt], plan: CohortPlan) -> Fraction | None:
    """The least breakpoint at which the plan passes, or None when it passes at none."""
    values = _values([(attempt, _breakpoints(attempt, plan)) for attempt in attempts])
    return next((v for v in values if any(_runs(a, plan, v) for a in attempts)), None)


def _price(
    attempts: Sequence[Attempt],
    plan: CohortPlan,
    least: tuple[Fraction, tuple[Binding, ...]] | None,
) -> Price | None:
    if least is None:
        return None
    factor, binding = least
    rounded = Fraction(math.ceil(factor * 100), 100)
    chosen = next(attempt for attempt in attempts if _runs(attempt, plan, rounded))
    earlier = _first_pass(attempts, plan)
    first = None
    if earlier is not None and earlier < factor:
        # Rounded up like the price, and only named if the plan passes there.
        up = Fraction(math.ceil(earlier * 100), 100)
        if up < rounded and any(_runs(attempt, plan, up) for attempt in attempts):
            first = float(up)
    return Price(
        factor=float(rounded), block_days=chosen.block_days, binding=binding, first_pass=first
    )


def _counted(attempt: Attempt) -> Attempt:
    """The attempt with the cohorts left out for an open outcome window counted again."""
    return replace(attempt, incomplete=())


def traffic_needed(plan: CohortPlan) -> TrafficNeeded | None:
    """How much more traffic would let `plan` pass, or None when it already does.

    The price is for the plan: the least multiple of every observed cohort of both arms from
    which the plan's own rules pass for weekly or else 14-day blocks (`_least`), rounded up to
    a hundredth. Where cohorts were left out because their outcome windows had not closed, it
    is worked out twice: as exported, and with them counted at the sizes observed, which is the
    price once the export is made again if no player arrives in them meanwhile (1.0 when
    waiting alone is enough). A plan that failed because its window holds fewer than 3 blocks,
    or because the arms are more than 9 to 1 apart, has no price (`blocker`): more of the same
    traffic does not mend it. Nor has a plan whose cohorts that would have to grow are empty,
    even when the cohorts left out are counted, because scaling what was observed cannot fill
    them.
    """
    if plan.evaluated:
        return None
    blocker = _NOT_A_MATTER_OF_TRAFFIC.get(plan.reason or "")
    if blocker is not None:
        return TrafficNeeded(now=None, after_windows_close=None, blocker=blocker, attempts=())
    attempts = list(plan.attempts)
    now = _price(attempts, plan, _least(attempts, plan))
    counted = [_counted(attempt) for attempt in attempts]
    left_out = any(attempt.incomplete for attempt in attempts)
    after = _price(counted, plan, _least(counted, plan)) if left_out else None
    rows = []
    for attempt, again in zip(attempts, counted, strict=True):
        alone = _price([attempt], plan, _least([attempt], plan))
        later = _price([again], plan, _least([again], plan)) if attempt.incomplete else None
        rows.append(
            TrafficAttempt(
                block_days=attempt.block_days,
                reason=attempt.reason,
                left_out=attempt.incomplete,
                now=None if alone is None else alone.factor,
                after_windows_close=None if later is None else later.factor,
            )
        )
    return TrafficNeeded(
        now=now,
        after_windows_close=after,
        blocker="empty_cohorts" if now is None and after is None else None,
        attempts=tuple(rows),
    )
