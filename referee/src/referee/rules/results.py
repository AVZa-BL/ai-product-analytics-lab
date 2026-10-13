"""Rules about what the data of a finished experiment shows (RES).

The data-fit rules of design section 21.4 are here, with the effect rules RES-007 and RES-008;
RES-004 follows in milestone 4b-2. A rule reads a `ResultsContext` and returns the evidence that
triggered it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from referee.methods import (
    SMALL_EXPECTED_COUNT,
    SRM_ALPHA,
    SrmResult,
    StatsError,
    homogeneity_test,
    srm_test,
)
from referee.pooled_rates import EXCESS_RATE, NOMINAL_RATE, UNIT, percent
from referee.results import ResultsContext, difference_summary, effect_estimates
from referee.rules.base import Escalation, Rule
from referee.rules.cohorts import cohort_report
from referee.rules.heavy_tails import heavy_tail_report
from referee.rules.references import (
    COCHRAN_1954,
    FABIJAN_ET_AL_2019,
    HIGGINS_THOMPSON_2002,
    KOHAVI_ET_AL_2014,
    KOHAVI_TANG_XU_2020,
)

LATE_SHARE_ALPHA = 0.001  # RES-012's escalation; its own judgement, not SRM_ALPHA (section 21.9)
_SHARE_DIGITS = 4
_CHI_SQUARE_DIGITS = 4
_EXPECTED_DIGITS = 2


def _allocation(context: ResultsContext) -> list[float]:
    return [arm.allocation for arm in context.spec.arms]


def _sample_ratio(context: ResultsContext, counts: list[int]) -> SrmResult:
    """The sample-ratio test of counts in the spec's arm order: exact where they are small."""
    return srm_test(counts, _allocation(context), exact_below=SMALL_EXPECTED_COUNT)


def _total_sample_ratio(context: ResultsContext) -> tuple[dict[str, int], SrmResult]:
    """The assigned players per arm, and the sample-ratio test over all of them."""
    assigned = context.count_by_arm(context.players)
    return assigned, _sample_ratio(context, [assigned[arm] for arm in context.arm_names])


def _weekly_sample_ratios(context: ResultsContext) -> list[dict[str, Any]]:
    """The same test for each 7-day week of assignment that holds players, in week order."""
    arms = context.arm_names
    by_week: dict[int, Counter[str]] = defaultdict(Counter)
    for player in context.players:
        by_week[context.week_of(player.assigned_at)][player.arm] += 1
    weeks = []
    for week, counts in sorted(by_week.items()):
        result = _sample_ratio(context, [counts[arm] for arm in arms])
        weeks.append(
            {
                "week": week,
                "assigned": {arm: counts[arm] for arm in arms},
                "p_value": result.p_value,
                "method": result.method,
            }
        )
    return weeks


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
        "method": total.method,
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
        "total": {"assigned": assigned, "p_value": total.p_value, "method": total.method},
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
    homogeneity: dict[str, Any]
    try:
        result = homogeneity_test(
            [late[a] for a in tested],
            [exposed[a] for a in tested],
            exact_below=SMALL_EXPECTED_COUNT,
        )
        homogeneity = {
            "chi_square": round(result.chi_square, _CHI_SQUARE_DIGITS),
            "degrees_of_freedom": result.degrees_of_freedom,
            "p_value": result.p_value,
            "alpha": LATE_SHARE_ALPHA,
            "method": result.method,
            "smallest_expected": round(result.smallest_expected, _EXPECTED_DIGITS),
        }
    except StatsError as error:
        # one arm exposed, or everyone or no one late: there is nothing to compare
        homogeneity = {"error": str(error)}

    with_late = effect_estimates(context, exposed_players)
    without_late = effect_estimates(context, context.analysed)
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
                    "with_late_exposed": with_late[arm],
                    "without_late_exposed": without_late[arm],
                }
                for arm in with_late
            },
        },
    }


def _late_share_differs(evidence: dict[str, Any]) -> bool:
    homogeneity = evidence.get("homogeneity")
    return (
        homogeneity is not None
        and "p_value" in homogeneity
        and homogeneity["p_value"] < homogeneity["alpha"]
    )


