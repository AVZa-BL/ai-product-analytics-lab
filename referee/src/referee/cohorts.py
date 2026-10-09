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
from typing import Literal

from referee.results import ResultsContext

FLOOR = 30  # players per arm and cohort, never lowered (section 21.5)
PREFERRED_DIVISOR = 4  # the preferred minimum is a quarter of the planned share per block
KEEP_SHARE = 0.9  # the preferred minimum may drop at most 10% of the cohorts that reach the floor
MIN_COHORTS = 3
WEEKLY_MEDIAN_MINIMUM = 60  # median players of the smaller arm in a weekly block, to stay weekly
WEEK_DAYS = 7
FALLBACK_BLOCK_DAYS = 14
FALLBACK_MIN_PLAN_DAYS = 42

NotEvaluated = Literal[
    "window_holds_fewer_than_3_blocks",
    "fewer_than_3_cohorts_reach_minimum",
    "cohorts_do_not_cover_the_window",
    "cohorts_too_small_for_weekly_blocks",
]


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

    @property
    def evaluated(self) -> bool:
        return self.reason is None


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


def _minimum(context: ResultsContext, arm: str, block_days: int, achieved: int) -> Minimum:
    registered = context.required_n(arm)
    preferred = FLOOR
    if registered is not None:
        planned_days = context.spec.design.planned_duration_days
        share = block_days * registered / (PREFERRED_DIVISOR * planned_days)
        preferred = max(FLOOR, math.ceil(share))
    return Minimum(registered=registered, achieved=achieved, preferred=preferred, used=FLOOR)


def _attempt(context: ResultsContext, arm: str, block_days: int) -> Attempt:
    control = context.control
    sizes = cohort_sizes(context, block_days)
    planned_days = context.spec.design.planned_duration_days
    window_blocks = planned_days // block_days
    analysed = context.count_by_arm(context.analysed)

    minimum_arm = _minimum(context, arm, block_days, analysed[arm])
    minimum_control = _minimum(context, control, block_days, analysed[control])

    def reaching(need_arm: int, need_control: int) -> tuple[int, ...]:
        return tuple(
            block
            for block, found in sizes.items()
            if found[arm] >= need_arm and found[control] >= need_control
        )

    at_floor = reaching(FLOOR, FLOOR)
    at_preferred = reaching(minimum_arm.preferred, minimum_control.preferred)
    keep_preferred = (
        (minimum_arm.preferred, minimum_control.preferred) != (FLOOR, FLOOR)
        and len(at_preferred) >= MIN_COHORTS
        and len(at_preferred) >= KEEP_SHARE * len(at_floor)
    )
    usable = at_preferred if keep_preferred else at_floor
    if keep_preferred:
        minimum_arm = replace(minimum_arm, used=minimum_arm.preferred)
        minimum_control = replace(minimum_control, used=minimum_control.preferred)

    smaller = [
        min(sizes.get(b, {}).get(arm, 0), sizes.get(b, {}).get(control, 0))
        for b in range(window_blocks)
    ]
    median = float(statistics.median(smaller)) if smaller else 0.0
    half = window_blocks / 2
    covers = any(b < half for b in usable) and any(b >= half for b in usable)

    reason: NotEvaluated | None = None
    if window_blocks < MIN_COHORTS:
        reason = "window_holds_fewer_than_3_blocks"
    elif len(usable) < MIN_COHORTS:
        reason = "fewer_than_3_cohorts_reach_minimum"
    elif not covers:
        reason = "cohorts_do_not_cover_the_window"
    elif block_days == WEEK_DAYS and median < WEEKLY_MEDIAN_MINIMUM:
        reason = "cohorts_too_small_for_weekly_blocks"
    return Attempt(
        block_days=block_days,
        window_blocks=window_blocks,
        sizes=sizes,
        usable=usable,
        usable_at_floor=at_floor,
        preferred_used=keep_preferred,
        minimum_arm=minimum_arm,
        minimum_control=minimum_control,
        median_smaller_arm=median,
        covers_window=covers,
        reason=reason,
    )


def plan_cohorts(context: ResultsContext, arm: str) -> CohortPlan:
    """The block length and usable cohorts for `arm` against control, or why there are none.

    Weekly blocks when the weekly attempt passes. Otherwise 14-day blocks, when the plan is at
    least 42 days and that attempt passes; otherwise the arm is not evaluated, with the reason
    of the weekly attempt. Both attempts are kept, so a finding can show what was tried.
    """
    weekly = _attempt(context, arm, WEEK_DAYS)
    attempts = [weekly]
    if weekly.reason is None:
        return CohortPlan(
            arm=arm,
            control=context.control,
            block_days=WEEK_DAYS,
            usable=weekly.usable,
            reason=None,
            attempts=tuple(attempts),
        )
    if context.spec.design.planned_duration_days >= FALLBACK_MIN_PLAN_DAYS:
        fallback = _attempt(context, arm, FALLBACK_BLOCK_DAYS)
        attempts.append(fallback)
        if fallback.reason is None:
            return CohortPlan(
                arm=arm,
                control=context.control,
                block_days=FALLBACK_BLOCK_DAYS,
                usable=fallback.usable,
                reason=None,
                attempts=tuple(attempts),
            )
    return CohortPlan(
        arm=arm,
        control=context.control,
        block_days=None,
        usable=(),
        reason=weekly.reason,
        attempts=tuple(attempts),
    )
