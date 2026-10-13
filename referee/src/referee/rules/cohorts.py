"""The check behind RES-007: does an arm's effect differ between cohorts of first exposure?

`cohort_report` runs the cohort test (design sections 21.5 to 21.7) for every non-control arm
and every metric the spec names, and returns what a finding or a report needs: the cohort plan
of each arm (with the traffic that would let it pass, or when to export again, when it could
not), one entry per arm and metric with its status, a summary, the settings used, and the
sentences a reader should get. The rule raises a finding from it when something is flagged or
could not be evaluated; the report of milestone 4c prints its summary line even when the rule
is quiet.

The wording follows section 21.7: it says that the effect differs between cohorts, not why; it
never reads a result that was not flagged as proof of no change; and it says what the test could
have seen. Nothing here names a cause.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from referee.cohort_effects import (
    FADE_COHORTS,
    FADE_FAMILIES,
    FADE_FLAG_RATES,
    FADE_FLAG_RATES_ADDED,
    FADE_MAX_ALLOCATION_RATIO,
    FADE_SIZES,
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
from referee.cohorts import (
    FLOOR,
    Attempt,
    Binding,
    CohortPlan,
    Minimum,
    Price,
    TrafficAttempt,
    TrafficNeeded,
    cohort_gate,
    plan_cohorts,
    traffic_needed,
)
from referee.methods import CohortShape
from referee.pooled_rates import UNIT, percent
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


def _binding(binding: Binding) -> dict[str, Any]:
    return {
        "kind": binding.kind,
        "block_days": binding.block_days,
        "block": binding.block,
        "side": binding.side,
        "have": binding.have,
        "need": binding.need,
    }


def _price_evidence(price: Price | None) -> dict[str, Any] | None:
    if price is None:
        return None
    return {
        "factor": price.factor,
        "block_days": price.block_days,
        "binding": [_binding(b) for b in price.binding],
        "first_pass": price.first_pass,
    }


def _traffic_attempt(attempt: TrafficAttempt) -> dict[str, Any]:
    return {
        "block_days": attempt.block_days,
        "reason": attempt.reason,
        "left_out": list(attempt.left_out),
        "now": attempt.now,
        "after_windows_close": attempt.after_windows_close,
    }


def _traffic(found: TrafficNeeded | None, closes: datetime | None) -> dict[str, Any] | None:
    if found is None:
        return None
    return {
        "windows_close_at": None if closes is None else closes.isoformat(),
        "now": _price_evidence(found.now),
        "after_windows_close": _price_evidence(found.after_windows_close),
        "waiting_suffices": found.waiting_suffices,
        "blocker": found.blocker,
        "attempts": [_traffic_attempt(a) for a in found.attempts],
    }


def _plan(
    plan: CohortPlan, traffic: TrafficNeeded | None, closes: datetime | None
) -> dict[str, Any]:
    return {
        "block_days": plan.block_days,
        "usable": list(plan.usable),
        "reason": plan.reason,
        "floor": plan.floor,
        "allocation_ratio": _round(plan.allocation_ratio),
        "as_of": None if plan.as_of is None else plan.as_of.isoformat(),
        "completeness_checked": plan.completeness_checked,
        "attempts": [_attempt(a, plan.arm, plan.control) for a in plan.attempts],
        "traffic_needed": _traffic(traffic, closes),
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


def _design(test: CohortTest, plan: CohortPlan, arms: int) -> dict[str, Any]:
    """What the simulations of the fade were indexed by, as this test has it: the number of
    non-control arms, the cohorts the absolute scale used, the median over them of the players
    in the smaller arm, and how unequal the arms are overall."""
    sizes = [min(c.n_arm, c.n_control) for c in test.absolute.cohorts]
    return {
        "non_control_arms": arms,
        "cohorts": len(sizes),
        "players_an_arm_median": statistics.median(sizes) if sizes else None,
        "allocation_ratio": _round(plan.allocation_ratio),
    }


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
        "design": _design(test, plan, arms),
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


def _thousands(number: float) -> str:
    """A count with thousands separators: whole numbers as they are, a half to one decimal."""
    return f"{number:,.0f}" if number == int(number) else f"{number:,.1f}"


def _pct(rate: float) -> str:
    return percent(round(rate * UNIT))


def _span(low: float, high: float) -> str:
    return f"{_pct(low)} to {_pct(high)}"


def _nearest_size(players: float) -> int:
    """The simulated number of players an arm in a cohort nearest to `players`, in log scale."""
    return min(FADE_SIZES, key=lambda size: abs(math.log(players / size)))


def _outside_simulations(entry: dict[str, Any]) -> list[str]:
    """How this test differs from the cohort design the fade was simulated for, if it does."""
    design, reasons = entry["design"], []
    if design["non_control_arms"] > 1:
        reasons.append(f"{design['non_control_arms']} arms against control")
    ratio = design["allocation_ratio"]
    if ratio is not None and ratio > FADE_MAX_ALLOCATION_RATIO:
        rounded_up = math.ceil(round(ratio * 100, 6)) / 100
        reasons.append(f"arms that differ in size by about {_times(rounded_up)} to 1")
    if not FADE_COHORTS[0] <= design["cohorts"] <= FADE_COHORTS[-1]:
        reasons.append(f"{design['cohorts']} cohorts")
    players = design["players_an_arm_median"]
    if players is None or not FADE_SIZES[0] <= players <= FADE_SIZES[-1]:
        reasons.append(f"cohorts of about {_thousands(players or 0)} players an arm")
    if entry["control_baseline"]["moves"]:
        reasons.append("a control baseline that moves between the cohorts")
    return reasons


_FADE_KINDS = {
    "revenue_like": "revenue-like metrics",
    "binary": "a binary metric at a rate of 10%",
    "poisson": "counts simulated as Poisson",
}
_FADE_ASSUMES = (
    "That figure takes the standard errors as known and the effect as leaving the spread of the "
    "arm unchanged."
)
_FADE_STEP = "The step was not simulated, and the test could have missed anything smaller."


def _overall_span(family: str) -> tuple[float, float]:
    """The lowest and the highest share of runs over the cohort sizes simulated."""
    rates = FADE_FLAG_RATES[family].values()
    return min(low for low, _ in rates), max(high for _, high in rates)


def _shares(families: tuple[str, ...], rates_of) -> str:
    """The share of runs for each kind of metric, in a clause: "in 36.3% to 38.3% of runs for a
    binary metric at a rate of 10% and in 71.9% to 74.5% of runs for counts simulated as
    Poisson"."""
    return " and ".join(
        f"in {_span(*rates_of(family))} of runs for {_FADE_KINDS[family]}" for family in families
    )


