"""The check behind RES-004: a guardrail worse than its tolerance allows (design section 21.12).

`guardrail_report` reads every non-control arm against control on every guardrail of the spec
(`referee.guardrails` does the statistics) and returns what a finding or a report needs: one
entry for each arm and guardrail, a summary, the settings used, and the sentences a reader
should get. The rule raises a finding from it when any comparison shows a breach or a possible
one; the report of milestone 4c prints the summary line even when the rule is quiet.

The wording says what was measured, on which reference, and how strong the evidence is: a breach
is "shown" when the whole interval for the harm is beyond the tolerance, "possible" when only the
point estimate is (and when the interval is one that cannot be trusted to show a breach by
itself: see `referee.guardrails`). Nothing here names a cause.
"""

from __future__ import annotations

from typing import Any

from referee.guardrails import (
    CHANCE_LEVEL,
    CONFIDENCE,
    DIGITS,
    REFERENCES,
    SMALL_COUNT,
    GuardrailTest,
    Harm,
    ReferenceResult,
    chance_could_explain,
    guardrail_tests,
)
from referee.results import METRIC_FAMILIES, ResultsContext
from referee.rules.text import join_and, percent_exact, percent_near, sig, sig_up

_UNITS = {
    "sessions_7d": "sessions per player",
    "purchases_7d": "purchases per player",
    "revenue_usd_7d": "USD per player",
}
_NAMES = {"control": "control's mean", "baseline": "the registered baseline"}
_HEADLINES = {
    "breach_shown": "a breach is shown",
    "breach_possible": "a breach is possible, not shown",
    "within_tolerance": "within the tolerance",
    "not_evaluated": "not evaluated",
}
_NOT_RULED_OUT = "within the tolerance on the point estimate, but the data cannot rule out a breach"


# --- Evidence ---------------------------------------------------------------------------------


def _harm_evidence(harm: Harm) -> dict[str, Any]:
    return {
        "harm": {"point": harm.point, "low": harm.low, "high": harm.high},
        "reference_value": harm.reference_value,
        "measured": {"point": harm.measured[0], "low": harm.measured[1], "high": harm.measured[2]},
        "tier": harm.tier,
        "not_verified": harm.not_verified,
        "no_variation": harm.no_variation,
        "constant_group": harm.constant_group,
        "chance_all_alike": harm.chance_all_alike,
        "capped_by": harm.capped_by,
        "uncapped_tier": harm.uncapped_tier,
    }


def _reference_evidence(result: ReferenceResult) -> dict[str, Any]:
    if result.harm is None:
        return {"evaluated": False, "reason": result.reason}
    return {"evaluated": True, "reason": None, **_harm_evidence(result.harm)}


def _entry(test: GuardrailTest) -> dict[str, Any]:
    binary = test.kind == "binary"
    return {
        "arm": test.arm,
        "guardrail": test.guardrail,
        "kind": test.kind,
        "family": METRIC_FAMILIES.get(test.guardrail),
        "harmful_direction": test.harmful_direction,
        "tolerance": test.tolerance,
        "baseline": test.baseline,
        "n": {"arm": test.n_arm, "control": test.n_control},
        "means": {"arm": test.mean_arm, "control": test.mean_control},
        "events": {"arm": test.events_arm, "control": test.events_control} if binary else None,
        "references": {
            "control": _reference_evidence(test.control),
            "baseline": _reference_evidence(test.baseline_reference),
        },
        "control_on_baseline": _reference_evidence(test.control_on_baseline),
        "status": test.status,
        "tier": test.tier,
        "decided_by": list(test.decided_by),
        "references_agree": test.references_agree,
        "baseline_has_moved": test.baseline_has_moved,
        "small_counts": test.small_counts,
        "unreachable": list(test.unreachable),
    }


