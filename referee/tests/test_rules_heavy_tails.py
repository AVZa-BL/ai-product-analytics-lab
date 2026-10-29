"""RES-008: signs of a skewed or heavy-tailed metric (design section 21.11).

The exports are built by hand from seeded draws, so each scenario's outcome can be reasoned out
before it is run; the figures a note prints are checked against the evidence and the lookup.
"""

import json
import random
from fractions import Fraction
from pathlib import Path

import pytest
from cohort_helpers import THREE_ARMS
from results_helpers import TWO_ARMS, Row, build_data, crowd, results_spec

from referee.data import load_export
from referee.heavy_tails import DIGITS, KOHAVI_MULTIPLE, KURTOSIS_OVER, GroupShape
from referee.pooled_rates import EXCESS_RATE, NOMINAL_RATE, UNIT, hull, lookup, percent
from referee.results import ResultsContext
from referee.rules import RESULTS_RULES
from referee.rules.heavy_tails import (
    _cases_text,
    _count_who,
    _group_sentence,
    _measure,
    _nearest_text,
    _over,
    _plural,
    _ratio,
    _sig,
    _signed_percent,
    _tails_text,
    _who,
    heavy_tail_report,
)
from referee.rules.references import KOHAVI_ET_AL_2014
from referee.rules.results import _simulated_rate_is_high

