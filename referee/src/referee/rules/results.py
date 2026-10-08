"""Rules about what the data of a finished experiment shows (RES).

The data-fit rules of design section 21.4 arrive here one at a time; the effect rules follow
in the next change. A rule reads a `ResultsContext` and returns the evidence that triggered it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from referee.methods import SRM_ALPHA, srm_test
from referee.results import ResultsContext
from referee.rules.base import Rule
from referee.rules.references import FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020

_CHI_SQUARE_DIGITS = 4
_EXPECTED_DIGITS = 2


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
)