def _not_verified(entry: dict[str, Any]) -> bool:
    """A comparison within the tolerance on the point estimate whose interval reaches beyond it
    on some reference: the data cannot rule out a breach."""
    return entry["status"] == "within_tolerance" and any(
        ref["evaluated"] and ref["not_verified"] for ref in entry["references"].values()
    )


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of the entries by status and the one line the report always prints."""
    counts = {
        status: sum(entry["status"] == status for entry in entries)
        for status in ("breach_shown", "breach_possible", "within_tolerance", "not_evaluated")
    }
    not_verified = sum(_not_verified(entry) for entry in entries)
    out_of_reach = sum(len(entry["unreachable"]) == len(REFERENCES) for entry in entries)
    noun = "comparison" if len(entries) == 1 else "comparisons"
    line = (
        f"RES-004: {len(entries)} {noun} of an arm against control on a guardrail, "
        f"a breach shown in {counts['breach_shown']}, possible in {counts['breach_possible']}, "
        f"{counts['within_tolerance']} within the tolerance ({not_verified} of them with an "
        f"interval that reaches beyond it, so the data cannot rule out a breach), "
        f"{counts['not_evaluated']} not evaluated."
    )
    if out_of_reach:
        line += (
            f" In {out_of_reach} of them the tolerance is not below the largest possible harm, "
            "so no data could show a breach."
        )
    return {
        "tests": len(entries),
        **counts,
        "not_verified": not_verified,
        "tolerance_out_of_reach": out_of_reach,
        "line": line,
    }


def _settings(context: ResultsContext) -> dict[str, Any]:
    return {
        "confidence": CONFIDENCE,
        "decision_digits": DIGITS,
        "small_count": SMALL_COUNT,
        "references": list(REFERENCES),
        "guardrails": [guardrail.name for guardrail in context.spec.guardrails],
        "arms": [arm for arm in context.arm_names if arm != context.control],
    }


# --- Sentences --------------------------------------------------------------------------------


def _share(value: float, tolerance: float) -> str:
    """A harm as a percentage, with the decimals that keep it on its side of the tolerance."""
    return percent_near(value, tolerance)


def _number(entry: dict[str, Any], value: float) -> str:
    """A mean or a rate without its unit."""
    return f"{sig(100 * value)}%" if entry["kind"] == "binary" else sig(value)


def _unit(entry: dict[str, Any]) -> str:
    """What the numbers of a guardrail count, to come after the last of them."""
    if entry["kind"] == "binary":
        return " of players"
    unit = _UNITS.get(entry["guardrail"])
    return f" {unit}" if unit else ""


def _quantity(entry: dict[str, Any], value: float) -> str:
    """One mean or rate in the guardrail's own terms."""
    return f"{_number(entry, value)}{_unit(entry)}"


def _span(entry: dict[str, Any], low: float, high: float) -> str:
    """Two numbers of the guardrail, "2.20 to 2.30 sessions per player"."""
    return f"{_number(entry, low)} to {_quantity(entry, high)}"


def _headline(entry: dict[str, Any]) -> str:
    if _not_verified(entry):
        return _NOT_RULED_OUT
    return _HEADLINES[entry["status"]]


def _verdict(reference: dict[str, Any]) -> str:
    tier = reference["tier"]
    if reference["capped_by"]:  # the whole interval is beyond the tolerance, and is not believed
        return (
            "and the whole interval is beyond the tolerance, but this reading is held to possible"
        )
    if tier == "shown":
        return "and the whole interval is beyond the tolerance"
    if tier == "possible":
        return "and only the point estimate is beyond the tolerance: the interval reaches inside it"
    text = "and the point estimate is within the tolerance"
    if reference["not_verified"]:
        text += ", though the interval reaches beyond it"
    return text


def _harm_text(entry: dict[str, Any], reference: dict[str, Any], of_what: str) -> str:
    tolerance = entry["tolerance"]
    harm = reference["harm"]
    gain = "a gain; " if harm["point"] < 0 else ""  # a negative harm is a better guardrail
    return (
        f"the harm is {_share(harm['point'], tolerance)} of {of_what} "
        f"({gain}{_share(harm['low'], tolerance)} to {_share(harm['high'], tolerance)}) against "
        f"a tolerance of {percent_exact(tolerance)}, {_verdict(reference)}."
    )


def _arm_at_zero(entry: dict[str, Any]) -> bool:
    """The arm's mean is 0 and control's is above 0: the ratio of the means has no logarithm."""
    arm, control = entry["means"]["arm"], entry["means"]["control"]
    return arm is not None and control is not None and arm == 0 and control > 0