def _versions(players: list) -> list[dict[str, int]]:
    counts = Counter(p.version for p in players)
    return [{"version": version, "players": counts[version]} for version in sorted(counts)]


def _configuration_changed(context: ResultsContext) -> dict[str, Any] | None:
    """An arm whose analysed players first saw it on more than one configuration version."""
    metric = context.metrics[context.spec.primary_metric.name]
    changed: dict[str, Any] = {}
    analysed_by_arm: dict[str, list] = {arm: [] for arm in context.arm_names}
    for player in context.analysed:
        analysed_by_arm[player.arm].append(player)
    for arm in context.arm_names:
        players = analysed_by_arm[arm]
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
    design = context.spec.design
    observed_days = context.observed_days
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


def _effect_differs_between_cohorts(context: ResultsContext) -> dict[str, Any] | None:
    """The cohort test of design sections 21.5 to 21.7, when anything is flagged or not run."""
    report = cohort_report(context, _configuration_changed(context))
    summary = report["summary"]
    if not (summary["flagged"] or summary["not_evaluated"]):
        return None
    return report


def _heavy_tailed_metric(context: ResultsContext) -> dict[str, Any] | None:
    """The signs of a heavy tail (design section 21.11), when any arm and metric shows one."""
    report = heavy_tail_report(context)
    if not report["summary"]["tripped"]:
        return None
    return report


def _simulated_rate_is_high(evidence: dict[str, Any]) -> bool:
    """The largest simulated rate for the effects nearer the difference seen (both ranges, when
    it cannot be told which are nearer) is above `EXCESS_RATE`, or a comparison lies beyond the
    simulated cases in a direction in which the rates rose."""
    summary = evidence.get("summary", {})
    largest = summary.get("largest_simulated_rate")
    return (largest is not None and largest > EXCESS_RATE / UNIT) or bool(
        summary.get("floor_ranges")
    )


