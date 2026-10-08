"""Rules about what the data of a finished experiment shows (RES).

The data-fit rules of design section 21.4 arrive here one at a time; the effect rules follow
in the next change. A rule reads a `ResultsContext` and returns the evidence that triggered it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from referee.methods import SRM_ALPHA, srm_test
from referee.results import ResultsContext
from referee.rules.base import Rule
from referee.rules.references import FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020

_CHI_SQUARE_DIGITS = 4
_EXPECTED_DIGITS = 2
_DAY = timedelta(days=1)


def _sample_ratio_mismatch(context: ResultsContext) -> dict[str, Any] | None:
    """The sample-ratio check of design section 9, on every assigned player (section 21.4)."""
    arms = context.arm_names
    allocation = [arm.allocation for arm in context.spec.arms]
    assigned = context.count_by_arm(context.players)
    total = srm_test([assigned[arm] for arm in arms], allocation)
    if not total.flagged:
        return None

    by_week: dict[int, Counter[str]] = defaultdict(Counter)
    for player in context.players:
        by_week[context.week_of(player.assigned_at)][player.arm] += 1
    weekly = [
        {
            "week": week,
            "assigned": {arm: counts[arm] for arm in arms},
            "p_value": srm_test([counts[arm] for arm in arms], allocation).p_value,
        }
        for week, counts in sorted(by_week.items())
    ]
    return {
        "alpha": SRM_ALPHA,
        "allocation": dict(zip(arms, allocation, strict=True)),
        "assigned": assigned,
        "expected": {
            arm: round(expected, _EXPECTED_DIGITS)
            for arm, expected in zip(arms, total.expected, strict=True)
        },
        "chi_square": round(total.chi_square, _CHI_SQUARE_DIGITS),
        "degrees_of_freedom": total.degrees_of_freedom,
        "p_value": total.p_value,
        "by_week": weekly,
    }


def _fewer_players_than_registered(context: ResultsContext) -> dict[str, Any] | None:
    """An arm of the effect analysis is smaller than the n the power plan requires of it."""
    analysed = context.count_by_arm(context.analysed)
    if context.plan is None:
        return {"unattainable": True, "reason": context.power_error, "analysed": analysed}
    required = {arm: context.required_n(arm) for arm in context.arm_names}
    short = [arm for arm in context.arm_names if analysed[arm] < (required[arm] or 0)]
    if not short:
        return None
    return {
        "required": required,
        "analysed": analysed,
        "assigned": context.count_by_arm(context.players),
        "short_arms": short,
        "missing": {arm: (required[arm] or 0) - analysed[arm] for arm in short},
    }


def _shorter_than_the_registered_minimum(context: ResultsContext) -> dict[str, Any] | None:
    """The assignments span fewer whole days than design.min_duration_days."""
    first = min(player.assigned_at for player in context.players)
    last = max(player.assigned_at for player in context.players)
    observed_days = math.ceil((last - first) / _DAY)
    design = context.spec.design
    if observed_days >= design.min_duration_days:
        return None
    return {
        "observed_days": observed_days,
        "min_duration_days": design.min_duration_days,
        "planned_duration_days": design.planned_duration_days,
        "first_assignment": first.isoformat(),
        "last_assignment": last.isoformat(),
        "ignored_before_start": list(context.ignored_before_start),
    }


RESULTS_RULES: tuple[Rule[ResultsContext], ...] = (
    Rule(
        id="RES-001",
        severity="blocker",
        title="Sample ratio mismatch: the arms are not the size the allocation promised",
        fires_when=(
            "The assigned players per arm differ from arms[].allocation by more than chance "
            "allows: the chi-squared test of the counts against the registered allocation, "
            "over every assigned player, has p below 0.001."
        ),
        why_it_matters=(
            "Random assignment gives arms of the registered sizes, up to chance. A mismatch this "
            "large means the arms were not formed as designed (a fault in assignment, in "
            "logging or in filtering), so who is in each arm may differ and a difference in the "
            "metrics can come from that. No estimate of the effect can be trusted until the "
            "cause is known."
        ),
        remediation=(
            "Do not read the effect. Find why the counts differ: assignment or bucketing, "
            "logging that loses events in one arm, bot or test-account filters, a crash or "
            "redirect on one variant, or an exposure rule applied to some arms only. The "
            "week-by-week table in the evidence shows whether the mismatch began at a point in "
            "time. Fix the cause and rerun the experiment."
        ),
        references=(FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020),
        check=_sample_ratio_mismatch,
    ),
    Rule(
        id="RES-002",
        severity="blocker",
        title="Fewer players than the registered sample size",
        fires_when=(
            "In the effect analysis (assigned, exposed, and not first exposed after the first "
            "purchase), at least one arm has fewer players than the n per arm that the power "
            "plan of the spec requires for it, or the design cannot be sized at all."
        ),
        why_it_matters=(
            "The registered sample size is what the experiment needs to detect the registered "
            "effect with the registered power. With fewer players the test has less power than "
            "was promised, so a result that is not significant says little about whether the "
            "effect exists."
        ),
        remediation=(
            "Keep the experiment running until every arm reaches its registered n (the "
            "evidence says how many are missing). If it must stop, report the result as "
            "underpowered, with the interval of the effect, and not as evidence of no effect. "
            "Do not lower the registered n after seeing the data."
        ),
        references=(KOHAVI_TANG_XU_2020,),
        check=_fewer_players_than_registered,
    ),
    Rule(
        id="RES-003",
        severity="blocker",
        title="Ran for less than the registered minimum duration",
        fires_when=(
            "The observed duration, from the first to the last assignment in whole days "
            "(rounded up), is shorter than design.min_duration_days."
        ),
        why_it_matters=(
            "The minimum duration is registered so that the run covers the weekly cycle of "
            "behaviour and gives effects that take time to settle a chance to show. A shorter "
            "run measures a window that may not represent the usual weeks, and cannot show a "
            "change over time."
        ),
        remediation=(
            "Run to at least design.min_duration_days, and to a whole number of weeks where "
            "you can. Do not stop on the day the result looked good. If the registered minimum "
            "was wrong, say so and why before reading the effect."
        ),
        references=(KOHAVI_TANG_XU_2020,),
        check=_shorter_than_the_registered_minimum,
    ),
)