def _arm_collapsed(entry: dict[str, Any]) -> bool:
    """An arm at 0 against a control that is not, where chance does not explain an arm all at 0:
    the two groups plainly differ. The chance is the one the baseline reading worked out for a
    group with no variation; for a rate (which has an interval of its own, never held) it is
    worked out here from control's share of players without the outcome."""
    if not _arm_at_zero(entry):
        return False
    if entry["kind"] == "binary":
        events, players = entry["events"]["control"], entry["n"]["control"]
        chance = (1 - events / players) ** entry["n"]["arm"] if players else None
    else:
        chance = entry["references"]["baseline"].get("chance_all_alike")
    return chance is not None and not chance_could_explain(chance)


def _control_sentence(entry: dict[str, Any]) -> str:
    reference = entry["references"]["control"]
    arm_mean, control_mean = entry["means"]["arm"], entry["means"]["control"]
    what = "rate" if entry["kind"] == "binary" else "mean"
    if not reference["evaluated"]:
        text = f"Against control's mean: not measured ({reference['reason']})."
        if _arm_at_zero(entry):
            text += (
                f" The {what} of {entry['arm']} is 0 and control's "
                f"{_quantity(entry, control_mean)}, a fall of the whole of control's {what}."
            )
        return text
    measured = reference["measured"]
    return (
        f"Against control's mean: the {what} of {entry['arm']} is {_number(entry, arm_mean)} and "
        f"control's {_quantity(entry, control_mean)}, a ratio of {sig(measured['point'], 4)} "
        f"(95% interval "
        f"{sig(measured['low'], 4)} to {sig(measured['high'], 4)}); "
        f"{_harm_text(entry, reference, _NAMES['control'])}"
        + _cap_sentence(entry, reference, "control")
    )


def _chance_text(chance: float) -> str:
    if chance < 0.001:
        return "under 0.1% of samples"
    return f"about {sig(100 * chance, 2)}% of samples"


def _same_value_sentence(entry: dict[str, Any], reference: dict[str, Any], reading: str) -> str:
    """A group in which every player has the same value: what that does to the interval and,
    where the comparison was made, whether chance explains it."""
    group = reference["constant_group"]
    label = entry["arm"] if group == "arm" else "control"
    other = "control" if group == "arm" else entry["arm"]
    players = entry["n"]["arm" if group == "arm" else "control"]
    width = (
        "so that interval has no width"
        if reading == "baseline"
        else f"so the interval for the ratio takes its width from {other} alone"
    )
    text = f" Every player of {label} ({players}) has the same value, {width}"
    chance = reference["chance_all_alike"]
    if chance is None:
        return f"{text}, and an interval with no width is not believed to show a breach."
    text += (
        f"; at {other}'s share of players with that value, so many alike would arise by chance "
        f"in {_chance_text(chance)}"
    )
    if chance_could_explain(chance):
        return (
            f"{text}, which is not below {sig(100 * CHANCE_LEVEL, 2)}%, so chance is not ruled out."
        )
    return f"{text}, which chance does not explain."


def _cap_sentence(entry: dict[str, Any], reference: dict[str, Any], reading: str) -> str:
    """Why a reading is held to possible, or what it rests on where it has no variation."""
    if reference["capped_by"] == "heavy_tail":
        return (
            " For a revenue-like guardrail whose fall is harmful the t interval for a mean "
            "cannot be trusted to show a breach on its own (it lies wholly below the true mean "
            "more often than it should); the reading against control's mean is not held."
        )
    if reference["no_variation"]:
        return _same_value_sentence(entry, reference, reading)
    return ""


def _baseline_sentence(entry: dict[str, Any]) -> str:
    reference = entry["references"]["baseline"]
    if not reference["evaluated"]:
        return f"Against the registered baseline: not measured ({reference['reason']})."
    measured = reference["measured"]
    what = "rate" if entry["kind"] == "binary" else "mean"
    return (
        f"Against the registered baseline of {_quantity(entry, entry['baseline'])}: "
        f"{entry['arm']}'s own {what} is {_quantity(entry, measured['point'])} (95% interval "
        f"{_span(entry, measured['low'], measured['high'])}); "
        f"{_harm_text(entry, reference, 'the baseline')}"
        + _cap_sentence(entry, reference, "baseline")
    )


