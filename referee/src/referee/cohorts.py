"""Which cohorts of first exposure the cohort test may use (design section 21.5 and 21.6).

A cohort is the analysed players of one arm whose first exposure falls in one block of days,
counted from the origin of the results context. This module only counts players and decides
which blocks are usable and how long a block is; it never looks at an outcome, so the choice
cannot depend on the result. The test itself (the statistics over the usable cohorts) is built
on top of it.

The decisions are those of section 21.5. Where that section leaves a detail open, the choice
made here is recorded in section 21.5 as well, and flagged as a judgement.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
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


def cohort_gate(context: ResultsContext, metric: ExportMetric) -> GateReason | None:
    """Why the cohort test may not run on this spec and metric at all, or None.

    The units must be one class of independent players (`player` and `user`, or `device` for
    both), and the metric must not be a ratio, which the test was never validated for.
    """
    population = context.spec.population
    randomization = UNIT_CLASS.get(population.randomization_unit)
    analysis = UNIT_CLASS.get(population.analysis_unit)
    if randomization is None or analysis is None or randomization != analysis:
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

    smaller = [
        min(sizes.get(b, {}).get(arm, 0), sizes.get(b, {}).get(control, 0))
        for b in range(window_blocks)
    ]
    median = float(statistics.median(smaller)) if smaller else 0.0
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