def _fade_rates(entry: dict[str, Any]) -> str:
    """What share of runs flagged a fade of the size a finding prints, in Referee's simulations
    (design section 21.5), for the kind of metric, if the test is inside what was simulated."""
    families = FADE_FAMILIES.get(entry["metric"])
    if families is None:
        return (
            f"{_FADE_ASSUMES} Referee did not simulate this kind of metric, so it does not know "
            f"what share of runs would flag a fade of this size. {_FADE_STEP}"
        )
    reasons = _outside_simulations(entry)
    if reasons:
        return (
            f"{_FADE_ASSUMES} Referee simulated the trigger only for two arms of the same size "
            f"(a test within {_times(FADE_MAX_ALLOCATION_RATIO)} to 1 counts as the same here), a "
            f"control baseline that does not move, {FADE_COHORTS[0]} or {FADE_COHORTS[-1]} "
            f"cohorts and {_join_or([f'{size:,}' for size in FADE_SIZES])} players an arm in a "
            "cohort (a count or a size between those counts as inside here). "
            f"This test has {_join(reasons)}, so what share of runs would flag a fade of this "
            "size is not known here; in the cases simulated the trigger flagged a fade of this "
            f"size {_shares(families, _overall_span)}. {_FADE_STEP}"
        )
    players = entry["design"]["players_an_arm_median"]
    size = _nearest_size(players)
    text = (
        f"{_FADE_ASSUMES} In Referee's simulations (design section 21.5: two arms of the same "
        f"size, a control baseline that does not move, {FADE_COHORTS[0]} and "
        f"{FADE_COHORTS[-1]} cohorts, with {size:,} players an arm in a cohort, the nearest "
        f"size to this test's; a count or a size between those simulated counts as inside "
        f"here, and this test has {entry['design']['cohorts']} cohorts and about "
        f"{_thousands(players)} players an arm) the trigger, which needs the log-ratio scale "
        "as well, "
        "flagged a fade of exactly this size "
        f"{_shares(families, lambda family: FADE_FLAG_RATES[family][size])}: "
        "below the 80% in every case simulated."
    )
    if "revenue_like" in families:
        added = FADE_FLAG_RATES_ADDED["revenue_like"][size]
        text += (
            " The effect in those simulations multiplied what the players who spend spend; "
            f"when the same amount was added to every player the rate was {_span(*added)}."
        )
    return f"{text} {_FADE_STEP}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _join_or(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


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
        f"{label}: not flagged. The usual power calculation puts at 80% the chance that the "
        f"test would have flagged a linear fade (a difference between the arm and control of "
        f"{fade} in the first cohort that falls in a straight line to nothing in the last) or "
        f"a step (a difference of {step} in the first half of the cohorts and nothing in the "
        f"second), in the metric's units. {_fade_rates(entry)} A result that is not flagged "
        "does not show that the effect is the same in every cohort."
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