RES_008 = next(rule for rule in RESULTS_RULES if rule.id == "RES-008")
REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 10.0,
}
SESSIONS_GUARDRAIL = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 3.0,
    "baseline_std": 2.0,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.1,
}
BANNED = ("novelty", "decay", "stable", "proves", "found no", "because of")
LAB = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _spenders(arm: str, n: int, seed: int, *, share: float = 0.13, sigma: float = 1.5) -> list[Row]:
    """`n` players of one arm: a share of them spend a lognormal amount, the rest nothing."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        spends = rng.random() < share
        value = rng.lognormvariate(1.0, sigma) if spends else 0.0
        rows.append(Row(f"{arm}_{i:05d}", arm, revenue=round(value, 4)))
    return rows


def _heavy_sessions() -> list[Row]:
    """Session counts of two arms of 300 players: 2% of them play 500 sessions, the rest 1 to 5."""
    rng = random.Random(8)
    return [
        Row(f"{arm}_{i:04d}", arm, sessions=500 if rng.random() < 0.02 else rng.randint(1, 5))
        for arm in ("control", "variant_b")
        for i in range(300)
    ]


def _context(raw_spec, rows: list[Row], *, arms=TWO_ARMS, **more) -> ResultsContext:
    spec = results_spec(raw_spec, arms=arms, **{**REVENUE, **more})
    return ResultsContext.of(spec, build_data(rows))


def _pair(
    raw_spec,
    *,
    n: int = 1000,
    seed: int = 1,
    control_copies: int = 1,
    variant_copies: int = 1,
    factor: float = 1.1,
    **more,
) -> ResultsContext:
    """Control and one variant made of the same `n` draws, so that the difference seen is exact.

    Control holds the draws `control_copies` times over, the variant holds them `variant_copies`
    times over and multiplied by `factor`, so the groups are in the ratio of the copies and the
    variant's mean is `factor` times control's.
    """
    base = [row.revenue for row in _spenders("control", n, seed)]
    rows = [
        Row(f"control_{i:06d}", "control", revenue=base[i % n]) for i in range(n * control_copies)
    ]
    rows += [
        Row(f"variant_b_{i:06d}", "variant_b", revenue=round(base[i % n] * factor, 6))
        for i in range(n * variant_copies)
    ]
    return _context(raw_spec, rows, **more)


def _equal(raw_spec, **more) -> ResultsContext:
    """Equal arms of 1,000, the variant's mean 10% above control's."""
    return _pair(raw_spec, **more)


def _three_to_one(raw_spec, **more) -> ResultsContext:
    """The variant three times the size of control (1,200 players, about 156 who spend)."""
    return _pair(raw_spec, n=1200, seed=3, variant_copies=3, **more)


def _evidence(context: ResultsContext) -> dict:
    finding = RES_008.evaluate(context)
    assert finding is not None
    return finding.evidence


# --- The rule as the catalogue states it ------------------------------------------------------


def test_the_rule_is_an_info_that_escalates_to_a_warning() -> None:
    assert (RES_008.severity, RES_008.escalation.to) == ("info", "warning")
    assert RES_008.references[0] == KOHAVI_ET_AL_2014
    assert RES_008.title.startswith("Skewed or heavy-tailed metric")
    for text in (RES_008.fires_when, RES_008.why_it_matters, RES_008.remediation, RES_008.title):
        assert text.isascii()
    assert RES_008.escalation.when.isascii()


@pytest.mark.parametrize(
    ("summary", "high"),
    [
        ({}, False),
        ({"largest_simulated_rate": None, "floor_ranges": 0}, False),
        ({"largest_simulated_rate": EXCESS_RATE / UNIT, "floor_ranges": 0}, False),  # 7.5%
        ({"largest_simulated_rate": (EXCESS_RATE + 1) / UNIT, "floor_ranges": 0}, True),
        ({"largest_simulated_rate": 0.03, "floor_ranges": 1}, True),  # a floor, whatever the rate
        ({"largest_simulated_rate": None, "floor_ranges": 2}, True),
    ],
)
def test_the_severity_rises_above_one_and_a_half_times_the_level_or_for_a_floor(
    summary: dict, high: bool
) -> None:
    assert _simulated_rate_is_high({"summary": summary}) is high
    assert _simulated_rate_is_high({}) is False
    assert RES_008.finding({"summary": summary}).severity == ("warning" if high else "info")
    assert RES_008.finding({}).severity == "info"


# --- What it finds ----------------------------------------------------------------------------


def test_equal_arms_with_a_small_difference_seen_are_an_info(raw_spec) -> None:
    finding = RES_008.evaluate(_equal(raw_spec))

    assert finding is not None and finding.severity == "info"
    evidence = finding.evidence
    assert set(evidence) == {"summary", "settings", "tests", "notes"}
    (entry,) = evidence["tests"]
    assert (entry["arm"], entry["metric"], entry["status"]) == (
        "variant_b",
        "revenue_usd_7d",
        "tripped",
    )
    assert entry["family"] == "revenue_like" and "kohavi" in entry["signs"]
    assert entry["relative_difference"] == pytest.approx(0.1, abs=1e-5)
    assert entry["nearer_effects"] == "small"
    comparison = entry["comparison"]
    assert comparison["larger"] == "equal" and comparison["split"] == 1.0
    assert comparison["payers_in_smaller"] == min(g["payers"] for g in entry["groups"].values())
    ranges = entry["simulated"]["ranges"]
    assert ranges["small"]["nearer"] is True and ranges["large"]["nearer"] is False
    assert ranges["small"]["high"] <= EXCESS_RATE / UNIT < ranges["large"]["high"]
    summary = evidence["summary"]
    assert summary["largest_simulated_rate"] == ranges["small"]["high"]  # the nearer row decides
    assert summary["largest_printed_rate"] == ranges["large"]["high"]


def test_equal_arms_with_a_large_difference_seen_are_a_warning(raw_spec) -> None:
    finding = RES_008.evaluate(_equal(raw_spec, factor=1.6))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    assert entry["nearer_effects"] == "large" and entry["relative_difference"] > 0.35
    large = entry["simulated"]["ranges"]["large"]
    assert large["nearer"] is True and large["high"] > EXCESS_RATE / UNIT
    assert finding.evidence["summary"]["largest_simulated_rate"] == large["high"]


def test_a_lower_mean_is_read_by_the_effect_in_the_terms_of_the_study(raw_spec) -> None:
    # the variant has half of control's mean: -50% of it, an effect of +100% as the study has it
    finding = RES_008.evaluate(_equal(raw_spec, factor=0.5))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    assert entry["relative_difference"] == pytest.approx(-0.5, abs=1e-5)
    assert entry["effect_seen"] == pytest.approx(1.0, abs=1e-5)
    assert entry["nearer_effects"] == "large" and entry["comparison"]["read_as"] == "equal"
    text = " ".join(finding.evidence["notes"])
    assert (
        "The difference seen is -50% of control's mean, which is +100% in the terms of the "
        "simulations (the higher mean over the lower one)."
    ) in text


@pytest.mark.parametrize("grouping", ["equal", "three_to_one"])
def test_swapping_which_group_is_control_changes_nothing(raw_spec, grouping: str) -> None:
    """The same two groups, the labels exchanged: -30% of control's mean is +43% as the study
    has it, and is read as the +43% is (it was once read as a small effect)."""
    if grouping == "equal":
        up, down = _equal(raw_spec, factor=1.43), _equal(raw_spec, factor=1 / 1.43)
    else:
        up = _three_to_one(raw_spec, factor=1.43)
        down = _pair(raw_spec, n=1200, seed=3, control_copies=3, factor=1 / 1.43)

    found = [RES_008.evaluate(context) for context in (up, down)]

    assert all(finding is not None and finding.severity == "warning" for finding in found)
    (a,), (b,) = (finding.evidence["tests"] for finding in found)
    assert a["relative_difference"] > 0.42 and -0.31 < b["relative_difference"] < -0.29
    assert a["effect_seen"] == pytest.approx(b["effect_seen"], abs=1e-4)
    assert a["effect_seen"] == pytest.approx(0.43, abs=1e-3)
    assert a["nearer_effects"] == b["nearer_effects"] == "large"
    assert a["comparison"]["read_as"] == b["comparison"]["read_as"]
    assert a["simulated"]["ranges"] == b["simulated"]["ranges"]
    assert "-30% of control's mean, which is +43% in the terms" in " ".join(
        found[1].evidence["notes"]
    )


@pytest.mark.parametrize("control_copies", [1, 3])
@pytest.mark.parametrize("factor", [0.9, 1.1, 0.5, 1.6])
def test_unequal_groups_are_read_in_both_orders_whichever_is_larger_or_higher(
    raw_spec, control_copies: int, factor: float
) -> None:
    """The sample does not say which group has the higher mean in truth, so the range covers
    both orders: the same range for either group the larger and either difference."""
    context = _pair(
        raw_spec,
        n=1200,
        seed=3,
        control_copies=control_copies,
        variant_copies=4 - control_copies,
        factor=factor,
    )

    finding = RES_008.evaluate(context)

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    assert entry["comparison"]["read_as"] == "both_orders" and entry["comparison"]["split"] == 3.0
    for effects, found in entry["simulated"]["ranges"].items():
        both = hull(
            lookup(effects, "arm", Fraction(3), 159), lookup(effects, "control", Fraction(3), 159)
        )
        assert (found["low"], found["high"]) == (both.low / UNIT, both.high / UNIT)
    text = " ".join(finding.evidence["notes"])
    assert (
        "In the simulated cases the arm is the group with the higher mean. The sample cannot be "
        "relied on to show which group that is (with few players who spend, the group with the "
        "higher mean seen can be the one with the lower true mean), so the ranges cover both "
        "orders: the arm the larger group, and control the larger group. With many players who "
        "spend the sign would be reliable, and the range is then wider than it needs to be."
    ) in text
    assert "Control has the higher mean" not in text


def test_groups_within_five_to_four_are_placed_among_groups_of_one_size(raw_spec) -> None:
    finding = RES_008.evaluate(_sized(raw_spec, 1200))

    assert finding is not None and finding.severity == "info"
    (entry,) = finding.evidence["tests"]
    comparison = entry["comparison"]
    assert comparison["larger"] == "arm" and comparison["split"] == 1.2
    assert comparison["placed_as_equal"] and comparison["read_as"] == "equal"
    for effects, found in entry["simulated"]["ranges"].items():
        equal = lookup(effects, "equal", Fraction(1), comparison["payers_in_smaller"])
        assert (found["low"], found["high"]) == (equal.low / UNIT, equal.high / UNIT)
    text = " ".join(finding.evidence["notes"])
    assert (
        "Groups within 1.25 to 1 of each other in size are placed among the simulated cases of "
        "groups of the same size."
    ) in text
    assert "The sample cannot be relied on to show which group" not in text


def test_the_same_split_with_a_small_difference_is_a_warning(raw_spec) -> None:
    finding = RES_008.evaluate(_three_to_one(raw_spec))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    assert entry["comparison"]["read_as"] == "both_orders"
    assert entry["simulated"]["ranges"]["small"]["high"] > EXCESS_RATE / UNIT


def test_a_variant_far_larger_than_control_is_beyond_the_cases_and_a_floor(raw_spec) -> None:
    finding = RES_008.evaluate(_pair(raw_spec, variant_copies=19))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    small = entry["simulated"]["ranges"]["small"]
    assert small["extrapolated"] == ["split_above_range"] and small["floor"] is True
    assert finding.evidence["summary"]["floor_ranges"] == 1  # only the nearer row counts
    text = " ".join(finding.evidence["notes"])
    assert "the split is above the largest simulated (9 to 1)" in text
    assert "the true rate is probably above this range" in text


def test_only_the_floors_of_the_nearer_effects_are_counted(raw_spec) -> None:
    finding = RES_008.evaluate(_pair(raw_spec, variant_copies=19, factor=1.1))
    other = RES_008.evaluate(_pair(raw_spec, variant_copies=19, factor=1.6))

    assert finding is not None and other is not None
    (near_small,) = finding.evidence["tests"]
    (near_large,) = other.evidence["tests"]
    assert near_small["simulated"]["ranges"]["large"]["floor"] is False  # 19 to 1: the large grid
    assert finding.evidence["summary"]["floor_ranges"] == 1
    assert near_large["nearer_effects"] == "large"
    assert near_large["simulated"]["ranges"]["large"]["extrapolated"] == ["split_above_range"]
    assert other.evidence["summary"]["floor_ranges"] == 0  # the large grid fell towards 9 to 1


def _expected_range(comparison: dict, effects: str):
    split = Fraction(comparison["split_numerator"], comparison["split_denominator"])
    payers = comparison["payers_in_smaller"]
    if comparison["read_as"] == "both_orders":
        return hull(
            lookup(effects, "arm", split, payers), lookup(effects, "control", split, payers)
        )
    return lookup(effects, "equal", Fraction(1), payers)


@pytest.mark.parametrize("scenario", ["equal", "near_equal", "three_to_one", "nineteen_to_one"])
def test_the_ranges_in_the_evidence_are_those_of_the_lookup(raw_spec, scenario: str) -> None:
    context = {
        "equal": lambda: _equal(raw_spec),
        "near_equal": lambda: _sized(raw_spec, 1200),
        "three_to_one": lambda: _three_to_one(raw_spec, factor=1.6),
        "nineteen_to_one": lambda: _pair(raw_spec, variant_copies=19),
    }[scenario]()
    (entry,) = _evidence(context)["tests"]
    comparison = entry["comparison"]
    assert comparison["read_as"] == ("both_orders" if "to_one" in scenario else "equal")

    for effects, found in entry["simulated"]["ranges"].items():
        expected = _expected_range(comparison, effects)
        assert found["low"] == expected.low / UNIT and found["high"] == expected.high / UNIT
        assert found["cells"] == expected.cells and found["floor"] == expected.floor_only
        assert found["extrapolated"] == list(expected.extrapolated)
        assert found["rising"] == list(expected.rising)
        assert found["tail_weights"] == list(expected.tails)
        assert found["fewest_runs"] == expected.min_runs
        assert [(c["payers"], round(c["low"] * UNIT)) for c in found["cases"]] == [
            (c.payers, c.low) for c in expected.cases
        ]


def test_a_count_metric_gets_its_signs_and_no_error_rate(raw_spec) -> None:
    context = _context(raw_spec, _heavy_sessions(), primary_metric__name="sessions_7d")

    finding = RES_008.evaluate(context)

    assert finding is not None and finding.severity == "info"
    (entry,) = finding.evidence["tests"]
    assert entry["family"] == "count" and entry["status"] == "tripped"
    assert entry["simulated"] == {"reason": "metric_not_simulated", "ranges": None}
    assert finding.evidence["summary"]["largest_simulated_rate"] is None
    text = " ".join(finding.evidence["notes"])
    assert "states no error rate for this metric" in text
    assert "The simulated family" not in text
    assert "within 4% to 6% at the size it asks for; how this interval behaves here was" in text
    assert "players with a value other than 0" in text
    first = finding.evidence["notes"][0]  # nothing explains rates that are not quoted
    assert "see the note on the rates" not in first and "A setting, in the notes below" not in first


def test_units_that_are_not_independent_players_get_no_error_rate(raw_spec) -> None:
    context = _equal(raw_spec, population__randomization_unit="session")

    (entry,) = _evidence(context)["tests"]

    assert entry["status"] == "tripped"
    assert entry["simulated"] == {"reason": "unit_not_independent", "ranges": None}
    text = " ".join(_evidence(context)["notes"])
    assert "independent players" in text
    assert "This spec randomises by session and analyses by player." in text
    first = _evidence(context)["notes"][0]
    assert "see the note on the rates" not in first and "A setting, in the notes below" not in first


# --- Groups that cannot be read, and pairs with no sign ---------------------------------------


def test_a_pair_that_cannot_be_read_and_shows_no_sign_is_counted_but_does_not_fire(
    raw_spec,
) -> None:
    rows = crowd("variant_b", 50, revenue=0.0) + _spenders("control", 400, 9, sigma=0.2, share=1.0)
    context = _context(raw_spec, rows)

    report = heavy_tail_report(context)

    assert RES_008.evaluate(context) is None
    (entry,) = report["tests"]
    assert entry["status"] == "not_evaluated"
    assert entry["groups"]["variant_b"]["unread"] == "all_zero"
    assert (
        entry["groups"]["control"]["unread"] is None and entry["groups"]["control"]["signs"] == []
    )
    assert report["summary"]["not_evaluated"] == 1 and report["summary"]["tripped"] == 0
    assert report["summary"]["line"].startswith(
        "RES-008: 1 comparison (binary metrics are not read), 0 with a sign of a heavy tail, "
        "1 not evaluated. No sign is not a pass"
    )
    assert "arm variant_b, metric revenue_usd_7d: not evaluated: variant_b could not be read" in (
        " ".join(report["notes"])
    )


def test_an_unreadable_arm_does_not_hide_a_heavy_tailed_control(raw_spec) -> None:
    rows = crowd("variant_b", 50, revenue=0.0) + _spenders("control", 1000, 10)

    finding = RES_008.evaluate(_context(raw_spec, rows))

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert entry["status"] == "tripped" and entry["groups"]["variant_b"]["unread"] == "all_zero"
    text = " ".join(finding.evidence["notes"])
    assert "variant_b: 50 analysed players, 0 players who spend, could not be read" in text
    assert "every value is 0" in text


def test_a_pair_with_no_sign_is_reported_in_a_fired_finding_without_calling_it_reliable(
    raw_spec,
) -> None:
    context = _context(
        raw_spec,
        _equal_sessions_rows(),
        guardrails=[SESSIONS_GUARDRAIL],
    )

    report = heavy_tail_report(context)

    assert [(e["metric"], e["status"]) for e in report["tests"]] == [
        ("revenue_usd_7d", "tripped"),
        ("sessions_7d", "not_tripped"),
    ]
    note = next(n for n in report["notes"] if "metric sessions_7d" in n)
    assert note.startswith("arm variant_b, metric sessions_7d: none of the three signs was found.")
    assert note.endswith("This does not show that the interval is reliable.")


def _equal_sessions_rows() -> list[Row]:
    rows = _spenders("control", 1000, 1) + _spenders("variant_b", 1000, 2)
    for i, row in enumerate(rows):
        row.sessions = 3 + i % 5
    return rows


def test_binary_metrics_are_not_read(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)  # a binary primary metric, no guardrails
    context = ResultsContext.of(
        spec, build_data(_spenders("control", 50, 1) + _spenders("variant_b", 50, 2))
    )

    report = heavy_tail_report(context)

    assert RES_008.evaluate(context) is None
    assert report["tests"] == [] and report["summary"]["tests"] == 0
    assert report["summary"]["line"].startswith(
        "RES-008: 0 comparisons (binary metrics are not read), 0 with"
    )
    assert report["settings"]["metrics_read"] == []
    assert report["settings"]["metrics_not_read_binary"] == ["purchased_7d"]


def test_a_binary_guardrail_is_not_read_beside_a_continuous_primary_metric(raw_spec) -> None:
    guardrail = {
        "name": "purchased_7d",
        "kind": "binary",
        "baseline": 0.05,
        "harmful_direction": "decrease",
        "tolerance_relative": 0.1,
    }
    context = _context(
        raw_spec,
        _spenders("control", 400, 1) + _spenders("variant_b", 400, 2),
        guardrails=[guardrail],
    )

    report = heavy_tail_report(context)

    assert [e["metric"] for e in report["tests"]] == ["revenue_usd_7d"]
    assert report["settings"]["metrics_read"] == ["revenue_usd_7d"]
    assert report["settings"]["metrics_not_read_binary"] == ["purchased_7d"]


def test_metrics_come_first_and_arms_in_the_spec_order_inside_each(raw_spec) -> None:
    rows = (
        _spenders("variant_c", 400, 11)
        + _spenders("control", 400, 12)
        + _spenders("variant_b", 400, 13)
    )
    context = _context(raw_spec, rows, arms=THREE_ARMS, guardrails=[SESSIONS_GUARDRAIL])

    report = heavy_tail_report(context)

    assert [(e["metric"], e["arm"]) for e in report["tests"]] == [
        ("revenue_usd_7d", "variant_b"),
        ("revenue_usd_7d", "variant_c"),
        ("sessions_7d", "variant_b"),
        ("sessions_7d", "variant_c"),
    ]
    assert report["summary"]["tests"] == 4
    assert report["summary"]["line"].startswith("RES-008: 4 comparisons")


def test_the_report_is_deterministic_and_plain_json(raw_spec) -> None:
    context = _equal(raw_spec, guardrails=[SESSIONS_GUARDRAIL])

    first = heavy_tail_report(context)
    second = heavy_tail_report(context)

    assert first == second
    assert json.loads(json.dumps(first, allow_nan=False)) == first


@pytest.mark.parametrize("scenario", ["_equal", "_three_to_one"])
def test_every_note_is_ascii_and_names_no_cause(raw_spec, scenario: str) -> None:
    context = globals()[scenario](raw_spec, guardrails=[SESSIONS_GUARDRAIL])

    for note in heavy_tail_report(context)["notes"]:
        assert note.isascii(), note
        assert not any(word in note.lower() for word in BANNED), note
        assert "\n" not in note


# --- What the notes print ---------------------------------------------------------------------


def test_the_note_of_a_tripped_entry_prints_the_measures_and_the_rates_of_the_evidence(
    raw_spec,
) -> None:
    evidence = _evidence(_equal(raw_spec))
    (entry,) = evidence["tests"]
    note = next(
        n for n in evidence["notes"] if n.startswith("arm variant_b, metric revenue_usd_7d")
    )
    ranges = entry["simulated"]["ranges"]

    for effects in ("small", "large"):
        found = ranges[effects]
        assert (
            f"{percent(round(found['low'] * UNIT))} to {percent(round(found['high'] * UNIT))}"
            in note
        )
        assert f"{found['cells']} simulated settings" in note
        assert f"at least {found['fewest_runs']:,} experiments each)" in note
    for name, group in entry["groups"].items():
        assert (
            f"{name}: {group['n']:,} analysed players, {group['payers']:,} players who spend"
            in note
        )
    low, high = entry["estimate"]["ci_low"], entry["estimate"]["ci_high"]
    assert "Welch's 95% interval for the difference (variant_b less control) is " in note
    assert note.count(" to ") >= 3 and isinstance(low, float) and isinstance(high, float)
    assert (
        "An interval like it should fail to contain the true difference in 5% of experiments"
        in note
    )
    assert note.index("An interval like it") < note.index("variant_b: 1,000 analysed players")


def test_the_direction_is_said_in_the_readers_terms(raw_spec) -> None:
    equal = " ".join(_evidence(_equal(raw_spec))["notes"])
    unequal = " ".join(_evidence(_three_to_one(raw_spec))["notes"])

    assert "most of the failed intervals in the simulations understated the gap" in equal
    assert "made the larger group look better than it is; here the larger group is variant_b" in (
        unequal
    )
    assert "understated" not in unequal and "better than it is" not in equal


def test_when_control_is_the_larger_group_the_note_names_control(raw_spec) -> None:
    notes = " ".join(
        _evidence(_pair(raw_spec, n=1200, seed=3, control_copies=3, factor=1.6))["notes"]
    )

    assert "control is the larger group" in notes
    assert "here the larger group is control" in notes


def test_unequal_groups_get_no_direction_for_a_large_effect(raw_spec) -> None:
    for context in (
        _three_to_one(raw_spec, factor=1.6),
        _pair(raw_spec, n=1200, seed=3, control_copies=3, factor=1.6),
    ):
        notes = " ".join(_evidence(context)["notes"])

        assert "made the larger group look better than it is" in notes  # the small row
        assert "understated" not in notes  # the study showed a side for equal groups only
        assert "the group with the lower mean the larger one" not in notes


def test_kohavis_remark_about_equal_arms_comes_with_its_condition(raw_spec) -> None:
    equal = _evidence(_equal(raw_spec))
    unequal = " ".join(_evidence(_three_to_one(raw_spec))["notes"])
    count = " ".join(
        _evidence(_context(raw_spec, _heavy_sessions(), primary_metric__name="sessions_7d"))[
            "notes"
        ]
    )
    text = " ".join(equal["notes"])

    assert "Kohavi et al. (2014) note that when the two groups have the same distribution" in text
    assert "equal sizes, the difference of the means is nearly symmetric" in text
    assert "The simulated rates above, not that rule, are the guide here." in text
    assert "Kohavi et al. (2014) note" not in unequal
    assert "That does not make the interval reliable: Referee has no simulation for this." in count
    assert "The simulated rates above" not in count


def test_a_larger_group_with_fewer_players_who_spend_is_said(raw_spec) -> None:
    control = _spenders("control", 1000, 16, share=0.13)
    variant = _spenders("variant_b", 1100, 17, share=0.05)

    notes = " ".join(_evidence(_context(raw_spec, control + variant))["notes"])

    assert "The larger group has fewer players who spend" in notes
    # 1.1 to 1: placed among groups of one size, where there is no larger group to speak of
    assert "always had more of them" not in notes and "had more of them on average" not in notes
    unequal = " ".join(
        _evidence(
            _context(
                raw_spec,
                _spenders("control", 500, 16, share=0.13)
                + _spenders("variant_b", 2000, 17, share=0.02),
            )
        )["notes"]
    )
    assert "The larger group has fewer players who spend" in unequal
    assert (
        "the simulations gave both groups the same chance of spending, so the larger group had "
        "more of them on average."
    ) in unequal
    assert "always had more" not in unequal


def test_the_fixed_notes_are_printed_once_and_only_when_they_apply(raw_spec) -> None:
    both = heavy_tail_report(_equal(raw_spec))["notes"]
    count = heavy_tail_report(
        _context(raw_spec, _heavy_sessions(), primary_metric__name="sessions_7d")
    )["notes"]

    for marker in (
        "The simulated family (design section 21.10)",
        "A rate is a share of simulated experiments",
        "The rates are over all the simulated experiments of a case.",
        "Referee places a comparison among the simulated cases by the split",
        "Referee shows no bootstrap interval.",
        "RES-008 reads each non-control arm against control",
        "Which effects are nearer the difference seen is decided on the higher mean over the "
        "lower one: 35% or more is nearer +50% and +100% (a lower mean of 0 counts as that), "
        "less is nearer none and +20%.",
    ):
        assert sum(marker in note for note in both) == 1, marker
    assert any("Referee shows no bootstrap interval." in n for n in count)
    assert not any("The simulated family" in n for n in count)
    assert not any("Which effects are nearer" in n for n in count)
    assert sum("Kohavi, Deng, Longbotham and Xu (2014)" in n for n in both) == 1


def test_the_first_note_says_what_the_terms_of_the_other_notes_mean(raw_spec) -> None:
    first = heavy_tail_report(_equal(raw_spec))["notes"][0]

    assert (
        "(skewness is how lopsided the values are, and excess kurtosis how heavy their tails "
        "are, 0 for a normal distribution)"
    ) in first
    assert (
        "A setting, in the notes below, is one combination of group sizes, share of players "
        "who spend, effect and tail weight that was simulated."
    ) in first
    assert "though samples that showed them failed less often than the others" in first
    assert (
        "rounded to three or four significant figures, with more where that is needed to show "
        "that one is over its level; the decisions are made on the figures rounded to six places."
    ) in " ".join(first.split())


# --- The committed export of the lab ----------------------------------------------------------


def _lab(raw_spec) -> ResultsContext:
    spec = results_spec(raw_spec, **REVENUE, design__mde_relative=0.3)
    return ResultsContext.of(spec, load_export(LAB, "hybrid_offer_page"))


def test_the_lab_export_trips_every_sign_in_every_group_of_revenue(raw_spec) -> None:
    arms_three = results_spec(
        raw_spec, **REVENUE, design__mde_relative=0.3
    )  # variant_b, variant_c and control, as the lab ran them
    context = ResultsContext.of(arms_three, load_export(LAB, "hybrid_offer_page"))

    finding = RES_008.evaluate(context)

    assert finding is not None and finding.severity == "warning"
    for entry in finding.evidence["tests"]:
        assert entry["status"] == "tripped" and entry["signs"] == [
            "kohavi",
            "kurtosis",
            "top_share",
        ]
        for group in entry["groups"].values():
            assert group["signs"] == ["kohavi", "kurtosis", "top_share"]
            assert (
                group["n"] < group["kohavi_minimum"] / 10
            )  # asks for ten times the players or more
    by_arm = {e["arm"]: e for e in finding.evidence["tests"]}
    assert by_arm["variant_b"]["comparison"]["payers_in_smaller"] == 124  # control's
    assert by_arm["variant_b"]["comparison"]["smaller"] == "control"
    assert by_arm["variant_c"]["comparison"]["smaller"] == "variant_c"
    assert by_arm["variant_c"]["comparison"]["larger"] == "control"


def test_the_lab_exports_session_counts_show_no_sign(raw_spec) -> None:
    context = ResultsContext.of(
        results_spec(
            raw_spec, **REVENUE, design__mde_relative=0.3, guardrails=[SESSIONS_GUARDRAIL]
        ),
        load_export(LAB, "hybrid_offer_page"),
    )

    report = heavy_tail_report(context)

    assert {(e["metric"], e["status"]) for e in report["tests"]} == {
        ("revenue_usd_7d", "tripped"),
        ("sessions_7d", "not_tripped"),
    }


# --- The fixed sentences and the small formatters, word for word -------------------------------


def _notes(raw_spec, scenario) -> str:
    return " ".join(heavy_tail_report(scenario(raw_spec))["notes"])


def test_the_sentences_about_the_runs_and_the_bootstrap_say_which_way_the_study_went(
    raw_spec,
) -> None:
    text = _notes(raw_spec, _equal)

    assert (
        "In nearly every setting where both kinds of sample were common (at least 200 "
        "experiments of each), those whose sample showed an excess kurtosis above 100 failed "
        "less often than the others, and so did those whose top share was above 50% (each sign "
        "compared alone), so for a sample that shows one of these signs the rate may be lower "
        "than the range, and for a sample that looks lighter-tailed it may be higher."
    ) in text
    assert (
        "Every simulated experiment of a revenue-like metric showed the first or the second "
        "sign, so the range is also the rate among the experiments that show a sign."
    ) in text
    assert (
        "the percentile bootstrap interval failed more often than Welch's in most of the cells "
        "it was run on, so it is not a repair (design section 21.10)."
    ) in text
    assert (
        "at 9 to 1 with no effect the rate followed that number in the simulations (design "
        "section 21.10); at other splits this was not checked."
    ) in text


def test_the_figures_the_texts_restate_are_those_of_the_code_and_the_simulations() -> None:
    from cohort_simulation import BASE, PAYING, SPEND_SD
    from pooled_simulation import PAYER_SHARES

    from referee.cohort_effects import FADE_MAX_ALLOCATION_RATIO
    from referee.heavy_tails import EQUAL_ARMS_SPLIT
    from referee.rules.cohorts import _FADE_KINDS
    from referee.rules.heavy_tails import _FAMILY_NOTE

    low, high = PAYER_SHARES
    first, second, third = (f"{sd:.1f}" for sd in SPEND_SD.values())
    assert f"rounded to {DIGITS} places" in RES_008.fires_when
    assert f"({PAYING:.0%} in most cases, {low:.0%} or {high:.0%} in some)" in _FAMILY_NOTE
    assert f"(log standard deviation {first}, {second} or {third})" in _FAMILY_NOTE
    assert _FADE_KINDS["binary"] == f"a binary metric at a rate of {BASE['binary']:.0%}"
    assert EQUAL_ARMS_SPLIT == Fraction(FADE_MAX_ALLOCATION_RATIO)  # the same limit in RES-007


def test_the_family_and_the_noise_are_described_as_the_study_made_them(raw_spec) -> None:
    text = _notes(raw_spec, _equal)

    assert (
        "most players spend nothing, and the rest (13% in most cases, 3% or 30% in some) spend "
        "an amount with a lognormal distribution, whose tail is mild, middle or heavy (log "
        "standard deviation 1.0, 1.5 or 2.0)"
    ) in text
    assert (
        "an effect multiplies what the players who spend spend, and only positive effects were run"
    ) in text
    assert (
        "within about 0.3 points either way (a 95% range) near a rate of 5% and 0.7 points "
        "near 35% when a setting has 20,000 experiments, and within about 1 and 2 points when "
        "it has 2,000. A range is the lowest and the highest of the rates of several settings, "
        "so its ends are more extreme than the rate of any one setting would be; it is not an "
        "interval."
    ) in text
    assert "so the arm in a simulated case is the group with the higher mean" in text
    assert "within 4% to 6%" in text and "an excess kurtosis above 100" in text
    assert "the top 1% of players holding more than 50% of the total" in text


def test_the_direction_sentences_name_the_effects_they_are_about(raw_spec) -> None:
    equal = _notes(raw_spec, _equal)
    unequal = _notes(raw_spec, _three_to_one)

    assert (
        "With an effect of +50% or +100% and groups of about equal size, most of the failed "
        "intervals in the simulations understated the gap between the groups."
    ) in equal
    assert (
        "With an effect of none or +20% and groups of unequal size, most of the failed "
        "intervals in the simulations made the larger group look better than it is"
    ) in unequal


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("too_few_players", "it has fewer than 2 analysed players"),
        ("all_zero", "every value is 0"),
        ("no_variation", "every value is the same"),
        ("negative_value", "it holds a negative value"),
        ("not_computable", "its values are not finite, or too large or too small to measure"),
    ],
)
def test_every_reason_a_group_cannot_be_read_has_its_own_words(reason: str, text: str) -> None:
    from referee.rules.heavy_tails import _UNREAD

    assert _UNREAD[reason] == text
    assert set(_UNREAD) == {
        "too_few_players",
        "all_zero",
        "no_variation",
        "negative_value",
        "not_computable",
    }


def test_the_reasons_a_comparison_is_unsimulated_and_the_directions_beyond_the_grid_are_worded(
    raw_spec,
) -> None:
    rows = _spenders("control", 20, 5) + _spenders("variant_b", 20, 6)  # few who spend
    few = " ".join(
        _evidence(_context(raw_spec, rows, population__randomization_unit="player"))["notes"]
    )
    above = " ".join(_evidence(_three_to_one(raw_spec))["notes"])

    assert "there are fewer players who spend than in the cases simulated at this split" in few
    assert "there are more players who spend than in the cases simulated at this split" in above
    assert "this comparison lies beyond the simulated cases: there are more" in above
    assert "the simulations do not show which way the rate goes there, so Referee does not" in above


def test_the_small_formatters_print_what_the_notes_rely_on() -> None:
    assert [
        _ratio(Fraction(n, d)) for n, d in ((1, 1), (3, 2), (9, 1), (969, 926), (5, 4), (1000, 1))
    ] == ["1", "1.5", "9", "1.05", "1.25", "1,000"]
    assert [_measure(v) for v in (1.134, 11.54, 99.96, 100.4, 462.6, 12345.6)] == [
        "1.134",
        "11.54",
        "99.96",
        "100.4",
        "462.6",
        "12,350",
    ]
    assert [
        _sig(v) for v in (0, 1.673, -0.247, 131649, 0.00005123, -0.00005123, 9.996, 1234.5)
    ] == [
        "0",
        "1.67",
        "-0.247",
        "132,000",
        "0.0000512",
        "-0.0000512",
        "10.0",
        "1,230",
    ]
    assert _tails_text([3, 3]) == "over all three tail weights"
    assert _tails_text([2, 2]) == "over two of the three tail weights"
    assert _tails_text([2, 3]) == "over two or three of the three tail weights"
    assert [_plural(n, "player") for n in (0, 1, 2, 1234)] == [
        "0 players",
        "1 player",
        "2 players",
        "1,234 players",
    ]
    assert [_count_who(n, "revenue_like") for n in (0, 1, 2)] == [
        "0 players who spend",
        "1 player who spends",
        "2 players who spend",
    ]
    assert [_count_who(n, "count") for n in (1, 3)] == [
        "1 player with a value other than 0",
        "3 players with a value other than 0",
    ]
    assert _who("revenue_like") == "players who spend"
    assert _who("count") == "players with a value other than 0"
    cases = {
        "cases": [
            {"split": 1.0, "payers": 130},
            {"split": 3.0, "payers": 13},
            {"split": 1.0, "payers": 13},
        ]
    }
    assert _cases_text(cases) == (
        "splits 1 to 1 (13 and 130 players who spend) and 3 to 1 (13 players who spend)"
    )
    same_counts = {
        "cases": [
            {"split": 1.0, "payers": 90},
            {"split": 1.5, "payers": 130},
            {"split": 1.0, "payers": 130},
            {"split": 1.5, "payers": 90},
        ]
    }
    assert (
        _cases_text(same_counts) == "splits 1 to 1 and 1.5 to 1 with 90 and 130 players who spend"
    )
    assert _cases_text({"cases": [{"split": 1.5, "payers": 1300}]}) == (
        "split 1.5 to 1 with 1,300 players who spend"
    )


def test_the_note_prints_the_shares_and_the_units_of_the_groups(raw_spec) -> None:
    evidence = _evidence(_equal(raw_spec, guardrails=[SESSIONS_GUARDRAIL]))
    note = next(n for n in evidence["notes"] if n.startswith("arm variant_b, metric revenue"))
    (entry,) = [e for e in evidence["tests"] if e["metric"] == "revenue_usd_7d"]

    for group in entry["groups"].values():
        top = f"the top {group['top_count']:,} players (1% of them, rounded up)"
        assert "top_share" in group["signs"]
        shown = _over(100 * group["top_share"], 50, 3)
        assert f"{top} hold {shown}% of the total (above 50%: a sign)" in note
        assert f"skewness {_measure(group['skewness'])}" in note
        assert f"excess kurtosis {_measure(group['excess_kurtosis'])}" in note
        assert f"about {_sig(group['kohavi_minimum'])} players (a sign)" in note
    assert " USD per player." in note
    assert (
        evidence["settings"]["nominal_rate"] == 0.05
        and evidence["settings"]["excess_rate"] == 0.075
    )
    assert evidence["settings"]["equal_arms_up_to_split"] == 1.25
    assert evidence["settings"]["unit_class"] == {"randomization": "person", "analysis": "person"}


@pytest.mark.parametrize(
    ("value", "level", "digits", "shown"),
    [
        (462.6, 100, 4, "462.6"),  # far over: the usual digits
        (100.4, 100, 4, "100.4"),
        (100.04, 100, 4, "100.04"),  # 4 figures give 100.0, which does not look over 100
        (100.000001, 100, 4, "100.000001"),
        (50.04, 50, 3, "50.04"),
        (50.0001, 50, 3, "50.0001"),
        (100.0, 50, 3, "100"),
    ],
)
def test_a_figure_over_its_level_is_shown_with_enough_digits_to_be_seen_over_it(
    value: float, level: float, digits: int, shown: str
) -> None:
    assert _over(value, level, digits) == shown


def test_a_sign_is_never_printed_as_a_figure_that_looks_to_be_at_its_level() -> None:
    """The decision is made on six places, so the note shows what the decision saw."""
    group = GroupShape(
        arm="variant_b",
        n=500,
        payers=60,
        unread=None,
        skewness=1.5,
        excess_kurtosis=100.04,
        top_share=0.50004,
        top_count=5,
        limbs=("kurtosis", "top_share"),
    )

    text = _group_sentence("variant_b", group, "revenue_usd_7d")

    assert "excess kurtosis 100.04 (above 100: a sign)" in text
    assert (
        "the top 5 players (1% of them, rounded up) hold 50.004% of the total (above 50%: a sign)"
        in text
    )


@pytest.mark.parametrize(
    ("skewness", "shown"), [(1.0002, "1.0002"), (-1.0002, "-1.0002"), (-9.9, "-9.900")]
)
def test_a_skewness_over_its_level_in_size_is_shown_with_its_sign_and_enough_digits(
    skewness: float, shown: str
) -> None:
    group = GroupShape(
        arm="variant_b",
        n=100,
        payers=60,
        unread=None,
        skewness=skewness,
        excess_kurtosis=3.0,
        top_share=0.2,
        top_count=1,
        limbs=("kohavi",),
    )

    text = _group_sentence("variant_b", group, "revenue_usd_7d")

    assert f"skewness {shown}, for which the size rule asks for about" in text


def test_the_cases_are_said_to_be_on_each_side_of_a_comparison_only_when_they_are(raw_spec) -> None:
    inside = " ".join(_evidence(_three_to_one(raw_spec))["notes"])
    beyond = " ".join(_evidence(_pair(raw_spec, variant_copies=19))["notes"])

    assert "(nearer the difference seen), the simulated cases on each side of it (" in inside
    assert "the simulated cases nearest to it (" in beyond  # 19 to 1: beyond 9 to 1 in both rows
    assert "on each side of it" not in beyond


def test_a_count_metric_interval_is_in_the_units_of_the_metric(raw_spec) -> None:
    context = _context(raw_spec, _heavy_sessions(), primary_metric__name="sessions_7d")

    note = next(n for n in _evidence(context)["notes"] if "metric sessions_7d" in n)

    assert " sessions per player." in note
    assert "a top player" not in note
    assert "the top 3 players (1% of them, rounded up) hold" in note


def test_in_a_group_of_fewer_than_a_hundred_one_player_is_the_top_one_per_cent(raw_spec) -> None:
    rows = [Row(f"c{i:03d}", "control", revenue=100.0 if i == 0 else 0.0) for i in range(50)]
    rows += [Row(f"v{i:03d}", "variant_b", revenue=40.0 if i < 2 else 0.0) for i in range(50)]

    finding = RES_008.evaluate(_context(raw_spec, rows))

    assert finding is not None
    note = next(n for n in finding.evidence["notes"] if n.startswith("arm variant_b, metric rev"))
    assert "control: 50 analysed players, 1 player who spends;" in note
    assert "the top player holds 100% of the total (above 50%: a sign)" in note
    assert "the top player holds 50.0% of the total." in note  # two equal spenders: not above half
    assert "the top 1 players" not in note


# --- After the independent review: what the reader is told first, and about far-off cases -------


def _range_text(found: dict) -> str:
    return f"{percent(round(found['low'] * UNIT))} to {percent(round(found['high'] * UNIT))}"


def test_the_note_starts_with_the_bottom_line_and_prints_the_difference_seen(raw_spec) -> None:
    evidence = _evidence(_equal(raw_spec, factor=1.6))
    note = next(n for n in evidence["notes"] if n.startswith("arm variant_b, metric rev"))
    ranges = evidence["tests"][0]["simulated"]["ranges"]
    first, second = (_range_text(ranges[effects]) for effects in ("large", "small"))

    head = note.split(" variant_b: 1,000 analysed players")[0]
    assert head.startswith(
        "arm variant_b, metric revenue_usd_7d: signs of a heavy-tailed metric in variant_b and "
        "control. The difference seen is +60% of control's mean. Welch's 95% interval for the "
        "difference (variant_b less control) is "
    )
    assert (
        f"it failed in {first} of them with an effect of +50% or +100% (nearer the difference seen)"
        in head
    )
    assert f"and in {second} with an effect of none or +20%." in head
    assert head.endswith("Read the interval with those rates in mind.")


def test_a_comparison_that_was_simulated_to_stay_near_its_level_does_not_ask_for_caution(
    raw_spec,
) -> None:
    note = next(
        n
        for n in _evidence(_equal(raw_spec))["notes"]
        if n.startswith("arm variant_b, metric revenue")
    )

    assert "The difference seen is +10% of control's mean." in note
    assert "with an effect of none or +20% (nearer the difference seen) and in" in note
    assert "Read the interval with those rates in mind." not in note


def test_cases_far_from_the_comparison_are_said_to_be_and_the_nearest_one_is_given(
    raw_spec,
) -> None:
    evidence = _evidence(_equal(raw_spec, factor=1.6))
    (entry,) = evidence["tests"]
    large = entry["simulated"]["ranges"]["large"]
    note = next(n for n in evidence["notes"] if n.startswith("arm variant_b, metric rev"))

    assert (
        large["far_apart"] is True and entry["simulated"]["ranges"]["small"]["far_apart"] is False
    )
    (nearest,) = large["nearest_cases"]
    assert (nearest["split"], nearest["payers"]) == (1.0, 130)
    # the nearest case (130 players who spend) has the low end of the range; the 13 the high end
    assert large["ends_from_further"] == {"low": False, "high": True}
    assert (
        "These cases lie far apart, so the high end of that range comes from a case further "
        "from this comparison than the nearest one, 1 to 1 with 130 players who spend, which "
        f"failed in {percent(round(nearest['low'] * UNIT))} to "
        f"{percent(round(nearest['high'] * UNIT))}."
    ) in note
    assert note.count("These cases lie far apart") == 1


def test_groups_of_one_size_name_the_group_with_fewer_players_who_spend(raw_spec) -> None:
    rows = _spenders("control", 1000, 21, share=0.10) + _spenders("variant_b", 1000, 22, share=0.14)
    note = next(
        n
        for n in _evidence(_context(raw_spec, rows))["notes"]
        if n.startswith("arm variant_b, metric revenue")
    )

    assert "the groups are the same size), with " in note
    assert " players who spend in control, the group with fewer of them." in note
    assert "in the smaller group (control)" not in note and "in each group" not in note


def test_groups_of_one_size_with_as_many_players_who_spend_say_so_and_not_which_is_fewer(
    raw_spec,
) -> None:
    note = next(
        n
        for n in _evidence(_equal(raw_spec))["notes"]
        if n.startswith("arm variant_b, metric revenue")
    )

    assert "the groups are the same size), with 117 players who spend in each group." in note
    assert "the group with fewer of them" not in note


def test_when_both_groups_cannot_be_read_the_note_does_not_speak_of_another_one(raw_spec) -> None:
    rows = crowd("variant_b", 40, revenue=0.0) + crowd("control", 40, revenue=0.0)

    report = heavy_tail_report(_context(raw_spec, rows))

    (entry,) = report["tests"]
    note = report["notes"][1]
    assert entry["status"] == "not_evaluated"
    assert note == (
        "arm variant_b, metric revenue_usd_7d: not evaluated: variant_b could not be read "
        "(every value is 0) and control could not be read (every value is 0)."
    )


def test_a_pair_with_one_group_that_cannot_be_read_and_one_without_a_sign_says_so(
    raw_spec,
) -> None:
    rows = crowd("variant_b", 40, revenue=0.0) + _spenders("control", 400, 9, sigma=0.2, share=1.0)

    report = heavy_tail_report(_context(raw_spec, rows))

    assert report["notes"][1] == (
        "arm variant_b, metric revenue_usd_7d: not evaluated: variant_b could not be read "
        "(every value is 0); the other group shows no sign."
    )


def test_the_summary_keeps_the_rate_that_decides_and_the_highest_one_printed(raw_spec) -> None:
    summary = heavy_tail_report(_equal(raw_spec))["summary"]

    assert summary["largest_simulated_rate"] < summary["largest_printed_rate"]
    assert summary["floor_ranges"] == 0
    assert summary["largest_printed_rate"] > EXCESS_RATE / UNIT >= summary["largest_simulated_rate"]


def _sized(raw_spec, variant_n: int, **more) -> ResultsContext:
    """Control of 1,000 and a variant of `variant_n`, both made of the same draws."""
    base = [row.revenue for row in _spenders("control", 1000, 1)]
    rows = [Row(f"control_{i:05d}", "control", revenue=base[i]) for i in range(1000)]
    rows += [
        Row(f"variant_b_{i:05d}", "variant_b", revenue=round(base[i % 1000] * 1.1, 6))
        for i in range(variant_n)
    ]
    return _context(raw_spec, rows, **more)


@pytest.mark.parametrize(
    ("variant_n", "equal"), [(1000, True), (1249, True), (1250, True), (1251, False), (1300, False)]
)
def test_groups_within_five_to_four_are_about_equal_in_size_in_the_note(
    raw_spec, variant_n: int, equal: bool
) -> None:
    notes = " ".join(_evidence(_sized(raw_spec, variant_n))["notes"])

    assert ("groups of about equal size, most of the failed" in notes) is equal
    assert ("groups of unequal size, most of the failed" in notes) is (not equal)
    assert ("Kohavi et al. (2014) note" in notes) is equal


def _only_skewed() -> list[Row]:
    """500 players an arm, 60% of them spending a lognormal amount: skewed, light-tailed."""
    rows = []
    for arm, seed in (("control", 21), ("variant_b", 22)):
        rng = random.Random(seed)
        rows += [
            Row(
                f"{arm}_{i:04d}",
                arm,
                revenue=round(rng.lognormvariate(0, 1.2), 4) if i % 5 else 0.0,
            )
            for i in range(500)
        ]
    return rows


def test_a_metric_that_trips_only_the_size_rule_is_called_skewed_not_heavy_tailed(raw_spec) -> None:
    finding = RES_008.evaluate(_context(raw_spec, _only_skewed()))

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert entry["signs"] == ["kohavi"]
    note = next(n for n in finding.evidence["notes"] if n.startswith("arm variant_b, metric rev"))
    assert note.startswith(
        "arm variant_b, metric revenue_usd_7d: signs of a skewed metric in variant_b and control."
    )
    assert "heavy-tailed metric" not in note
    assert "(a sign)" in note and "(above 100: a sign)" not in note


def test_the_printed_interval_and_the_summary_line_are_those_of_the_evidence(raw_spec) -> None:
    evidence = _evidence(_equal(raw_spec, factor=1.6))
    note = next(n for n in evidence["notes"] if n.startswith("arm variant_b, metric rev"))
    estimate = evidence["tests"][0]["estimate"]

    assert f"is {_sig(estimate['ci_low'])} to {_sig(estimate['ci_high'])} USD per player." in note
    assert evidence["summary"]["line"].startswith(
        "RES-008: 1 comparison (binary metrics are not read), 1 with a sign of a heavy tail, "
        "0 not evaluated. No sign is not a pass"
    )
    assert "The larger group has fewer" not in note  # equal counts of players who spend


def test_the_rules_condition_names_the_levels_and_the_rounding_of_the_code() -> None:
    text = RES_008.fires_when

    assert f"fewer players than {KOHAVI_MULTIPLE} times the square" in text
    assert f"excess kurtosis above {KURTOSIS_OVER}" in text
    assert f"rounded to {DIGITS} places" in text
    assert "more than half of the total" in text
    when = RES_008.escalation.when
    assert f"reaches above {percent(EXCESS_RATE)}" in when
    assert f"which is {EXCESS_RATE / NOMINAL_RATE:g} times the" in when
    assert f"the {percent(NOMINAL_RATE)[:-3]}% an interval of this level" in when


@pytest.mark.parametrize(
    ("nearer", "largest", "floors"),
    [(True, 0.04, 0), (False, 0.09, 1), (None, 0.09, 1)],
)
def test_a_range_decides_the_severity_unless_the_other_effects_are_the_nearer_ones(
    nearer: bool | None, largest: float, floors: int
) -> None:
    """With None the nearer effects cannot be told, and both ranges decide."""
    from referee.rules.heavy_tails import summarise

    def entry(small: dict, large: dict) -> dict:
        return {
            "status": "tripped",
            "simulated": {"reason": None, "ranges": {"small": small, "large": large}},
        }

    low = {"high": 0.04, "floor": False, "nearer": nearer}
    high = {"high": 0.09, "floor": True, "nearer": None if nearer is None else not nearer}

    summary = summarise([entry(low, high)])

    assert summary["largest_simulated_rate"] == largest
    assert summary["largest_printed_rate"] == 0.09
    assert summary["floor_ranges"] == floors


def _bottom_line_entry(high: float) -> dict:
    ranges = {
        effects: {"low": 0.03, "high": high, "nearer": effects == "small"}
        for effects in ("small", "large")
    }
    return {
        "arm": "variant_b",
        "metric": "revenue_usd_7d",
        "estimate": {"ci_low": -1.0, "ci_high": 2.0},
        "relative_difference": 0.1,
        "effect_seen": 0.1,
        "nearer_effects": "small",
        "simulated": {"reason": None, "ranges": ranges},
    }


@pytest.mark.parametrize(("high", "asked"), [(0.04999, False), (0.05, False), (0.05001, True)])
def test_the_interval_is_to_be_read_with_the_rates_in_mind_only_above_the_level(
    high: float, asked: bool
) -> None:
    from referee.rules.heavy_tails import _bottom_line

    text = _bottom_line(_bottom_line_entry(high))

    assert ("Read the interval with those rates in mind." in text) is asked


def test_without_an_interval_the_bottom_line_does_not_speak_of_one(raw_spec) -> None:
    from referee.rules.heavy_tails import _bottom_line

    entry = {
        **_bottom_line_entry(0.2),
        "estimate": {"error": "an arm has fewer than 2 players"},
    }

    text = _bottom_line(entry)

    assert text.startswith(
        "The difference seen is +10% of control's mean. Welch's 95% interval could not be "
        "computed (an arm has fewer than 2"
    )
    assert (
        "For comparisons like this one, Welch's 95% interval, which should fail to contain" in text
    )
    assert "An interval like it" not in text and "Read the interval" not in text
    assert "failed in 3.0% to 20.0% of them with an effect of none or +20%" in text


@pytest.mark.parametrize(
    ("share", "shown"),
    [
        (0.3, "+30%"),
        (-0.3, "-30%"),
        (0.0, "0%"),
        (0.35, "+35.0%"),
        (0.3499, "+34.99%"),  # not "+35%": the effects nearer are decided on this side of 35%
        (0.349999, "+34.9999%"),
        (-0.3499, "-34.99%"),
        (0.351, "+35.1%"),
        (0.3504, "+35.0%"),
    ],
)
def test_a_percentage_near_the_level_keeps_the_side_of_it_that_it_is_on(share, shown) -> None:
    assert _signed_percent(share) == shown


@pytest.mark.parametrize(
    ("split", "shown"),
    [
        (Fraction(1001, 1000), "1.001"),  # not "1", beside "the larger group"
        (Fraction(1004, 1000), "1.004"),
        (Fraction(5, 4), "1.25"),
        (Fraction(1251, 1000), "1.251"),  # not "1.25": that is about equal, this is not
        (Fraction(12501, 10000), "1.2501"),
        (Fraction(3, 2), "1.5"),
        (Fraction(969, 926), "1.05"),
        (Fraction(1000), "1,000"),
        (Fraction(12345, 10), "1,234.5"),
    ],
)
def test_a_split_is_shown_with_the_digits_that_keep_it_on_its_side_of_the_limits(
    split, shown
) -> None:
    assert _ratio(split) == shown


def test_the_nearest_cases_are_named_once_each_and_failed_in_the_span_of_all() -> None:
    twin = [
        {"split": 9.0, "payers": 130, "low": 0.041, "high": 0.073},
        {"split": 9.0, "payers": 130, "low": 0.115, "high": 0.2},
    ]
    other = {"split": 3.0, "payers": 90, "low": 0.03, "high": 0.05}

    assert _nearest_text(twin[:1]) == (
        "the nearest one, 9 to 1 with 130 players who spend, which failed in 4.1% to 7.3%"
    )
    assert _nearest_text(twin) == (
        "the nearest one, 9 to 1 with 130 players who spend, which failed in 4.1% to 20.0%"
    )
    assert _nearest_text([*twin, other]) == (
        "the nearest ones, 9 to 1 with 130 players who spend and 3 to 1 with 90 players who "
        "spend, which failed in 3.0% to 20.0%"
    )


# --- Behaviours the second review found unpinned -----------------------------------------------


def _same_values(values: list[float], *, field: str = "revenue") -> list[Row]:
    """The same values in both arms, so that they are of one size and one shape."""
    return [
        Row(f"{arm}_{i:05d}", arm, **{field: value})
        for arm in ("control", "variant_b")
        for i, value in enumerate(values)
    ]


def _text(report: dict) -> str:
    return " ".join(report["notes"])


def test_the_remark_about_equal_groups_is_for_the_size_rule_alone(raw_spec) -> None:
    kurtosis_only = [1000.0] * 998 + [0.0, 2000.0]
    share_only = [200.0] * 400 + [1.0] * 39600

    for values, signs in ((kurtosis_only, ["kurtosis"]), (share_only, ["top_share"])):
        report = heavy_tail_report(_context(raw_spec, _same_values(values)))

        assert report["tests"][0]["signs"] == signs
        assert "Kohavi et al. (2014) note" not in _text(report)


def test_the_size_rule_sentence_is_for_a_pair_that_shows_the_size_rule_only(raw_spec) -> None:
    kurtosis_only = [1000] * 998 + [0, 2000]

    report = heavy_tail_report(
        _context(
            raw_spec,
            _same_values(kurtosis_only, field="sessions"),
            primary_metric__name="sessions_7d",
        )
    )

    assert report["tests"][0]["signs"] == ["kurtosis"]
    assert "The size rule is built" not in _text(report)


@pytest.mark.parametrize(
    ("players", "phrase"),
    [
        (100, "the top player holds"),
        (101, "the top 2 players (1% of them, rounded up) hold"),
        (200, "the top 2 players (1% of them, rounded up) hold"),
        (201, "the top 3 players (1% of them, rounded up) hold"),
    ],
)
def test_the_top_count_is_named_by_its_size_in_groups_of_a_hundred_to_two_hundred(
    raw_spec, players: int, phrase: str
) -> None:
    rng = random.Random(5)
    values = [0.0] * (players * 2 // 3) + [
        float(rng.randint(1, 50)) for _ in range(players - players * 2 // 3)
    ]

    report = heavy_tail_report(_context(raw_spec, _same_values(values)))

    assert phrase in _text(report)


def test_with_only_binary_metrics_the_first_note_says_none_is_read(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    context = ResultsContext.of(spec, build_data(crowd("control", 50) + crowd("variant_b", 50)))

    report = heavy_tail_report(context)

    assert "is not binary: none (purchased_7d binary, not read)." in report["notes"][0]
    assert "bootstrap" not in _text(report)  # nothing tripped: nothing to say about it


def test_a_quiet_report_has_no_bootstrap_note(raw_spec) -> None:
    rng = random.Random(1)
    values = [round(rng.lognormvariate(1.0, 0.2), 3) for _ in range(400)]

    report = heavy_tail_report(_context(raw_spec, _same_values(values)))

    assert report["summary"]["tripped"] == 0 and "bootstrap" not in _text(report)


def test_the_evidence_of_every_entry_holds_what_the_report_of_4c_will_print(raw_spec) -> None:
    context = _context(raw_spec, _equal_sessions_rows(), guardrails=[SESSIONS_GUARDRAIL])
    evidence = _evidence(context)
    tripped, quiet = evidence["tests"]

    assert (tripped["kind"], tripped["family"]) == ("continuous", "revenue_like")
    assert (quiet["kind"], quiet["family"], quiet["status"]) == (
        "continuous",
        "count",
        "not_tripped",
    )
    assert quiet["estimate"] is None and quiet["simulated"] is None
    for entry in (tripped, quiet):
        for name, group in entry["groups"].items():
            assert group["mean"] is not None and group["mean"] > 0, name
    assert tripped["comparison"] == {
        "split": 1.0,
        "split_numerator": 1,
        "split_denominator": 1,
        "larger": "equal",
        "smaller": "control",
        "payers_in_smaller": 117,
        "payers_in_larger": 118,
        "placed_as_equal": True,
        "read_as": "equal",
    }
    arm_mean, control_mean = (tripped["groups"][name]["mean"] for name in ("variant_b", "control"))
    assert tripped["relative_difference"] == round((arm_mean - control_mean) / control_mean, 6)
    assert tripped["effect_seen"] == round(
        tripped["groups"]["variant_b"]["mean"] / tripped["groups"]["control"]["mean"] - 1, 6
    )


def test_the_settings_and_the_summary_are_the_levels_of_the_code(raw_spec) -> None:
    context = _context(raw_spec, _equal_sessions_rows(), guardrails=[SESSIONS_GUARDRAIL])
    evidence = _evidence(context)

    assert evidence["settings"] == {
        "kohavi_multiple": KOHAVI_MULTIPLE,
        "skewness_over": 1,
        "kurtosis_over": KURTOSIS_OVER,
        "top_percent": 1,
        "top_share_over": 0.5,
        "confidence": 0.95,
        "nominal_rate": 0.05,
        "excess_rate": 0.075,
        "equal_arms_up_to_split": 1.25,
        "large_effect_from": 0.35,
        "far_apart": {"players": 5, "split": 2.5},
        "metrics_read": ["revenue_usd_7d", "sessions_7d"],
        "metrics_not_read_binary": [],
        "randomization_unit": "player",
        "analysis_unit": "player",
        "unit_class": {"randomization": "person", "analysis": "person"},
    }
    summary = evidence["summary"]
    assert (summary["tests"], summary["tripped"], summary["not_tripped"]) == (2, 1, 1)
    assert summary["not_evaluated"] == 0


# --- After the third review ---------------------------------------------------------------------


def _exact_spenders(arm: str, n: int, spenders: int, seed: int) -> list[Row]:
    """`n` players of one arm, exactly `spenders` of them spending a lognormal amount."""
    rng = random.Random(seed)
    return [
        Row(
            f"{arm}_{i:05d}",
            arm,
            revenue=round(rng.lognormvariate(1.0, 1.5), 4) if i < spenders else 0.0,
        )
        for i in range(n)
    ]


def test_cases_exactly_at_the_comparison_are_said_to_be_at_it(raw_spec) -> None:
    rows = _exact_spenders("control", 1000, 130, 1) + _exact_spenders("variant_b", 1000, 130, 2)
    (entry,) = _evidence(_context(raw_spec, rows))["tests"]
    note = next(n for n in _evidence(_context(raw_spec, rows))["notes"] if "metric revenue" in n)

    assert entry["comparison"]["payers_in_smaller"] == 130 and entry["comparison"]["split"] == 1.0
    assert "the simulated cases at it (split 1 to 1 with 130 players who spend;" in note
    assert "on each side of it" not in note


def test_the_far_apart_sentence_is_only_for_ends_that_come_from_further_cases(raw_spec) -> None:
    far = _evidence(_equal(raw_spec, factor=1.6))  # the high end comes from the 13 who spend
    # 3 to 1 with about 30 players who spend: the 13 who spend are the nearest, in both orders
    nearest_all = _evidence(_pair(raw_spec, n=230, seed=3, variant_copies=3, factor=1.6))
    (a,), (b,) = far["tests"], nearest_all["tests"]
    assert 14 <= b["comparison"]["payers_in_smaller"] <= 40

    large = b["simulated"]["ranges"]["large"]
    assert large["far_apart"] is True  # the cases lie far apart ...
    assert large["ends_from_further"] == {
        "low": False,
        "high": False,
    }  # ... the nearest hold the ends
    assert "These cases lie far apart" not in " ".join(nearest_all["notes"])
    assert a["simulated"]["ranges"]["large"]["ends_from_further"] == {"low": False, "high": True}
    assert "the high end of that range comes from a case further" in " ".join(far["notes"])


def test_the_means_are_given_when_no_share_of_control_s_mean_can_be(raw_spec) -> None:
    # control's mean is about 0.3 and the arm's about 1e8: beyond what is measured
    rng = random.Random(7)
    rows = [
        Row(
            f"control_{i:04d}",
            "control",
            revenue=round(rng.lognormvariate(0, 1.5), 4) if i % 5 == 0 else 0.0,
        )
        for i in range(500)
    ] + [
        Row(
            f"variant_b_{i:04d}",
            "variant_b",
            revenue=round(rng.lognormvariate(18, 1.5), 4) if i % 5 == 0 else 0.0,
        )
        for i in range(500)
    ]
    evidence = _evidence(_context(raw_spec, rows))
    (entry,) = evidence["tests"]

    assert entry["relative_difference"] is None and entry["effect_seen"] is None
    assert entry["nearer_effects"] == "large"
    json.dumps(evidence, allow_nan=False)  # nothing that JSON refuses
    text = " ".join(evidence["notes"])
    assert (
        "too far apart to give a share of control's mean; that is read as an effect of +50% "
        "and +100%." in text
    )


def test_when_the_means_cannot_be_compared_both_ranges_set_the_severity(raw_spec) -> None:
    from referee.rules.heavy_tails import _seen_sentence

    (entry,) = _evidence(_equal(raw_spec))["tests"]
    missing = {**entry, "relative_difference": None, "effect_seen": None, "nearer_effects": None}

    assert (
        _seen_sentence(missing) == "The means cannot be compared, so both ranges set the severity. "
    )
    no_rates = {**missing, "simulated": {"reason": "metric_not_simulated", "ranges": None}}
    assert _seen_sentence(no_rates) == ""  # nothing is "nearer" where no rate is quoted


def test_a_control_with_a_mean_of_zero_is_read_as_a_large_effect(raw_spec) -> None:
    rows = crowd("control", 60, revenue=0.0) + _spenders("variant_b", 800, 4, share=0.1)
    (entry,) = _evidence(_context(raw_spec, rows))["tests"]

    assert entry["groups"]["control"]["unread"] == "all_zero"
    assert entry["relative_difference"] is None and entry["nearer_effects"] == "large"


def test_a_huge_share_is_printed_with_separators_and_a_lower_mean_is_not_explained_without_rates(
    raw_spec,
) -> None:
    assert _signed_percent(123456.7) == "+12,345,670%"
    assert _signed_percent(-0.5) == "-50%"
    count = heavy_tail_report(
        _context(raw_spec, _heavy_sessions(), primary_metric__name="sessions_7d")
    )
    assert "in the terms of the simulations" not in " ".join(count["notes"])


def test_the_exactly_equal_groups_are_not_told_they_were_placed_among_equal_ones(raw_spec) -> None:
    text = " ".join(_evidence(_equal(raw_spec))["notes"])
    near = " ".join(_evidence(_sized(raw_spec, 1200))["notes"])

    assert "Groups within 1.25 to 1 of each other in size are placed" not in text
    assert "The rate rises with the split, so near that limit it can be higher" in near


def test_the_report_does_not_depend_on_where_control_is_in_the_spec(raw_spec) -> None:
    rows = _spenders("control", 1000, 31, sigma=0.8) + _spenders("variant_b", 1000, 32, sigma=1.6)
    first = _evidence(_context(raw_spec, rows))
    swapped = _evidence(_context(raw_spec, rows, arms=list(reversed(TWO_ARMS))))

    assert first["tests"] == swapped["tests"]
    assert first["summary"] == swapped["summary"]


def test_a_direction_that_rose_in_one_order_of_the_groups_is_not_called_unknown(raw_spec) -> None:
    rng = random.Random(5)
    rows = [
        Row(
            f"control_{i:03d}",
            "control",
            revenue=round(rng.lognormvariate(1.0, 1.5), 4) if i < 12 else 0.0,
        )
        for i in range(90)
    ] + [
        Row(
            f"variant_b_{i:03d}",
            "variant_b",
            revenue=round(rng.lognormvariate(1.0, 1.5), 4) if i < 6 else 0.0,
        )
        for i in range(60)
    ]
    evidence = _evidence(_context(raw_spec, rows))
    (entry,) = evidence["tests"]
    small = entry["simulated"]["ranges"]["small"]
    large = entry["simulated"]["ranges"]["large"]

    assert entry["comparison"]["split"] == 1.5 and entry["comparison"]["payers_in_smaller"] == 6
    assert small["extrapolated"] == ["payers_below_range"]
    assert small["rising"] == [] and small["rising_in_one_order"] == ["payers_below_range"]
    assert small["floor"] is False
    assert large["rising"] == ["payers_below_range"] and large["rising_in_one_order"] == []
    text = " ".join(evidence["notes"])
    assert (
        "For an effect of none or +20%, this comparison lies beyond the simulated cases: there "
        "are fewer players who spend than in the cases simulated at this split; in one order of "
        "the groups the rate rose in that direction and in the other it did not, so the true "
        "rate may be above this range."
    ) in text
    assert "the simulations do not show which way the rate goes there" not in text


def test_a_lower_mean_is_not_put_in_the_terms_of_the_simulations_where_no_rate_is_quoted(
    raw_spec,
) -> None:
    rows = _heavy_sessions()
    for row in rows:
        if row.arm == "variant_b":
            row.sessions = max(1, row.sessions // 2)
    evidence = _evidence(_context(raw_spec, rows, primary_metric__name="sessions_7d"))
    (entry,) = evidence["tests"]

    assert entry["relative_difference"] < 0 and entry["effect_seen"] > 0
    text = " ".join(evidence["notes"])
    assert "The difference seen is -29% of control's mean." in text
    assert "in the terms of the simulations" not in text