RESULTS_RULES: tuple[Rule[ResultsContext], ...] = (
    Rule(
        id="RES-001",
        severity="blocker",
        title="Sample ratio mismatch: the arms are not the size the allocation promised",
        fires_when=(
            "The assigned players per arm differ from arms[].allocation by more than chance "
            "allows: the chi-squared test of the counts against the registered allocation "
            "(the exact multinomial test when an expected count is below 100), over every "
            "assigned player at or after design.start_utc (all of them when the spec "
            "registers none), has p below 0.001."
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
            "effect exists. A design that cannot be sized has no registered sample size at "
            "all, so no amount of data meets it."
        ),
        remediation=(
            "Keep the experiment running until every arm reaches its registered n (when the "
            "evidence gives sizes, it says how many are missing). If it must stop, report the "
            "result as underpowered, with the interval of the effect, and not as evidence of no "
            "effect. Do not lower the registered n after seeing the data. If the evidence says "
            "the design is unattainable, the spec's baseline and mde_relative cannot be turned "
            "into a sample size (the evidence gives the reason): more data will not clear this, "
            "so correct them and register the experiment again."
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
            "(rounded up), is shorter than design.min_duration_days. Every assigned player at "
            "or after design.start_utc counts, exposed or not (all of them when the spec "
            "registers none)."
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
            "was wrong, say so and why before reading the effect. Register design.start_utc: "
            "without it the first and last assignment in the export set the duration, and one "
            "mistimed row (a timestamp of zero, a default date) can hide this finding."
        ),
        references=(KOHAVI_TANG_XU_2020,),
        check=_shorter_than_the_registered_minimum,
    ),
    Rule(
        id="RES-007",
        severity="warning",
        title="The effect differs between cohorts of first exposure, or the test could not run",
        fires_when=(
            "For a non-control arm and one of the metrics of the spec (the primary metric or a "
            "guardrail), the arm's difference against control is compared between cohorts: the "
            "analysed players of the arm whose first exposure falls in one 7-day block (one "
            "14-day block when the weekly cohorts are too small and the plan is at least 42 "
            "days), counted from design.start_utc, else from the first assignment. The arm and "
            "metric are flagged when, on both the absolute scale (the Welch difference) and the "
            "relative scale (the log of the ratio of the means), Cochran's Q or the weighted "
            "slope of the difference over the blocks has p below 0.025 divided by the number "
            "of non-control arms. The rule fires when any arm and metric is flagged, or could "
            "not be evaluated: the evidence then gives a reason code (fewer than 3 cohorts "
            "reach the minimum size, the cohorts do not cover the window, the arms differ by "
            "more than 9 to 1, an outcome window had not closed at the export, the units are "
            "not independent players, or the metric is a ratio)."
        ),
        why_it_matters=(
            "The pooled effect is an average over players who were first exposed at different "
            "times. If the effect differs between those cohorts, the pooled figure describes "
            "none of them well, and what a later launch sees can differ from it. The test says "
            "that the effect differs, not why: a change tied to the calendar week of a cohort "
            "(a launch, a promotion, a build, the mix of players acquired) cannot be told from "
            "one tied to each player's own time since first exposure, because the export "
            "holds seven-day totals only. A test that could not run is reported too, so that a "
            "missing check cannot read as a pass."
        ),
        remediation=(
            "Read the table of cohorts in the evidence before the pooled effect: each cohort's "
            "difference and its standard error on both scales. Find out what differed between "
            "the weeks of the cohorts (a launch, a promotion, a build, a change in where "
            "players come from; RES-013 shows a change of configuration), and report the "
            "pooled effect together with the cohort table, naming no cause the data cannot "
            "show. For existing players, check whether the earliest cohorts are the most "
            "active. A flag labelled low information is a lead to re-check with more data at "
            "the planned end, not a finding. If the test did not run, the reason code says what "
            "was missing: more traffic or a longer run, arms closer in size, an export made "
            "after every outcome window has closed, or randomisation and analysis in the same "
            "independent unit (player, user or device). The evidence prices the traffic that "
            "would let the cohorts be used, from the sizes observed (plans, traffic_needed), says "
            "when to export again if the outcome windows of some cohorts had not closed, or "
            "says why more traffic would not help."
        ),
        references=(COCHRAN_1954, HIGGINS_THOMPSON_2002, KOHAVI_TANG_XU_2020),
        check=_effect_differs_between_cohorts,
    ),
    Rule(
        id="RES-008",
        severity="info",
        title=(
            "Skewed or heavy-tailed metric: its 95% interval can be wrong more or less often "
            "than 5% of the time"
        ),
        fires_when=(
            "For a non-control arm and a metric of the spec that is not binary (the primary "
            "metric or a guardrail), the analysed players of the arm and of control are "
            "compared, and at least one of three signs shows in either group: the rule of "
            "thumb of Kohavi, Deng, Longbotham and Xu (2014), a sample skewness above 1 in size "
            "in a group of fewer players than 355 times the square of that skewness; an excess "
            "kurtosis above 100; or the top 1% of the group's players (at least one) holding "
            "more than half of the total of the metric. Every split between the arms is read, "
            "equal arms included. The skewness, kurtosis and share are rounded to 6 places and "
            "the decision is made on the rounded figures that the evidence shows. A group that "
            "cannot be read (fewer than 2 players, every value 0 or the same, a negative value, "
            "values that are not finite or are too large or too small to measure) is reported "
            "with its reason and the pair is judged on the other group; a pair with no sign "
            "and a group that could not be read is reported as not evaluated and does not "
            "fire the rule on its own."
        ),
        why_it_matters=(
            "Welch's interval for a difference of means, the one Referee prints, assumes that "
            "the mean of each arm is nearly normal. For a metric that most players leave at "
            "zero and a few drive up, that takes more players than an experiment often has "
            "(by the rule of thumb of Kohavi et al., revenue per user, with a skewness of about "
            "18, needs about 114,000 users), and below that size the interval is wrong more or "
            "less often than the 5% it states. Referee measured how often for a revenue-like "
            "metric of independent players in two arms (design section 21.10), and the "
            "finding quotes the simulated cases on each side of the comparison: with equal "
            "arms the interval "
            "was mostly close to or under 5% for a small effect and above it for a large one; "
            "with arms of unequal size it was often above 5%, for a small effect mostly on the "
            "side that makes the larger arm look better than it is, and it was worst when the "
            "control was the larger arm (the arm there being the group with the higher mean); "
            "and at 9 to 1 with no effect it was worse the fewer "
            "the players who spend in the smaller arm. These rates come from one simulated "
            "family and are not a measure of the experiment in hand. A quiet RES-008 is not "
            "evidence that the interval is reliable: in the simulations every run of a "
            "revenue-like metric showed a sign. For a metric that is not revenue-like the "
            "finding gives the signs and says that no error rate was measured."
        ),
        remediation=(
            "Where an entry gives a simulated rate, read it in place of 5%: an interval that "
            "failed in 10% of simulated experiments behaved like a 90% interval, and for a "
            "small effect and arms of unequal size it mostly favoured the larger group. Where "
            "an entry states no error rate (a metric that is not revenue-like, units that are "
            "not independent players, a group with no analysed players, or no player who "
            "spends in the smaller group), treat its "
            "interval as unchecked: the signs show that it may be unreliable, but Referee has "
            "not measured how much. Do not call the result "
            "significant, or not, on one edge of this interval: if an end of it is close to "
            "zero or to a decision threshold, say that the result is uncertain. Where you can "
            "choose, do not make the control the larger arm, which was the worst case in the "
            "simulations (where the arm has the higher mean; for a metric you expect to fall, "
            "avoid the larger arm instead), and plan for more players who spend in the "
            "smaller arm. For a "
            "decision that rests on this metric, consider a less skewed version of it (a cap "
            "on the amount per player, or a transformation): Kohavi et al. report that capping "
            "revenue per user cut its skewness from about 18 to about 5. It changes what is "
            "estimated, and Referee has not measured how well capping, trimming or a "
            "transformation works, so register the choice before the next test and not after "
            "seeing the data. Referee shows no bootstrap interval, because in its simulations "
            "the percentile bootstrap interval failed more often than Welch's in most of the "
            "cells it was run on."
        ),
        references=(KOHAVI_ET_AL_2014, KOHAVI_TANG_XU_2020),
        check=_heavy_tailed_metric,
        escalation=Escalation(
            to="warning",
            when=(
                "the simulated range for the effects nearer the difference seen (both ranges, "
                "when the means cannot be compared) reaches above "
                f"{percent(EXCESS_RATE)}, which is {EXCESS_RATE / NOMINAL_RATE:g} times the "
                f"{percent(NOMINAL_RATE)[:-3]}% an interval of this level should fail in, or "
                "that comparison lies beyond the simulated cases in a direction in which the "
                "simulated rates rose, so that the true rate is probably above the range "
                "printed."
            ),
            applies=_simulated_rate_is_high,
        ),
    ),
    Rule(
        id="RES-011",
        severity="warning",
        title="Sample ratio drifts over time although the total passes",
        fires_when=(
            "The sample-ratio check over all assigned players passes (RES-001 does not fire), "
            "but in at least one 7-day week of assignment (weeks are counted from "
            "design.start_utc, else from the first assignment) the chi-squared test of that "
            "week's counts against arms[].allocation (the exact multinomial test when an "
            "expected count is below 100) has p below 0.001 divided by the number of weeks "
            "that hold players."
        ),
        why_it_matters=(
            "A mismatch that reverses partway through can cancel in the total, and one that "
            "begins or ends partway is diluted in it. A failing week points to a change in "
            "assignment or logging during the test (a release, a campaign, an outage, a planned "
            "ramp-up of the allocation), so the players of that week may not be comparable with "
            "the others."
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
            "a different share of the exposed players being late in different arms means the "
            "change reached the arms differently. It is the results-time counterpart of DES-007."
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
                "the chi-squared test of homogeneity across the arms (the exact test when an "
                "expected count is below 100) has p below 0.001."
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
