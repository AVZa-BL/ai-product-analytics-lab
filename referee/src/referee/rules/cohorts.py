"""The check behind RES-007: does an arm's effect differ between cohorts of first exposure?

`cohort_report` runs the cohort test (design sections 21.5 to 21.7) for every non-control arm
and every metric the spec names, and returns what a finding or a report needs: the cohort plan
of each arm, one entry per arm and metric with its status, a summary, the settings used, and the
sentences a reader should get. The rule raises a finding from it when something is flagged or
could not be evaluated; the report of milestone 4c prints its summary line even when the rule
is quiet.

The wording follows section 21.7: it says that the effect differs between cohorts, not why; it
never reads a result that was not flagged as proof of no change; and it says what the test could
have seen. Nothing here names a cause.
"""

from __future__ import annotations

from typing import Any

from referee.cohort_effects import (
    NULL_FLAG_RATE_MAX,
    NULL_FLAG_RATE_MEAN,
    POWER,
    TRIGGER_LEVEL,
    CohortTest,
    ScaleTest,
    cohort_test,
    control_baseline,
    detectable_shifts,
    low_information,
    min_expected_events,
    registered_mde,
    trigger,
)
from referee.cohorts import Attempt, CohortPlan, Minimum, cohort_gate, plan_cohorts
from referee.methods import CohortShape
from referee.results import ExportMetric, ResultsContext

_DIGITS = 6


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, _DIGITS)


def _minimum(found: Minimum) -> dict[str, Any]:
    return {
        "registered": found.registered,
        "achieved": found.achieved,
        "preferred": found.preferred,
        "used": found.used,
    }


def _attempt(attempt: Attempt, arm: str, control: str) -> dict[str, Any]:
    return {
        "block_days": attempt.block_days,
        "window_blocks": attempt.window_blocks,
        "sizes": [
            {"block": block, "arm": found[arm], "control": found[control]}
            for block, found in attempt.sizes.items()
        ],
        "usable": list(attempt.usable),
        "usable_at_floor": list(attempt.usable_at_floor),
        "preferred_used": attempt.preferred_used,
        "minimum_arm": _minimum(attempt.minimum_arm),
        "minimum_control": _minimum(attempt.minimum_control),
        "median_smaller_arm": attempt.median_smaller_arm,
        "covers_window": attempt.covers_window,
        "incomplete": list(attempt.incomplete),
        "reason": attempt.reason,
    }


def _plan(plan: CohortPlan) -> dict[str, Any]:
    return {
        "block_days": plan.block_days,
        "usable": list(plan.usable),
        "reason": plan.reason,
        "floor": plan.floor,
        "allocation_ratio": _round(plan.allocation_ratio),
        "as_of": None if plan.as_of is None else plan.as_of.isoformat(),
        "completeness_checked": plan.completeness_checked,
        "attempts": [_attempt(a, plan.arm, plan.control) for a in plan.attempts],
    }


def _scale(scale: ScaleTest) -> dict[str, Any]:
    found = scale.heterogeneity
    return {
        "reason": scale.reason,
        "error": scale.error,
        "cohorts": [
            {
                "block": c.block,
                "n_arm": c.n_arm,
                "n_control": c.n_control,
                "mean_arm": _round(c.mean_arm),
                "mean_control": _round(c.mean_control),
                "estimate": _round(c.estimate),
                "std_error": _round(c.std_error),
                "corrected_std_error": _round(c.corrected_std_error),
            }
            for c in scale.cohorts
        ],
        "dropped": [{"block": block, "reason": reason} for block, reason in scale.dropped],
        "q": None
        if found is None
        else {
            "statistic": _round(found.q_statistic),
            "degrees_of_freedom": found.degrees_of_freedom,
            "p_value": found.q_p_value,
            "i_squared": _round(found.i_squared),
        },
        "slope": None
        if found is None
        else {
            "value": _round(found.slope),
            "std_error": _round(found.slope_std_error),
            "p_value": found.slope_p_value,
        },
    }


def _shifts(scale: ScaleTest, level: float) -> dict[CohortShape, float]:
    found = detectable_shifts(scale, level)
    if found is None:
        raise ValueError(
            f"the {scale.scale} scale was not evaluated, so it has no detectable shift"
        )
    return found


def _share(shift: float, mean: float) -> float | None:
    return _round(shift / mean) if mean > 0 else None