_BLOCKERS = {
    "plan_too_short": (
        "More traffic would not help: the planned window holds fewer than 3 whole blocks. A "
        "plan of at least 21 days holds 3 weekly blocks."
    ),
    "arms_too_unequal": (
        "More traffic in the same proportions would not help: the two arms differ in size by "
        "more than 9 to 1, and the smaller arm would have to grow relative to the larger."
    ),
    "empty_cohorts": (
        "More of the same traffic would not help: too few blocks of the window hold players of "
        "both arms (the test needs 3 usable cohorts, at least one in each half of the window, "
        "and for weekly blocks the median week must not be empty), and scaling what was "
        "observed cannot fill an empty one. Check whether assignment or exposure stopped or "
        "began late."
    ),
}
_EMPTY_INTERIM = (
    "The assignments cover only part of the planned window, so some weeks of it are empty here "
    "and more of the same traffic could not fill them. If the run is still going, run to the "
    "planned end and look again; if it stopped, check whether assignment or exposure stopped "
    "early."
)
_UNIT = {7: "weekly", 14: "14-day"}
_NUMBERING = (
    "Cohort numbers count blocks of 7 or 14 days from 0, starting at design.start_utc, or at "
    "the first assignment when the spec registers none."
)
_INTERIM_TRAFFIC = (
    "This is an interim look: the weeks the assignments do not reach count as empty in the "
    "traffic figures, which describe the data so far and not a finished run, so a figure can "
    "fall as they fill."
)
_CAVEATS = (
    "About the traffic figures: they assume that the extra players arrive in the same weeks and "
    "in the same proportions between the arms, and are exposed at the same rate, so arrivals "
    "that come in spikes may not repeat; and they concern the sizes of the cohorts only, so a "
    "scale can still drop a cohort it cannot estimate (no variation, or a mean that is not "
    "positive). They do not price a longer run, or growing one arm only, which can cost less."
)
_PREFERRED = (
    " The preferred minimum is a quarter of the registered share of a block; it is used only "
    "while it keeps at least 90% of the cohorts that reach the floor."
)


def _count(number: float) -> str:
    return str(int(number)) if number == int(number) else f"{number:.1f}"


def _players(number: float) -> str:
    return f"{_count(number)} player" + ("" if number == 1 else "s")


def _times(factor: float) -> str:
    return f"{factor:.2f}".rstrip("0").rstrip(".")