def _agreement_sentence(entry: dict[str, Any]) -> str:
    agree = entry["references_agree"]
    if agree is True:
        return "The two references agree."
    if agree is None:
        measured = [name for name in REFERENCES if entry["references"][name]["evaluated"]]
        return f"Only the reference to {_NAMES[measured[0]]} could be measured."
    decided = join_and([_NAMES[name] for name in entry["decided_by"]])
    return f"The references differ; the stricter reading, against {decided}, decides."


def _held_in_brief(entry: dict[str, Any], own: dict[str, Any]) -> str:
    """Why the reading of control against the baseline is held to possible, after its figures."""
    if own["capped_by"] == "heavy_tail":
        return (
            ": the whole interval is beyond the tolerance, but this reading is held to possible "
            "for a revenue-like guardrail whose fall is harmful"
        )
    if own["capped_by"] == "no_variation":
        return (
            f": every control player ({entry['n']['control']}) has the same value, so that "
            "interval has no width and chance could explain that, so the reading is held to "
            "possible"
        )
    return ""


def _moved_sentence(entry: dict[str, Any]) -> str:
    own = entry["control_on_baseline"]
    tolerance = entry["tolerance"]
    harm = own["harm"]
    text = (
        f"Control itself is {'beyond' if own['tier'] == 'shown' else 'possibly beyond'} the "
        f"tolerance of the registered baseline (a harm of {_share(harm['point'], tolerance)}, "
        f"{_share(harm['low'], tolerance)} to {_share(harm['high'], tolerance)}"
        f"{_held_in_brief(entry, own)}), so the baseline may no longer describe this traffic"
    )
    # The clause about cause is for a breach on the baseline reading alone, which control's own
    # position could explain: not for a reading within the tolerance, not where control's
    # reading shows the breach too, and not for an arm all at 0 that chance does not explain.
    control = entry["references"]["control"]
    alone = control.get("tier") != "shown"
    if entry["references"]["baseline"]["tier"] != "within" and alone and not _arm_collapsed(entry):
        text += f"; a breach against the baseline alone does not show that {entry['arm']} caused it"
    return text + "."


def _unreachable_sentence(entry: dict[str, Any]) -> str:
    tolerance = percent_exact(entry["tolerance"])
    if len(entry["unreachable"]) == len(REFERENCES):
        return (
            "A metric that is never negative cannot fall by more than the whole of a reference "
            f"value, so a tolerance of {tolerance} cannot be exceeded and no data could show a "
            "breach of this guardrail."
        )
    # A rate cannot rise above 100%: control's own rate can be exceeded by (1 + tolerance) only
    # if it is below 1 / (1 + tolerance).
    limit = sig_up(100 / (1 + entry["tolerance"]))
    return (
        "A rate cannot rise above 100%, and the registered baseline times one plus the "
        f"tolerance of {tolerance} is not below that, so the reading against the registered "
        "baseline cannot show a breach; the reading against control's mean can only if "
        f"control's rate is below {limit}%."
    )


def _entry_note(entry: dict[str, Any]) -> str:
    direction = entry["harmful_direction"]
    label = (
        f"arm {entry['arm']}, guardrail {entry['guardrail']} ({direction} is harmful, tolerance "
        f"{percent_exact(entry['tolerance'])}): {_headline(entry)}."
    )
    if entry["status"] == "not_evaluated":
        reasons = [f"{_NAMES[name]}: {entry['references'][name]['reason']}" for name in REFERENCES]
        text = f"{label} Neither reference could be measured ({'; '.join(reasons)})."
        if len(entry["unreachable"]) == len(REFERENCES):
            text += " " + _unreachable_sentence(entry)
        return text
    parts = [label, _control_sentence(entry), _baseline_sentence(entry)]
    parts.append(_agreement_sentence(entry))
    if entry["baseline_has_moved"] and entry["references"]["baseline"]["evaluated"]:
        parts.append(_moved_sentence(entry))
    if entry["small_counts"]:
        parts.append(
            f"A group has fewer than {SMALL_COUNT} players on one side of its rate, so these "
            "intervals are rough."
        )
    if entry["unreachable"]:
        parts.append(_unreachable_sentence(entry))
    return " ".join(parts)