def _entry(
    context: ResultsContext, plan: CohortPlan, metric: ExportMetric, arms: int
) -> dict[str, Any]:
    base: dict[str, Any] = {"arm": plan.arm, "metric": metric.name, "kind": metric.kind}
    gate = cohort_gate(context, metric)
    if gate is not None:
        return {**base, "status": "not_evaluated", "reason": gate}
    if not plan.evaluated:
        return {**base, "status": "not_evaluated", "reason": plan.reason}

    test: CohortTest = cohort_test(context, plan, metric)
    decision = trigger(test, arms)
    entry = {
        **base,
        "block_days": plan.block_days,
        "scales": {"absolute": _scale(test.absolute), "log_ratio": _scale(test.log_ratio)},
        "trigger": {
            "level": decision.level,
            "absolute": decision.absolute,
            "log_ratio": decision.log_ratio,
        },
    }
    missing = [scale for scale in test.scales if scale.reason is not None]
    if missing:
        return {
            **entry,
            "status": "not_evaluated",
            "reason": missing[0].reason,
            "scales_not_evaluated": [scale.scale for scale in missing],
        }

    baseline = control_baseline(context, plan, metric)
    absolute = _shifts(test.absolute, decision.level)
    relative = _shifts(test.log_ratio, decision.level)
    mean = baseline.pooled_mean
    labels = low_information(
        shift=absolute["linear_fade"],
        control_mean=mean,
        registered_mde=registered_mde(context, metric),
        expected_events=min_expected_events(test.absolute) if metric.kind == "binary" else None,
    )
    return {
        **entry,
        "status": "flagged" if decision.flagged else "not_flagged",
        "detectable": {
            "power": POWER,
            "control_mean": _round(mean),
            "absolute": {
                shape: {"shift": _round(shift), "share_of_control_mean": _share(shift, mean)}
                for shape, shift in absolute.items()
            },
            "log_ratio": {shape: _round(shift) for shape, shift in relative.items()},
        },
        "control_baseline": {
            "cohorts": [
                {
                    "block": c.block,
                    "n": c.n,
                    "mean": _round(c.mean),
                    "ci_low": _round(c.ci_low),
                    "ci_high": _round(c.ci_high),
                }
                for c in baseline.cohorts
            ],
            "homogeneity_p": baseline.homogeneity_p,
            "moves": baseline.moves,
        },
        "low_information": list(labels),
    }


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of the entries by status, and the one line the report always prints."""
    flagged = sum(e["status"] == "flagged" for e in entries)
    not_evaluated = sum(e["status"] == "not_evaluated" for e in entries)
    low = sum(bool(e.get("low_information")) for e in entries)
    ran = len(entries) - not_evaluated
    line = (
        f"RES-007: {len(entries)} tests, {flagged} flagged, "
        f"{not_evaluated} not evaluated, {low} low information"
    )
    return {
        "tests": len(entries),
        "evaluated": ran,
        "flagged": flagged,
        "not_evaluated": not_evaluated,
        "low_information": low,
        "flags_by_chance": _round(ran * NULL_FLAG_RATE_MEAN),
        "flags_by_chance_at_most": _round(ran * NULL_FLAG_RATE_MAX),
        "line": line,
    }


def _settings(context: ResultsContext, arms: int) -> dict[str, Any]:
    planned = context.spec.design.planned_duration_days
    return {
        "trigger_level": TRIGGER_LEVEL,
        "non_control_arms": arms,
        "level_per_statistic": TRIGGER_LEVEL / arms,
        "power": POWER,
        "planned_duration_days": planned,
        "observed_days": context.observed_days,
        "interim": context.observed_days < planned,
    }


def _amount(found: dict[str, Any]) -> str:
    text = f"{found['shift']:.3g}"
    share = found["share_of_control_mean"]
    return text if share is None else f"{text} ({100 * share:.0f}% of the control mean)"


def _population_note(context: ResultsContext) -> str:
    kind = context.spec.population.kind
    unchecked = (
        "Referee cannot check this declaration, because the export has no column for how long "
        "a player has existed."
    )
    if kind is None:
        return "population.kind is not declared, so the kind of players is unknown."
    if kind == "existing_users":
        return (
            "population.kind is existing_users: players who see a change first can be the most "
            "active, so the earliest cohorts may differ from the later ones for that reason "
            f"alone. {unchecked}"
        )
    return f"population.kind is declared as {kind}. {unchecked}"


def _entry_note(entry: dict[str, Any]) -> str:
    label = f"arm {entry['arm']}, metric {entry['metric']}"
    if entry["status"] == "not_evaluated":
        where = entry.get("scales_not_evaluated")
        scales = f" on the {' and '.join(where)} scale" if where else ""
        return f"{label}: not evaluated{scales} ({entry['reason']})."
    labels = entry["low_information"]
    if entry["status"] == "flagged":
        sentence = f"{label}: the effect differs between cohorts of first exposure."
        if labels:
            sentence += (
                f" The test has low information here ({', '.join(labels)}): treat the flag as "
                "a lead to re-check, not as a finding."
            )
        return sentence
    fade = _amount(entry["detectable"]["absolute"]["linear_fade"])
    step = _amount(entry["detectable"]["absolute"]["step"])
    sentence = (
        f"{label}: not flagged. With 80% probability the test would have flagged a linear fade "
        f"(a difference between the arm and control of {fade} in the first cohort that falls "
        f"in a straight line to nothing in the last) or a step (a difference of {step} in the "
        "first half of the cohorts and nothing in the second), in the metric's units, and it "
        "could have missed anything smaller. The figure is a little optimistic, because the "
        "trigger needs the log-ratio scale too. A result that is not flagged does not show "
        "that the effect is the same in every cohort."
    )
    if entry["trigger"]["absolute"] != entry["trigger"]["log_ratio"]:
        shown = "absolute" if entry["trigger"]["absolute"] else "log-ratio"
        sentence += (
            f" The {shown} scale alone shows a difference between cohorts; an arm is flagged "
            "only when both do, because a baseline that moves can make either scale show one."
        )
    if labels:
        sentence += f" The test has low information here ({', '.join(labels)})."
    return sentence


def _notes(
    context: ResultsContext,
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    settings: dict[str, Any],
    plans: dict[str, CohortPlan],
    configuration: dict[str, Any] | None,
) -> list[str]:
    notes = [
        "The test says that the effect differs between cohorts of first exposure, not why. A "
        "change tied to the calendar week of a cohort (a launch, a promotion, a build, the mix "
        "of players acquired) cannot be told from one tied to each player's own time since "
        "first exposure, because the export holds seven-day totals only.",
        _population_note(context),
    ]
    if settings["interim"]:
        notes.append(
            f"The assignments span {settings['observed_days']} days of the "
            f"{settings['planned_duration_days']} planned, so this is an interim look. The test "
            "belongs at the planned end: run repeatedly on accumulating data, it flagged 11% "
            "to 13% of experiments with no change (design section 21.6)."
        )
    ran_arms = {entry["arm"] for entry in entries if "scales" in entry}
    if any(not plans[arm].completeness_checked for arm in ran_arms):
        notes.append(
            "No as-of time was known, so cohorts whose outcome windows had not closed were not "
            "looked for."
        )
    notes.extend(_entry_note(entry) for entry in entries)
    for entry in entries:
        baseline = entry.get("control_baseline")
        if baseline is not None and baseline["moves"]:
            notes.append(
                f"arm {entry['arm']}, metric {entry['metric']}: the control's mean differs "
                f"between the cohorts compared (p = {baseline['homogeneity_p']:.3g})."
            )
    if any(e.get("control_baseline", {}).get("moves") for e in entries):
        notes.append(
            "A control baseline that changes can raise Cochran's Q on a scale that is not "
            "invariant to it, which is why an arm is flagged only when both scales show a "
            "difference between cohorts."
        )
    if configuration is not None:
        for arm, changed in configuration["arms"].items():
            weeks = ", ".join(str(week) for week in changed["mixed_weeks"]) or "none"
            notes.append(
                f"RES-013: the configuration of arm {arm} changed during the test (weeks of "
                f"first exposure holding more than one version: {weeks}). The version change "
                "falls in the same weeks as the cohorts compared, so a difference between "
                "cohorts may be the change itself."
            )
    ran = summary["evaluated"]
    if ran:
        mean, worst = 100 * NULL_FLAG_RATE_MEAN, 100 * NULL_FLAG_RATE_MAX
        notes.append(
            f"{ran} {'test' if ran == 1 else 'tests'} ran. In the simulations of design section "
            f"21.5 (two arms, no change over time) the trigger flagged {mean:.1f}% of tests on "
            f"average and at most {worst:.1f}%, so about {summary['flags_by_chance']:.2g} flags "
            f"(at most {summary['flags_by_chance_at_most']:.2g}) would be expected by chance alone."
        )
    return notes


def cohort_report(context: ResultsContext, configuration: dict[str, Any] | None) -> dict[str, Any]:
    """The cohort test for every non-control arm and metric of the spec, with its sentences.

    `configuration` is the evidence of RES-013 (None if that rule is quiet), so that the notes
    can say where a version change falls in the same weeks as the cohorts.
    """
    arms = [name for name in context.arm_names if name != context.control]
    plans = {arm: plan_cohorts(context, arm) for arm in arms}
    entries = [
        _entry(context, plans[arm], metric, len(arms))
        for metric in context.metrics.values()
        for arm in arms
    ]
    summary = summarise(entries)
    settings = _settings(context, len(arms))
    return {
        "summary": summary,
        "settings": settings,
        "plans": {arm: _plan(plan) for arm, plan in plans.items()},
        "tests": entries,
        "notes": _notes(context, entries, summary, settings, plans, configuration),
    }
