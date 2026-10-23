"""The check behind RES-008: signs that a metric is skewed or heavy-tailed (design section 21.11).

`heavy_tail_report` reads every non-control arm against control on every metric of the spec
that is not binary, and returns what a finding or a report needs: one entry per arm and
metric with its status, a summary, the settings used, and the sentences a reader should get.
The rule raises a finding from it when any entry shows a sign; the results report
prints the summary line even when the rule is quiet.

The wording says what was measured and where. The rates come from one simulated family
(revenue-like metrics of independent players, two arms, an unadjusted 95% Welch interval) and
are quoted only for a metric of that family. Everything else gets the signs and a statement
that no error rate was measured for it. Nothing here names a cause.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
from typing import Any

from referee.cohorts import UNIT_CLASS
from referee.heavy_tails import (
    EQUAL_ARMS_SPLIT,
    FAR_APART_PAYERS,
    FAR_APART_SPLIT,
    KOHAVI_MULTIPLE,
    KURTOSIS_OVER,
    LARGE_EFFECT_FROM,
    SKEWNESS_OVER,
    TOP_PERCENT,
    TOP_SHARE_OVER,
    Comparison,
    GroupShape,
    NotSimulated,
    Pair,
    far_apart,
    nearest_cases,
    not_simulated,
    pairs,
    simulated,
)
from referee.pooled_rates import (
    CASES,
    EXCESS_RATE,
    NOMINAL_RATE,
    UNIT,
    Case,
    Effects,
    Extrapolation,
    SimulatedRange,
    percent,
)
from referee.results import METRIC_FAMILIES, ExportMetric, ResultsContext
from referee.rules.text import join_and, sig

CONFIDENCE = 0.95
_RATE_DIGITS = 5  # a rate is a whole number of 1/UNIT = 1/100,000

_UNITS = {
    "revenue_usd_7d": "USD per player",
    "sessions_7d": "sessions per player",
    "purchases_7d": "purchases per player",
}
_UNREAD = {
    "too_few_players": "it has fewer than 2 analysed players",
    "all_zero": "every value is 0",
    "no_variation": "every value is the same",
    "negative_value": "it holds a negative value",
    "not_computable": "its values are not finite, or too large or too small to measure",
}
_EFFECTS_TEXT: dict[Effects, str] = {
    "small": "an effect of none or +20%",
    "large": "an effect of +50% or +100%",
}
_REASONS_NOT_SIMULATED: dict[NotSimulated, str] = {
    "metric_not_simulated": (
        "Referee has simulated this interval for revenue-like metrics (money that most players "
        "leave at zero) only, so it states no error rate for this metric."
    ),
    "unit_not_independent": (
        "The spec does not randomise and analyse one class of independent players (player or "
        "user, or device for both), and the simulations draw independent players, so Referee "
        "states no error rate."
    ),
    "a_group_has_no_players": (
        "A group has no analysed players, so Referee cannot place this comparison among the "
        "simulated cases and states no error rate."
    ),
    "no_players_who_spend": (
        "No player in the smaller group has a value other than 0, so Referee cannot place this "
        "comparison among the simulated cases and states no error rate."
    ),
}
_EXTRAPOLATION_TEXT: dict[Extrapolation, str] = {
    "split_above_range": "the split is above the largest simulated ({largest} to 1)",
    "payers_below_range": (
        "there are fewer players who spend than in the cases simulated at this split"
    ),
    "payers_above_range": (
        "there are more players who spend than in the cases simulated at this split"
    ),
}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _ratio(value: Fraction | int) -> str:
    """A split in words: whole numbers as they are, others to two decimals, and to more where
    that is needed so that the figure shown is not a whole number (1.001) or on the other side
    of the limit for groups about equal in size (1.251) from the split itself."""
    number = Fraction(value)
    if number.denominator == 1:
        return f"{number.numerator:,}"
    places = 2
    while places < 6:
        shown = Fraction(round(number, places))
        if (shown <= EQUAL_ARMS_SPLIT) == (number <= EQUAL_ARMS_SPLIT) and (
            shown != 1 or number == 1
        ):
            break
        places += 1
    return f"{float(number):,.{places}f}".rstrip("0").rstrip(".")


_list = join_and
_sig = sig


def _measure(value: float) -> str:
    """A skewness or kurtosis, for a sentence: four significant figures."""
    return _sig(value, 4)


def _over(value: float, level: float, digits: int) -> str:
    """`value` to `digits` significant figures, with more of them if that is what it takes to
    show that it is over `level` (the decision is made on six places, and 100.04 is not "100")."""
    for places in range(digits, 10):
        shown = _sig(value, places)
        if float(shown.replace(",", "")) > level:
            return shown
    return _sig(value, 9)


def _plural(number: int, noun: str) -> str:
    return f"{number:,} {noun}" + ("" if number == 1 else "s")


def _count_who(number: int, metric: str) -> str:
    """`number` players who spend (money) or have a value other than 0 (anything else)."""
    if METRIC_FAMILIES.get(metric) == "revenue_like":
        return f"{_plural(number, 'player')} who {'spends' if number == 1 else 'spend'}"
    return f"{_plural(number, 'player')} with a value other than 0"


def _who(metric: str) -> str:
    return (
        "players who spend"
        if METRIC_FAMILIES.get(metric) == "revenue_like"
        else ("players with a value other than 0")
    )


# --- Evidence ---------------------------------------------------------------------------------


def _group(shape: GroupShape) -> dict[str, Any]:
    return {
        "n": shape.n,
        "payers": shape.payers,
        "mean": shape.mean,
        "skewness": shape.skewness,
        "excess_kurtosis": shape.excess_kurtosis,
        "top_count": shape.top_count,
        "top_share": shape.top_share,
        "kohavi_minimum": shape.kohavi_minimum,
        "signs": list(shape.limbs),
        "unread": shape.unread,
    }


def _case_evidence(case: Case) -> dict[str, Any]:
    return {
        "split": _round(float(case.split)),
        "payers": case.payers,
        "low": case.low / UNIT,
        "high": case.high / UNIT,
    }


def _range(found: SimulatedRange, comparison: Comparison, nearer: bool | None) -> dict[str, Any]:
    """A simulated range as evidence. `nearer` is whether its effects are the ones nearer the
    difference seen (None when that cannot be told): the severity reads those."""
    nearest = nearest_cases(found, comparison)
    return {
        "low": round(found.low / UNIT, _RATE_DIGITS),
        "high": round(found.high / UNIT, _RATE_DIGITS),
        "cells": found.cells,
        "tail_weights": list(found.tails),
        "fewest_runs": found.min_runs,
        "extrapolated": list(found.extrapolated),
        "rising": list(found.rising),
        "rising_in_one_order": list(found.rising_in_one),
        "floor": found.floor_only,
        "cases": [_case_evidence(case) for case in found.cases],
        "nearest_cases": [_case_evidence(case) for case in nearest],
        "far_apart": far_apart(found),
        # whether an end of the range comes from a case further away than the nearest ones
        "ends_from_further": {
            "low": found.low < min(case.low for case in nearest),
            "high": found.high > max(case.high for case in nearest),
        },
        "nearer": nearer,
    }


def _simulated(context: ResultsContext, metric: ExportMetric, pair: Pair) -> dict[str, Any] | None:
    if pair.status != "tripped":
        return None
    reason = not_simulated(context, metric, pair.comparison)
    if reason is not None or pair.comparison is None:
        return {"reason": reason, "ranges": None}
    nearer = pair.nearer_effects
    ranges = simulated(pair.comparison)
    return {
        "reason": None,
        "ranges": {
            effects: _range(found, pair.comparison, None if nearer is None else effects == nearer)
            for effects, found in ranges.items()
        },
    }


def _read_as(comparison: Comparison) -> str:
    """How the groups were put among the simulated cases: `equal` (about equal in size: placed
    among the cases of two groups of the same size) or `both_orders` (the range covers the arm
    the larger group and control the larger group)."""
    return "equal" if comparison.placed_as_equal else "both_orders"


def _entry(context: ResultsContext, metric: ExportMetric, pair: Pair) -> dict[str, Any]:
    comparison = pair.comparison
    larger_payers = None
    if comparison is not None:
        other = pair.control if comparison.smaller == pair.arm.arm else pair.arm
        larger_payers = other.payers
    return {
        "arm": pair.arm.arm,
        "metric": metric.name,
        "kind": metric.kind,
        "family": METRIC_FAMILIES.get(metric.name),
        "status": pair.status,
        "signs": list(pair.limbs),
        "groups": {pair.arm.arm: _group(pair.arm), pair.control.arm: _group(pair.control)},
        "comparison": None
        if comparison is None
        else {
            "split": _round(float(comparison.split)),
            "split_numerator": comparison.split.numerator,
            "split_denominator": comparison.split.denominator,
            "larger": comparison.larger,
            "smaller": comparison.smaller,
            "payers_in_smaller": comparison.payers,
            "payers_in_larger": larger_payers,
            "placed_as_equal": comparison.placed_as_equal,
            "read_as": _read_as(comparison),
        },
        "estimate": pair.estimate if pair.status == "tripped" else None,
        "relative_difference": _round(pair.relative_difference),
        "effect_seen": pair.effect_seen,
        "nearer_effects": pair.nearer_effects,
        "simulated": _simulated(context, metric, pair),
    }


def _ranges_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    found = entry.get("simulated")
    if not found or not found.get("ranges"):
        return []
    return list(found["ranges"].values())


def _deciding(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The ranges the severity reads: those for the effects nearer the difference seen, or both
    when it cannot be told which are nearer."""
    return [found for found in _ranges_of(entry) if found["nearer"] is not False]