def _when(moment: datetime) -> str:
    """`moment` in UTC, rounded up to the minute so that "after" it is never too early."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    if moment.second or moment.microsecond:
        moment = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return f"{moment:%Y-%m-%d %H:%M} UTC"


def _cohorts(block_days: int, blocks: list[int]) -> str:
    unit = _UNIT[block_days]
    if len(blocks) == 1:
        return f"{unit} cohort {blocks[0]}"
    listed = ", ".join(str(b) for b in blocks[:-1])
    return f"{unit} cohorts {listed} and {blocks[-1]}"


def _binding_text(arm: str, bindings: tuple[Binding, ...]) -> str:
    """The sizes that reach what a rule asks of them at the multiple, as one sentence."""
    groups: dict[tuple, dict[str, list[int]]] = {}
    for binding in bindings:
        key = (binding.block_days, binding.kind, binding.have, binding.need)
        groups.setdefault(key, {}).setdefault(binding.side, []).append(binding.block)
    parts = []
    for (days, kind, have, need), sides in groups.items():
        if kind == "weekly_median":
            parts.append(
                f"the median over the weeks of the smaller arm's size is {_players(have)} and "
                f"{need} are wanted for weekly cohorts"
            )
            continue
        wanted = f"the preferred minimum is {need}" if kind == "preferred" else f"{need} are wanted"
        if set(sides) == {"arm", "control"} and sides["arm"] == sides["control"]:
            where = _cohorts(days, sides["arm"])
            parts.append(f"both arms have {_players(have)} in {where}, where {wanted}")
            continue
        for side, blocks in sides.items():
            who = f"arm {arm} has" if side == "arm" else "control has"
            parts.append(f"{who} {_players(have)} in {_cohorts(days, blocks)}, where {wanted}")
    return "; ".join(parts)


def _price_text(arm: str, plan: CohortPlan, price: Price) -> str:
    sentence = (
        f"{_times(price.factor)} times the traffic observed (every cohort of both arms scaled "
        f"together) would meet the size rules for the cohorts, with {_UNIT[price.block_days]} "
        "cohorts at that multiple, and keep meeting them at any larger multiple. At that "
        "multiple these sizes reach what is wanted (the counts are as observed): "
        f"{_binding_text(arm, price.binding)}."
    )
    if price.first_pass is not None:
        sentence += (
            f" The plan already passes at {_times(price.first_pass)} times, but not at every "
            "larger multiple (the preferred minimum is judged again as the cohorts grow), so "
            f"{_times(price.factor)} is where it keeps passing."
        )
    if any(b.kind == "floor" for b in price.binding) and plan.floor > FLOOR:
        ratio = _times(math.ceil(plan.allocation_ratio * 100) / 100)
        sentence += (
            f" The floor is {plan.floor} instead of {FLOOR} because the two arms differ about "
            f"{ratio} to 1; a smaller gap between the arms lowers it."
        )
    if any(b.kind == "preferred" for b in price.binding):
        sentence += _PREFERRED
    return sentence


def _left_out_text(attempts: tuple[TrafficAttempt, ...]) -> str:
    return "; ".join(
        _cohorts(attempt.block_days, list(attempt.left_out))
        for attempt in attempts
        if attempt.left_out
    )


def _by_length(attempts: tuple[TrafficAttempt, ...]) -> str:
    parts = []
    for attempt in attempts:
        name = f"{_UNIT[attempt.block_days]} cohorts"
        now = f"{_times(attempt.now)} times" if attempt.now is not None else "no multiple would do"
        if not attempt.left_out:
            parts.append(f"{name}, {now}")
            continue
        later = attempt.after_windows_close
        if later is None:
            counted = "no multiple would do"
        elif later == 1.0:
            counted = "no extra traffic"
        else:
            counted = f"{_times(later)} times"
        parts.append(
            f"{name}, {now} as exported and {counted} once the cohorts left out are counted"
        )
    return "Each block length on its own: " + "; ".join(parts) + "."


def _windows_close(context: ResultsContext, arm: str, plan: CohortPlan) -> datetime | None:
    """When the last outcome window still open at the export closes, or None when none was.

    The cohorts left out are those with a player whose window closes after the as-of time, so
    the latest of those windows is the last to wait for, whichever block length is used.
    """
    if plan.as_of is None:
        return None
    still_open = [
        player.window_closes_at
        for player in context.analysed
        if player.arm in (arm, context.control) and player.window_closes_at > plan.as_of
    ]
    return max(still_open, default=None)


def _traffic_note(
    arm: str, plan: CohortPlan, found: TrafficNeeded, closes: datetime | None, interim: bool
) -> str:
    if found.blocker == "empty_cohorts" and interim:
        return f"arm {arm}: {_EMPTY_INTERIM}"
    if found.blocker is not None:
        return f"arm {arm}: {_BLOCKERS[found.blocker]}"
    parts = []
    left_out = _left_out_text(found.attempts)
    if left_out:
        parts.append(
            "Cohorts were left out because their outcome windows had not closed by "
            f"{_when(plan.as_of)}: {left_out}."
        )
    after_closing = "" if closes is None else f" after {_when(closes)}"
    now, after = found.now, found.after_windows_close
    if found.waiting_suffices:
        parts.append(
            f"Export again{after_closing}, once they have closed: {_UNIT[after.block_days]} "
            "cohorts would then meet the size rules at the traffic observed."
        )
        if now is not None:
            parts.append(f"Without waiting, {_price_text(arm, plan, now)}")
        else:
            parts.append("As exported, no multiple of the traffic would do.")
    elif now is not None and now == after:
        parts.append(f"Whether or not they are counted, {_price_text(arm, plan, now)}")
    else:
        if now is not None:
            lead = "As exported, " if after is not None else ""
            parts.append(lead + _price_text(arm, plan, now))
        elif left_out:
            parts.append("With those cohorts left out, no multiple of the traffic would do.")
        if after is not None:
            closed = "" if closes is None else f" (after {_when(closes)})"
            parts.append(
                f"Once they have closed{closed} and are counted, " + _price_text(arm, plan, after)
            )
    if len(found.attempts) > 1:
        parts.append(_by_length(found.attempts))
    return f"arm {arm}: " + " ".join(parts)


def _notes(
    context: ResultsContext,
    entries: list[dict[str, Any]],
    summary: dict[str, Any],
    settings: dict[str, Any],
    plans: dict[str, CohortPlan],
    traffic: dict[str, TrafficNeeded | None],
    closes: dict[str, datetime | None],
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
    priced = numbered = figures = False
    for arm, found in traffic.items():
        stopped = any(e["arm"] == arm and e.get("reason") == plans[arm].reason for e in entries)
        if found is not None and stopped:
            note = _traffic_note(arm, plans[arm], found, closes[arm], settings["interim"])
            notes.append(note)
            figures = figures or found.blocker is None
            numbered = numbered or bool(re.search(r"cohorts? \d", note))
            shown = found.now is not None or (
                found.after_windows_close is not None and not found.waiting_suffices
            )
            priced = priced or shown
    if numbered:
        notes.append(_NUMBERING)
    if figures and settings["interim"]:
        notes.append(_INTERIM_TRAFFIC)
    if priced:
        notes.append(_CAVEATS)
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
            f"21.5 (two arms of equal size, no change over time) the trigger flagged {mean:.1f}% "
            f"of tests on average and at most {worst:.1f}%, so about "
            f"{summary['flags_by_chance']:.2g} flags "
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
    traffic = {arm: traffic_needed(plan) for arm, plan in plans.items()}
    closes = {arm: _windows_close(context, arm, plan) for arm, plan in plans.items()}
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
        "plans": {arm: _plan(plan, traffic[arm], closes[arm]) for arm, plan in plans.items()},
        "tests": entries,
        "notes": _notes(context, entries, summary, settings, plans, traffic, closes, configuration),
    }
