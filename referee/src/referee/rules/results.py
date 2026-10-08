"""Rules about what the data of a finished experiment shows (RES).

The data-fit rules of design section 21.4 arrive here one at a time; the effect rules follow
in the next change. A rule reads a `ResultsContext` and returns the evidence that triggered it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from referee.methods import SRM_ALPHA, SrmResult, StatsError, homogeneity_test, srm_test
from referee.results import ResultsContext, difference_summary, effect_estimate
from referee.rules.base import Escalation, Rule
from referee.rules.references import FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020

_SHARE_DIGITS = 4
_CHI_SQUARE_DIGITS = 4
_EXPECTED_DIGITS = 2
_DAY = timedelta(days=1)


def _allocation(context: ResultsContext) -> list[float]:
    return [arm.allocation for arm in context.spec.arms]


def _total_sample_ratio(context: ResultsContext) -> tuple[dict[str, int], SrmResult]:
    """The assigned players per arm, and the sample-ratio test over all of them."""
    assigned = context.count_by_arm(context.players)
    total = srm_test([assigned[arm] for arm in context.arm_names], _allocation(context))
    return assigned, total


def _weekly_sample_ratios(context: ResultsContext) -> list[dict[str, Any]]:
    """The same test for each 7-day week of assignment that holds players, in week order."""
    arms = context.arm_names
    by_week: dict[int, Counter[str]] = defaultdict(Counter)
    for player in context.players:
        by_week[context.week_of(player.assigned_at)][player.arm] += 1
    return [
        {
            "week": week,
            "assigned": {arm: counts[arm] for arm in arms},
            "p_value": srm_test([counts[arm] for arm in arms], _allocation(context)).p_value,
        }
        for week, counts in sorted(by_week.items())
    ]


def _sample_ratio_mismatch(context: ResultsContext) -> dict[str, Any] | None:
    """The sample-ratio check of design section 9, on every assigned player (section 21.4)."""
    arms = context.arm_names
    allocation = _allocation(context)
    assigned, total = _total_sample_ratio(context)
    if not total.flagged:
        return None
    weekly = _weekly_sample_ratios(context)
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


def _sample_ratio_drift(context: ResultsContext) -> dict[str, Any] | None:
    """The total passes, but a week of assignment fails at 0.001 over the number of weeks."""
    assigned, total = _total_sample_ratio(context)
    if total.flagged:
        return None  # RES-001 reports it, with the same week-by-week table
    weekly = _weekly_sample_ratios(context)
    threshold = SRM_ALPHA / len(weekly)
    failing = [week["week"] for week in weekly if week["p_value"] < threshold]
    if not failing:
        return None
    return {
        "alpha_per_week": threshold,
        "weeks_tested": len(weekly),
        "failing_weeks": failing,
        "by_week": [{**week, "flagged": week["p_value"] < threshold} for week in weekly],
        "total": {"assigned": assigned, "p_value": total.p_value},
        "allocation": dict(zip(context.arm_names, _allocation(context), strict=True)),
    }


def _late_exposure(context: ResultsContext) -> dict[str, Any] | None:
    """Players first exposed after their first purchase: how many, where, and what they change."""
    arms = context.arm_names
    exposed_players = [p for p in context.players if p.exposed]
    late_players = [p for p in context.players if p.late_exposed]  # late implies exposed
    if not late_players:
        return None
    late = context.count_by_arm(late_players)
    exposed = context.count_by_arm(exposed_players)
    purchasers = sum(p.first_purchase_at is not None for p in context.players)

    tested = [arm for arm in arms if exposed[arm] > 0]
    homogeneity = None
    try:
        result = homogeneity_test([late[a] for a in tested], [exposed[a] for a in tested])
        homogeneity = {
            "chi_square": round(result.chi_square, _CHI_SQUARE_DIGITS),
            "degrees_of_freedom": result.degrees_of_freedom,
            "p_value": result.p_value,
            "alpha": SRM_ALPHA,
        }
    except StatsError:
        pass  # one arm exposed, or everyone or no one late: there is nothing to compare

    analysed = context.analysed
    return {
        "late": late,
        "exposed": exposed,
        "late_share_of_exposed": {
            arm: round(late[arm] / exposed[arm], _SHARE_DIGITS) if exposed[arm] else None
            for arm in arms
        },
        "late_total": len(late_players),
        "share_of_assigned": round(len(late_players) / len(context.players), _SHARE_DIGITS),
        "share_of_purchasers": round(len(late_players) / purchasers, _SHARE_DIGITS),
        "homogeneity": homogeneity,
        "estimate": {
            "metric": context.spec.primary_metric.name,
            "by_arm": {
                arm: {
                    "with_late_exposed": effect_estimate(context, arm, exposed_players),
                    "without_late_exposed": effect_estimate(context, arm, analysed),
                }
                for arm in arms
                if arm != context.control
            },
        },
    }


def _late_share_differs(evidence: dict[str, Any]) -> bool:
    homogeneity = evidence.get("homogeneity")
    return homogeneity is not None and homogeneity["p_value"] < homogeneity["alpha"]


def _versions(players: list) -> list[dict[str, int]]:
    counts = Counter(p.version for p in players)
    return [{"version": version, "players": counts[version]} for version in sorted(counts)]


def _configuration_changed(context: ResultsContext) -> dict[str, Any] | None:
    """An arm whose analysed players first saw it on more than one configuration version."""
    metric = context.metrics[context.spec.primary_metric.name]
    changed: dict[str, Any] = {}
    for arm in context.arm_names:
        players = [p for p in context.analysed if p.arm == arm]
        if len({p.version for p in players}) < 2:
            continue
        by_week: dict[int, list] = defaultdict(list)
        for player in players:
            by_week[context.week_of(player.first_exposed_at)].append(player)
        mixed = [
            week for week, found in sorted(by_week.items()) if len({p.version for p in found}) > 1
        ]
        within_week = []
        for week in mixed:
            groups: dict[int, list[float]] = defaultdict(list)
            for player in by_week[week]:
                groups[player.version].append(metric.value(player))
            earlier = min(groups)
            for later in sorted(v for v in groups if v > earlier):
                summary = difference_summary(metric, groups[later], groups[earlier])
                within_week.append(
                    {
                        "week": week,
                        "later_version": later,
                        "earlier_version": earlier,
                        "n_later": summary.pop("n_treatment"),
                        "n_earlier": summary.pop("n_control"),
                        **summary,
                    }
                )
        changed[arm] = {
            "versions": _versions(players),
            "by_week": [
                {"week": week, "versions": _versions(found)}
                for week, found in sorted(by_week.items())
            ],
            "mixed_weeks": mixed,
            "assigned_differs": sum(
                p.first_exposure_version is not None
                and p.first_exposure_version != p.assigned_version
                for p in players
            ),
            "within_week": within_week,
        }
    if not changed:
        return None
    analysed = context.analysed
    known = sum(p.first_exposure_version is not None for p in analysed)
    return {
        "metric": context.spec.primary_metric.name,
        "version_from": {"exposure": known, "assignment": len(analysed) - known},
        "arms": changed,
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
    Rule(
        id="RES-011",
        severity="warning",
        title="Sample ratio drifts over time although the total passes",
        fires_when=(
            "The sample-ratio check over all assigned players passes (RES-001 does not fire), "
            "but in at least one 7-day week of assignment the chi-squared test of that week's "
            "counts against arms[].allocation has p below 0.001 divided by the number of weeks "
            "that hold players."
        ),
        why_it_matters=(
            "A mismatch that begins, ends or reverses partway through can cancel in the total. "
            "It means assignment or logging changed during the test (a release, a campaign, an "
            "outage), so the players of the failing weeks are not comparable with the others."
        ),
        remediation=(
            "Find what changed in the failing weeks: a release, a change to assignment or "
            "logging, a new traffic source, an outage. Decide what to do with those weeks from "
            "the cause, never because leaving them out changes the result."
        ),
        references=(FABIJAN_ET_AL_2019, KOHAVI_TANG_XU_2020),
        check=_sample_ratio_drift,
    ),
    Rule(
        id="RES-012",
        severity="warning",
        title="Players first exposed after their first purchase",
        fires_when=(
            "At least one assigned player was first exposed after their first purchase in the "
            "seven-day outcome window."
        ),
        why_it_matters=(
            "A purchase made before the player first saw the change cannot be an effect of it. "
            "These players are left out of the effect analysis, but they are in the arms, so "
            "a different number of them in different arms means the change reached the arms "
            "differently. It is the results-time counterpart of DES-007."
        ),
        remediation=(
            "Check how exposure is triggered. If it can follow a purchase, say so in the "
            "design and analyse from first exposure. Compare the estimates with and without "
            "these players in the evidence, and say which one the conclusion rests on. If the "
            "late share differs between arms, find out why before reading the effect."
        ),
        references=(KOHAVI_TANG_XU_2020,),
        check=_late_exposure,
        escalation=Escalation(
            to="blocker",
            when=(
                "the share of exposed players who were exposed late differs between the arms: "
                "the chi-squared test of homogeneity across the arms has p below 0.001."
            ),
            applies=_late_share_differs,
        ),
    ),
    Rule(
        id="RES-013",
        severity="warning",
        title="An arm's configuration changed during the test",
        fires_when=(
            "Among the players of the effect analysis, at least one arm has players who first "
            "saw it on different arm_config_version values: the version at first exposure, or "
            "at assignment when the exposures carry none."
        ),
        why_it_matters=(
            "A change of configuration part-way through is a second treatment inside the arm. "
            "Players before and after it saw different things, so the arm's effect is an average "
            "of two experiences, and a change of that effect over time (RES-007) cannot be told "
            "from the effect of the change itself."
        ),
        remediation=(
            "Find out what changed and when. Analyse the versions separately or restart the test "
            "on the final configuration; do not pool the versions and read a trend over weeks as "
            "novelty. The difference within a week in the evidence is descriptive only: the "
            "versions were not randomised."
        ),
        references=(KOHAVI_TANG_XU_2020,),
        check=_configuration_changed,
    ),
)