def summarise(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of the entries by status, the figures the severity reads, and the one line the
    report always prints."""
    by_status = {
        status: sum(entry["status"] == status for entry in entries)
        for status in ("tripped", "not_tripped", "not_evaluated")
    }
    printed = [found for entry in entries for found in _ranges_of(entry)]
    deciding = [found for entry in entries for found in _deciding(entry)]
    noun = "comparison" if len(entries) == 1 else "comparisons"
    line = (
        f"RES-008: {len(entries)} {noun} (binary metrics are not read), "
        f"{by_status['tripped']} with a sign of a heavy tail, "
        f"{by_status['not_evaluated']} not evaluated. "
        "No sign is not a pass: in Referee's simulations every run of a revenue-like metric "
        "showed one, so they say nothing about a metric that shows none."
    )
    return {
        "tests": len(entries),
        **by_status,
        "largest_simulated_rate": max((found["high"] for found in deciding), default=None),
        "largest_printed_rate": max((found["high"] for found in printed), default=None),
        "floor_ranges": sum(found["floor"] for found in deciding),
        "line": line,
    }


def _settings(context: ResultsContext) -> dict[str, Any]:
    read = [name for name, metric in context.metrics.items() if metric.kind != "binary"]
    population = context.spec.population
    return {
        "kohavi_multiple": KOHAVI_MULTIPLE,
        "skewness_over": SKEWNESS_OVER,
        "kurtosis_over": KURTOSIS_OVER,
        "top_percent": TOP_PERCENT,
        "top_share_over": TOP_SHARE_OVER,
        "confidence": CONFIDENCE,
        "nominal_rate": NOMINAL_RATE / UNIT,
        "excess_rate": EXCESS_RATE / UNIT,
        "equal_arms_up_to_split": _round(float(EQUAL_ARMS_SPLIT)),
        "large_effect_from": LARGE_EFFECT_FROM,
        "far_apart": {"players": FAR_APART_PAYERS, "split": _round(float(FAR_APART_SPLIT))},
        "metrics_read": read,
        "metrics_not_read_binary": [n for n in context.metrics if n not in read],
        "randomization_unit": population.randomization_unit,
        "analysis_unit": population.analysis_unit,
        "unit_class": {
            "randomization": UNIT_CLASS.get(population.randomization_unit),
            "analysis": UNIT_CLASS.get(population.analysis_unit),
        },
    }


# --- Sentences --------------------------------------------------------------------------------


def _group_sentence(name: str, shape: GroupShape, metric: str) -> str:
    head = f"{name}: {_plural(shape.n, 'analysed player')}, {_count_who(shape.payers, metric)}"
    skewness, kurtosis_, share_, count = (
        shape.skewness,
        shape.excess_kurtosis,
        shape.top_share,
        shape.top_count,
    )
    if skewness is None or kurtosis_ is None or share_ is None or count is None:
        return f"{head}, could not be read ({_UNREAD[shape.unread or 'not_computable']})."
    if "kohavi" in shape.limbs:
        sign = "-" if skewness < 0 else ""
        skew = (
            f"skewness {sign}{_over(abs(skewness), SKEWNESS_OVER, 4)}, for which the size rule "
            f"asks for about {_sig(shape.kohavi_minimum or 0)} players (a sign)"
        )
    else:
        skew = f"skewness {_measure(skewness)}"
    if "kurtosis" in shape.limbs:
        kurtosis = (
            f"excess kurtosis {_over(kurtosis_, KURTOSIS_OVER, 4)} (above {KURTOSIS_OVER}: a sign)"
        )
    else:
        kurtosis = f"excess kurtosis {_measure(kurtosis_)}"
    top = (
        "the top player holds"
        if count == 1
        else f"the top {count:,} players ({TOP_PERCENT}% of them, rounded up) hold"
    )
    if "top_share" in shape.limbs:
        shown = _over(100 * share_, 100 * TOP_SHARE_OVER, 3)
        share = f"{top} {shown}% of the total (above {100 * TOP_SHARE_OVER:.0f}%: a sign)"
    else:
        share = f"{top} {100 * share_:.1f}% of the total"
    return f"{head}; {skew}; {kurtosis}; {share}."


def _signed_percent(share: float) -> str:
    """A share as a signed percentage. One that rounds to `LARGE_EFFECT_FROM` shows the decimals
    that keep it on its own side of that level (the nearer effects are decided on it)."""
    percent_, level = abs(100 * share), 100 * LARGE_EFFECT_FROM
    if round(percent_) == round(level):
        for places in range(1, 5):
            shown = f"{percent_:.{places}f}"
            if (float(shown) >= level) == (percent_ >= level):
                break
        return f"{'-' if share < 0 else '+'}{shown}%"
    whole = round(100 * share)
    return f"{whole:+,d}%" if whole else "0%"


def _seen_sentence(entry: dict[str, Any]) -> str:
    """The difference seen, as the rows "nearer the difference seen" rest on it (empty when the
    note quotes no rates, or when there is nothing to say)."""
    ranges = bool(_ranges_of(entry))
    relative, effect = entry["relative_difference"], entry["effect_seen"]
    if relative is not None:
        text = f"The difference seen is {_signed_percent(relative)} of control's mean"
        if ranges and relative < 0 and effect is not None:
            text += (
                f", which is {_signed_percent(effect)} in the terms of the simulations (the "
                "higher mean over the lower one)"
            )
        return f"{text}. "
    if not ranges:
        return ""
    if entry["nearer_effects"] is None:
        return "The means cannot be compared, so both ranges set the severity. "
    arm, control = entry["groups"].values()
    return (
        f"The means are {_measure(arm['mean'])} ({entry['arm']}) and {_measure(control['mean'])} "
        "(control), too far apart to give a share of control's mean; that is read as an effect "
        "of +50% and +100%. "
    )


def _interval_sentence(entry: dict[str, Any]) -> str:
    estimate = entry["estimate"]
    unit = _UNITS.get(entry["metric"], "in the metric's units")
    seen = _seen_sentence(entry)
    if "error" in estimate:
        return f"{seen}Welch's 95% interval could not be computed ({estimate['error']})."
    return (
        f"{seen}Welch's 95% interval for the difference ({entry['arm']} less control) is "
        f"{_sig(estimate['ci_low'])} to {_sig(estimate['ci_high'])} {unit}."
    )


def _cases_text(found: dict[str, Any]) -> str:
    """The cases of a range by split: "split 3 to 1 with 39 and 90 players who spend", and with
    different counts at different splits "splits 1 to 1 (90 and 130 players who spend) and 1.5
    to 1 (39 and 90 players who spend)"."""
    by_split: dict[float, set[int]] = {}
    for case in found["cases"]:
        by_split.setdefault(case["split"], set()).add(case["payers"])
    splits = sorted(by_split)

    def counts(split: float) -> str:
        return _list([f"{count:,}" for count in sorted(by_split[split])])

    def name(split: float) -> str:
        return f"{_ratio(Fraction(split).limit_denominator(100))} to 1"

    if len({frozenset(counted) for counted in by_split.values()}) == 1:
        noun = "split" if len(splits) == 1 else "splits"
        return (
            f"{noun} {_list([name(s) for s in splits])} with {counts(splits[0])} players who spend"
        )
    return "splits " + _list([f"{name(s)} ({counts(s)} players who spend)" for s in splits])


def _case_text(case: dict[str, Any]) -> str:
    split = _ratio(Fraction(case["split"]).limit_denominator(100))
    return f"{split} to 1 with {case['payers']:,} players who spend"


def _nearest_text(cases: list[dict[str, Any]]) -> str:
    """The nearest case or cases, and the rates they failed at, over all of them when there is
    more than one (a range read both ways round has the same case twice, once for each order)."""
    names = list(dict.fromkeys(_case_text(case) for case in cases))
    span = _share_text(
        {"low": min(case["low"] for case in cases), "high": max(case["high"] for case in cases)}
    )
    which = "the nearest one" if len(names) == 1 else "the nearest ones"
    return f"{which}, {_list(names)}, which failed in {span}"


def _tails_text(tails: Sequence[int]) -> str:
    low, high = tails
    words = {2: "two", 3: "three"}
    if low == high == 3:
        return "over all three tail weights"
    if low == high:
        return f"over {words[low]} of the three tail weights"
    return f"over {words[low]} or {words[high]} of the three tail weights"


def _share_text(found: dict[str, Any]) -> str:
    return f"{percent(round(found['low'] * UNIT))} to {percent(round(found['high'] * UNIT))}"


def _largest_split(effects: Effects) -> Fraction:
    return max(c.split for c in CASES if c.effects == effects)


def _beyond_text(entry: dict[str, Any], effects: Effects, found: dict[str, Any]) -> str | None:
    if not found["extrapolated"]:
        return None
    reasons = " and ".join(
        [
            _EXTRAPOLATION_TEXT[flag].format(largest=_ratio(_largest_split(effects)))
            for flag in found["extrapolated"]
        ]
    )
    if found["floor"]:
        verdict = (
            "in the cases simulated the rate rose in that direction, so the true rate is "
            "probably above this range"
        )
    elif found["rising_in_one_order"]:
        verdict = (
            "in one order of the groups the rate rose in that direction and in the other it "
            "did not, so the true rate may be above this range"
        )
    else:
        verdict = (
            "the simulations do not show which way the rate goes there, so Referee does not "
            "know whether the true rate is above or below this range"
        )
    return (
        f"For {_EFFECTS_TEXT[effects]}, this comparison lies beyond the simulated cases: "
        f"{reasons}; {verdict}."
    )


def _order(entry: dict[str, Any]) -> tuple[Effects, Effects]:
    """The two sets of effects, the nearer one first when it can be told."""
    return ("large", "small") if entry["nearer_effects"] == "large" else ("small", "large")


def _row_name(entry: dict[str, Any], effects: Effects) -> str:
    near = " (nearer the difference seen)" if entry["nearer_effects"] == effects else ""
    return f"{_EFFECTS_TEXT[effects]}{near}"


def _direction_text(entry: dict[str, Any]) -> list[str]:
    """Which way the failed intervals fell, in the roles of the simulations: the group with the
    higher mean plays the treated arm. Only what the study showed is said."""
    comparison = entry["comparison"]
    split = Fraction(comparison["split_numerator"], comparison["split_denominator"])
    about_equal = split <= EQUAL_ARMS_SPLIT
    out = []
    if not about_equal:
        name = entry["arm"] if comparison["larger"] == "arm" else "control"
        out.append(
            f"With {_EFFECTS_TEXT['small']} and groups of unequal size, most of the failed "
            "intervals in the simulations made the larger group look better than it is; here "
            f"the larger group is {name}."
        )
    if about_equal:
        out.append(
            f"With {_EFFECTS_TEXT['large']} and groups of about equal size, most of the failed "
            "intervals in the simulations understated the gap between the groups."
        )
    return out


def _payers_clause(entry: dict[str, Any]) -> str:
    comparison = entry["comparison"]
    count = _count_who(comparison["payers_in_smaller"], entry["metric"])
    if comparison["larger"] == "equal":
        if comparison["payers_in_larger"] == comparison["payers_in_smaller"]:
            return f"with {count} in each group"
        return f"with {count} in {comparison['smaller']}, the group with fewer of them"
    return f"with {count} in the smaller group ({comparison['smaller']})"


def _roles_sentence(entry: dict[str, Any]) -> str | None:
    """Why the range of groups of unequal size covers both orders of the groups."""
    if entry["comparison"]["read_as"] != "both_orders":
        return None
    return (
        "In the simulated cases the arm is the group with the higher mean. The sample cannot be "
        "relied on to show which group that is (with few players who spend, the group with the "
        "higher mean seen can be the one with the lower true mean), so the ranges cover both "
        "orders: the arm the larger group, and control the larger group. With many players who "
        "spend the sign would be reliable, and the range is then wider than it needs to be."
    )


def _bottom_line(entry: dict[str, Any]) -> str:
    ranges = entry["simulated"]["ranges"]
    first, second = _order(entry)
    nominal = f"{percent(NOMINAL_RATE)[:-3]}%"
    failed = (
        f"failed in {_share_text(ranges[first])} of them with {_row_name(entry, first)} and in "
        f"{_share_text(ranges[second])} with {_row_name(entry, second)}."
    )
    if "error" in entry["estimate"]:
        return (
            f"{_interval_sentence(entry)} For comparisons like this one, Welch's 95% interval, "
            f"which should fail to contain the true difference in {nominal} of experiments, "
            f"{failed}"
        )
    text = (
        f"{_interval_sentence(entry)} An interval like it should fail to contain the true "
        f"difference in {nominal} of experiments; in Referee's simulations of comparisons "
        f"like this one it {failed}"
    )
    deciding = _deciding(entry)
    if deciding and max(found["high"] for found in deciding) * UNIT > NOMINAL_RATE:
        text += " Read the interval with those rates in mind."
    return text


def _around(entry: dict[str, Any], found: dict[str, Any]) -> str:
    """Where the cases of a range lie: beyond the comparison, at it, or on each side of it."""
    if found["extrapolated"]:
        return "nearest to it"
    comparison = entry["comparison"]
    split = (
        Fraction(1)
        if comparison["placed_as_equal"]
        else Fraction(comparison["split_numerator"], comparison["split_denominator"])
    )
    at_it = all(
        Fraction(case["split"]).limit_denominator(100) == split
        and case["payers"] == comparison["payers_in_smaller"]
        for case in found["cases"]
    )
    return "at it" if at_it else "on each side of it"


def _rates_sentences(entry: dict[str, Any]) -> list[str]:
    comparison = entry["comparison"]
    ranges = entry["simulated"]["ranges"]
    larger = {
        "equal": "the groups are the same size",
        "arm": f"{entry['arm']} is the larger group",
        "control": "control is the larger group",
    }[comparison["larger"]]
    split = _ratio(Fraction(comparison["split_numerator"], comparison["split_denominator"]))
    out = [f"This comparison is {split} to 1 ({larger}), {_payers_clause(entry)}."]
    if comparison["placed_as_equal"] and comparison["larger"] != "equal":
        out.append(
            f"Groups within {_ratio(EQUAL_ARMS_SPLIT)} to 1 of each other in size are placed "
            "among the simulated cases of groups of the same size. The rate rises with the "
            "split, so near that limit it can be higher than those cases show when the larger "
            "group is the one with the lower mean."
        )
    for effects in _order(entry):
        found = ranges[effects]
        text = (
            f"For {_row_name(entry, effects)}, the simulated cases {_around(entry, found)} "
            f"({_cases_text(found)}; {found['cells']} simulated settings, "
            f"{_tails_text(found['tail_weights'])}, at least {found['fewest_runs']:,} "
            f"experiments each) failed in {_share_text(found)} of experiments."
        )
        further = found["ends_from_further"]
        if found["far_apart"] and (further["low"] or further["high"]):
            ends = (
                "the ends of that range come"
                if further["low"] and further["high"]
                else f"the {'low' if further['low'] else 'high'} end of that range comes"
            )
            text += (
                f" These cases lie far apart, so {ends} from a case further from this "
                f"comparison than {_nearest_text(found['nearest_cases'])}."
            )
        out.append(text)
    for effects in _order(entry):
        beyond = _beyond_text(entry, effects, ranges[effects])
        if beyond is not None:
            out.append(beyond)
    roles = _roles_sentence(entry)
    if roles is not None:
        out.append(roles)
    out += _direction_text(entry)
    return out


def _kohavi_remark(entry: dict[str, Any]) -> str | None:
    """Kohavi et al.'s remark about equal groups, with its condition, and what to rely on."""
    comparison = entry["comparison"]
    if comparison is None or "kohavi" not in entry["signs"]:
        return None
    if Fraction(comparison["split_numerator"], comparison["split_denominator"]) > EQUAL_ARMS_SPLIT:
        return None
    text = (
        "Kohavi et al. (2014) note that when the two groups have the same distribution and "
        "equal sizes, the difference of the means is nearly symmetric and their size rule "
        "gives no useful bound."
    )
    if (entry["simulated"] or {}).get("ranges"):
        return f"{text} The simulated rates above, not that rule, are the guide here."
    return f"{text} That does not make the interval reliable: Referee has no simulation for this."


def _signs_lead(entry: dict[str, Any]) -> str:
    kind = "skewed" if entry["signs"] == ["kohavi"] else "heavy-tailed"
    where = _list([name for name, group in entry["groups"].items() if group["signs"]])
    return f"arm {entry['arm']}, metric {entry['metric']}: signs of a {kind} metric in {where}."


def _tripped_note(entry: dict[str, Any], pair: Pair, settings: dict[str, Any]) -> str:
    parts = [_signs_lead(entry)]
    simulated_ = entry["simulated"]
    comparison = entry["comparison"]
    if simulated_["reason"] is not None:
        parts.append(_interval_sentence(entry))
        parts.append(_REASONS_NOT_SIMULATED[simulated_["reason"]])
        if simulated_["reason"] == "unit_not_independent":
            parts.append(
                f"This spec randomises by {settings['randomization_unit']} and analyses by "
                f"{settings['analysis_unit']}."
            )
        if entry["signs"] == ["kohavi"]:
            parts.append(
                "The size rule is built to keep the total error of a 95% interval for one mean "
                "within 4% to 6% at the size it asks for; how this interval behaves here was "
                "not measured."
            )
    else:
        parts.append(_bottom_line(entry))
    for name, shape in ((pair.arm.arm, pair.arm), (pair.control.arm, pair.control)):
        parts.append(_group_sentence(name, shape, entry["metric"]))
    if simulated_["reason"] is None:
        parts.extend(_rates_sentences(entry))
        larger_payers = comparison["payers_in_larger"]
        if larger_payers < comparison["payers_in_smaller"]:
            who = _who(entry["metric"])
            fewer = f"The larger group has fewer {who} ({larger_payers:,}) than the smaller one"
            if comparison["placed_as_equal"]:
                parts.append(f"{fewer}.")  # the simulated groups were of one size
            else:
                parts.append(
                    f"{fewer}; the simulations gave both groups the same chance of spending, "
                    "so the larger group had more of them on average."
                )
    remark = _kohavi_remark(entry)
    if remark is not None:
        parts.append(remark)
    return " ".join(parts)


def _quiet_note(entry: dict[str, Any], pair: Pair) -> str:
    label = f"arm {entry['arm']}, metric {entry['metric']}"
    if entry["status"] == "not_evaluated":
        unread = [
            f"{name} could not be read ({_UNREAD[group['unread']]})"
            for name, group in entry["groups"].items()
            if group["unread"] is not None
        ]
        rest = "; the other group shows no sign" if len(unread) == 1 else ""
        return f"{label}: not evaluated: {_list(unread)}{rest}."
    groups = " ".join(
        _group_sentence(name, shape, entry["metric"])
        for name, shape in ((pair.arm.arm, pair.arm), (pair.control.arm, pair.control))
    )
    return (
        f"{label}: none of the three signs was found. {groups} This does not show that the "
        "interval is reliable."
    )


def _checked_note(settings: dict[str, Any], *, rates_quoted: bool) -> str:
    """The first note: what is read and the three signs. `rates_quoted` is whether any entry
    quotes simulated rates, and so whether the notes that explain them follow."""
    read = _list(settings["metrics_read"]) or "none"
    skipped = settings["metrics_not_read_binary"]
    tail = f" ({_list(skipped)} binary, not read)" if skipped else ""
    levels = (
        "In Referee's simulations of a revenue-like metric every run showed the first or the "
        "second sign, so the simulations cannot say whether the levels of the second and the "
        "third are the right ones"
    )
    if rates_quoted:
        levels += (
            ", though samples that showed them failed less often than the others (see the note "
            "on the rates). A setting, in the notes below, is one combination of group sizes, "
            "share of players who spend, effect and tail weight that was simulated"
        )
    return (
        "RES-008 reads each non-control arm against control on the analysed players, for "
        f"every metric of the spec that is not binary: {read}{tail}. It looks for three signs "
        "of a skewed or heavy-tailed metric in either group (skewness is how lopsided the "
        "values are, and excess kurtosis how heavy their tails are, 0 for a normal "
        "distribution). The first, which the notes call the size rule, is the rule of thumb "
        "of Kohavi, Deng, Longbotham and Xu (2014): for a sample skewness above 1 in size, a "
        f"group needs at least {KOHAVI_MULTIPLE} times the square of the skewness in players "
        "before the interval for its mean can be trusted (the rule is built to keep the total "
        "error of a 95% interval for one mean within 4% to 6%). The other two are Referee's "
        f"own levels: an excess kurtosis above {KURTOSIS_OVER}, and the top {TOP_PERCENT}% of "
        f"players holding more than {100 * TOP_SHARE_OVER:.0f}% of the total. {levels}. The "
        "figures shown are rounded to three or four significant figures, with more where that "
        "is needed to show that one is over its level; the decisions are made on the figures "
        "rounded to six places."
    )


_FAMILY_NOTE = (
    "The simulated family (design section 21.10): two arms of independent players and one look "
    "at a fixed number of players; most players spend nothing, and the rest (13% in most "
    "cases, 3% or 30% in some) spend an amount with a lognormal distribution, whose tail is "
    "mild, middle or heavy (log standard deviation 1.0, 1.5 or 2.0); an effect multiplies what "
    "the players who spend spend, and only positive effects were run, so the arm in a simulated "
    "case is the group with the higher mean; the interval is the unadjusted 95% Welch interval "
    "that Referee prints. The rates describe this family only: another shape of tail, an "
    "effect that works through the share of players who spend, or a metric that is not money "
    "may behave differently."
)
_NEARER_NOTE = (
    "Which effects are nearer the difference seen is decided on the higher mean over the lower "
    f"one: {100 * LARGE_EFFECT_FROM:.0f}% or more is nearer +50% and +100% (a lower mean of 0 "
    "counts as that), less is nearer none and +20%. That is a judgement at one level, so a "
    "difference close to it can switch which range sets the severity. With few players who "
    "spend the means seen often differ by that much even when the true effect is none or "
    "+20%, so the label is a weak guide to the true effect; both ranges are always printed. "
    "The severity follows the label, so with arms of about equal size an experiment with no "
    "effect can read as a warning and one with a large effect as info; Referee has not "
    "measured how often."
)
_NOISE_NOTE = (
    "A rate is a share of simulated experiments and carries noise: it is within about 0.3 "
    "points either way (a 95% range) near a rate of 5% and 0.7 points near 35% when a setting "
    "has 20,000 experiments, and within about 1 and 2 points when it has 2,000. A range is "
    "the lowest and the highest of the rates of several settings, so its ends are more "
    "extreme than the rate of any one setting would be; it is not an interval."
)
_ALL_RUNS_NOTE = (
    "The rates are over all the simulated experiments of a case. In nearly every setting "
    "where both kinds of sample were common (at least 200 experiments of each), those whose "
    f"sample showed an excess kurtosis above {KURTOSIS_OVER} failed less often than the "
    f"others, and so did those whose top share was above {100 * TOP_SHARE_OVER:.0f}% (each "
    "sign compared alone), so for a sample that shows one of these signs the rate may be "
    "lower than the range, and for a sample that looks lighter-tailed it may be higher. Every "
    "simulated experiment of a revenue-like metric showed the first or the second sign, so "
    "the range is also the rate among the experiments that show a sign."
)
_PAYERS_NOTE = (
    "Referee places a comparison among the simulated cases by the split between the groups and "
    "the number of players who spend in the smaller group, not the number of players: at 9 to 1 "
    "with no effect the rate followed that number in the simulations (design section 21.10); "
    "at other splits this was not checked. Above the largest number simulated the range of "
    "that case is used; where the simulated rate fell as the number grew, the true rate "
    "beyond it may be lower, so that range may be a ceiling and not a measure, and the "
    "severity it sets can stay a warning however many players spend."
)
_BOOTSTRAP_NOTE = (
    "Referee shows no bootstrap interval. In its simulations the percentile bootstrap interval "
    "failed more often than Welch's in most of the cells it was run on, so it is not a repair "
    "(design section 21.10)."
)


def _notes(
    entries: list[dict[str, Any]], pairs_: list[tuple[ExportMetric, Pair]], settings: dict[str, Any]
) -> list[str]:
    rates_quoted = any(_ranges_of(entry) for entry in entries)
    notes = [_checked_note(settings, rates_quoted=rates_quoted)]
    for entry, (_, pair) in zip(entries, pairs_, strict=True):
        notes.append(
            _tripped_note(entry, pair, settings)
            if entry["status"] == "tripped"
            else _quiet_note(entry, pair)
        )
    if rates_quoted:
        notes += [_FAMILY_NOTE, _NEARER_NOTE, _NOISE_NOTE, _ALL_RUNS_NOTE, _PAYERS_NOTE]
    if any(entry["status"] == "tripped" for entry in entries):
        notes.append(_BOOTSTRAP_NOTE)
    return notes


def heavy_tail_report(context: ResultsContext) -> dict[str, Any]:
    """The signs of a heavy tail for every non-control arm and non-binary metric of the spec.

    Metrics come in the spec's order (the primary metric, then the guardrails), arms inside
    each in the spec's order. The report has the keys of the cohort report except its `plans`:
    `summary`, `settings`, `tests` and `notes`.
    """
    found: list[tuple[ExportMetric, Pair]] = [
        (metric, pair)
        for metric in context.metrics.values()
        if metric.kind != "binary"
        for pair in pairs(context, metric)
    ]
    entries = [_entry(context, metric, pair) for metric, pair in found]
    summary = summarise(entries)
    settings = _settings(context)
    return {
        "summary": summary,
        "settings": settings,
        "tests": entries,
        "notes": _notes(entries, found, settings),
    }


__all__ = ["heavy_tail_report", "summarise"]