def _checked_note(settings: dict[str, Any]) -> str:
    names = join_and(settings["guardrails"]) or "none"
    return (
        "RES-004 reads each non-control arm against control on each guardrail of the spec "
        f"({names}), on the analysed players. A guardrail is breached when it is worse than its "
        "registered baseline by more than its tolerance. Referee measures the harm, as a share "
        "of a reference value (positive is worse), against two references and takes the "
        "stricter: control's observed mean (the arm's mean over control's, with a 95% interval "
        "on the log scale), and the registered baseline (the arm's own mean with a t interval, "
        "or its rate with a Wilson interval). A breach is shown when the whole 95% interval "
        "for the harm is beyond the tolerance, and possible when only the point estimate is; an "
        "interval with no width that chance could explain, and the t interval of a revenue-like "
        "guardrail against the registered baseline when a fall is harmful and the group has some "
        "spread, can only make a breach possible. A point "
        "estimate within the tolerance is not a finding, even where its interval reaches beyond "
        "the tolerance, in which case the data cannot rule out a breach. The decisions are "
        f"made on the shares rounded to {DIGITS} places."
    )


_UNADJUSTED_NOTE = (
    "The intervals are unadjusted 95% intervals, one for each arm, guardrail and reference: "
    "with several arms and guardrails some of them will miss the true value. A breach shown "
    "here is a reason to look at the guardrail, not a verdict on the arm."
)
_REVENUE_NOTE = (
    "For a revenue-like guardrail (most players at 0 and a few large; a guardrail is taken to be "
    "one by its metric name, and Referee has not looked at its values) the intervals are less "
    "reliable than 95% suggests, and Referee has not measured by how much. The t interval for "
    "the mean of such data lies wholly below the true mean more often than it should, and hardly "
    "ever wholly above it. RES-008 reports simulated rates for Welch's interval for a "
    "difference of means; those are not the rates of these intervals."
)
_FALL_HELD_NOTE = (
    " So when a fall is harmful the reading against the registered baseline of a group with "
    "some spread is held to possible there, and a breach is shown only by the reading against "
    "control's mean (a group whose players all have one value has no t interval, and is judged "
    "by chance, as said with its reading)."
)
_RISE_NOT_HELD_NOTE = (
    " When a rise is harmful that reading is not held, but it hardly ever shows a rise from "
    "such data, so a rise is carried by the reading against control's mean."
)
_COUNT_NOTE = (
    "For a count guardrail (sessions, purchases) whose fall is harmful, the registered-baseline "
    "reading (a t interval for the arm's own mean) can show a fall more often than 95% "
    "suggests when the counts are small, because counts are right-skewed. It is not held, and "
    "Referee has not measured by how much."
)


def _notes(entries: list[dict[str, Any]], settings: dict[str, Any]) -> list[str]:
    notes = [_checked_note(settings)]
    notes += [_entry_note(entry) for entry in entries]
    if entries:
        notes.append(_UNADJUSTED_NOTE)
    revenue = [entry for entry in entries if entry["family"] == "revenue_like"]
    if revenue:
        note = _REVENUE_NOTE
        if any(entry["harmful_direction"] == "decrease" for entry in revenue):
            note += _FALL_HELD_NOTE
        if any(entry["harmful_direction"] == "increase" for entry in revenue):
            note += _RISE_NOT_HELD_NOTE
        notes.append(note)
    if any(e["family"] == "count" and e["harmful_direction"] == "decrease" for e in entries):
        notes.append(_COUNT_NOTE)
    return notes


def guardrail_report(context: ResultsContext) -> dict[str, Any]:
    """Every non-control arm against control on every guardrail of the spec.

    The guardrails come in the spec's order and the arms inside each in the spec's order. The
    report has the keys `summary`, `settings`, `tests` and `notes`.
    """
    entries = [_entry(test) for test in guardrail_tests(context)]
    settings = _settings(context)
    return {
        "summary": summarise(entries),
        "settings": settings,
        "tests": entries,
        "notes": _notes(entries, settings),
    }


__all__ = ["guardrail_report", "summarise"]
