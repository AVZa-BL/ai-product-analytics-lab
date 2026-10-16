"""RES-004: a guardrail worse than its tolerance allows, or that may be (design section 21.12).

The scenarios are seeded draws of session counts whose outcome against both references is
known from `tests/test_guardrails.py`; the figures a note prints are checked against the
evidence, and the findings' severities against the strength of the breach.
"""

import json
import random

import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, crowd, results_spec

from referee.guardrails import SMALL_COUNT
from referee.methods import proportion_interval
from referee.results import ResultsContext
from referee.rules import RESULTS_RULES
from referee.rules.guardrails import (
    _chance_text,
    _same_value_sentence,
    guardrail_report,
    summarise,
)
from referee.rules.references import KOHAVI_TANG_XU_2020

RES_004 = next(rule for rule in RESULTS_RULES if rule.id == "RES-004")
SESSIONS = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 3.0,
    "baseline_std": 2.0,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.10,
}
PURCHASED = {
    "name": "purchased_7d",
    "kind": "binary",
    "baseline": 0.018,
    "harmful_direction": "increase",
    "tolerance_relative": 0.10,
}
REVENUE_GUARDRAIL = {
    "name": "revenue_usd_7d",
    "kind": "continuous",
    "baseline": 1.0,
    "baseline_std": 10.0,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.10,
}
PRIMARY = {
    "primary_metric__name": "purchases_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 0.2,
    "primary_metric__baseline_std": 1.0,
}
BANNED = ("novelty", "decay", "stable", "proves", "found no", "because of")


def _context(raw_spec, rows: list[Row], *guardrails: dict, arms=TWO_ARMS) -> ResultsContext:
    spec = results_spec(raw_spec, arms=arms, guardrails=list(guardrails), **PRIMARY)
    return ResultsContext.of(spec, build_data(rows))


def _sessions(arm: str, values: list[int]) -> list[Row]:
    return [Row(f"{arm}_{i:05d}", arm, sessions=v) for i, v in enumerate(values)]


def _drawn(seed: int) -> tuple[list[Row], dict]:
    """60 players an arm with uniform session counts, and a baseline set at control's mean."""
    rng = random.Random(seed)
    arm = [rng.randint(0, 10) for _ in range(60)]
    control = [rng.randint(0, 12) for _ in range(60)]
    rows = _sessions("control", control) + _sessions("variant_b", arm)
    return rows, {**SESSIONS, "baseline": sum(control) / 60}


def _regression(raw_spec, *more: dict):
    """A real fall in sessions of about 25%."""
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [2, 3, 1, 2] * 80)
    return _context(raw_spec, rows, SESSIONS, *more)


def _evidence(context: ResultsContext) -> dict:
    finding = RES_004.evaluate(context)
    assert finding is not None
    return finding.evidence


# --- The rule as the catalogue states it ------------------------------------------------------


def test_the_rule_is_a_warning_that_becomes_a_blocker_when_the_breach_is_shown() -> None:
    assert (RES_004.severity, RES_004.escalation.to) == ("warning", "blocker")
    assert RES_004.references == (KOHAVI_TANG_XU_2020,)
    for text in (RES_004.fires_when, RES_004.why_it_matters, RES_004.remediation, RES_004.title):
        assert text.isascii()
    assert RES_004.escalation.when.isascii()
    assert RES_004.escalation.applies({}) is False  # a rule is test-built with no evidence


# --- What it finds -----------------------------------------------------------------------------


def test_a_real_regression_is_a_blocker_and_both_references_show_it(raw_spec) -> None:
    finding = RES_004.evaluate(_regression(raw_spec))

    assert finding is not None and finding.severity == "blocker"
    evidence = finding.evidence
    assert set(evidence) == {"summary", "settings", "tests", "notes"}
    (entry,) = evidence["tests"]
    assert (entry["arm"], entry["guardrail"], entry["status"]) == (
        "variant_b",
        "sessions_7d",
        "breach_shown",
    )
    assert entry["tier"] == "shown" and entry["decided_by"] == ["control", "baseline"]
    assert entry["references_agree"] is True and entry["baseline_has_moved"] is False
    for name in ("control", "baseline"):
        reference = entry["references"][name]
        assert reference["evaluated"] and reference["tier"] == "shown"
        assert reference["harm"]["low"] > entry["tolerance"]
    assert evidence["summary"]["breach_shown"] == 1 and evidence["summary"]["tests"] == 1


def test_a_breach_that_is_only_possible_is_a_warning(raw_spec) -> None:
    rows, guardrail = _drawn(4)
    finding = RES_004.evaluate(_context(raw_spec, rows, guardrail))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    assert entry["status"] == "breach_possible"
    for name in ("control", "baseline"):
        harm = entry["references"][name]["harm"]
        assert harm["point"] > entry["tolerance"] > harm["low"]
    assert finding.evidence["summary"]["breach_shown"] == 0
    assert finding.evidence["summary"]["breach_possible"] == 1
    note = finding.evidence["notes"][1]
    assert "a breach is possible, not shown." in note
    assert (
        "and only the point estimate is beyond the tolerance: the interval reaches inside it"
    ) in note
    assert "The two references agree." in note


def test_the_references_can_differ_and_the_stricter_one_decides(raw_spec) -> None:
    rows, guardrail = _drawn(1)
    finding = RES_004.evaluate(_context(raw_spec, rows, guardrail))

    assert finding is not None and finding.severity == "blocker"
    (entry,) = finding.evidence["tests"]
    assert entry["references"]["control"]["tier"] == "possible"
    assert entry["references"]["baseline"]["tier"] == "shown"
    assert entry["decided_by"] == ["baseline"] and entry["references_agree"] is False
    text = " ".join(finding.evidence["notes"])
    assert (
        "The references differ; the stricter reading, against the registered baseline, decides."
    ) in text


def test_a_guardrail_within_its_tolerance_is_no_finding(raw_spec) -> None:
    rows, guardrail = _drawn(3)
    context = _context(raw_spec, rows, guardrail)

    assert RES_004.evaluate(context) is None
    report = guardrail_report(context)
    assert report["summary"]["within_tolerance"] == 1 and report["summary"]["tests"] == 1
    assert report["tests"][0]["status"] == "within_tolerance"


def test_a_point_estimate_within_the_tolerance_is_no_finding_though_a_breach_is_not_ruled_out(
    raw_spec,
) -> None:
    # the same draws in both arms: no change, but 60 players cannot rule out a fall of 10%
    rng = random.Random(7)
    values = [rng.randint(0, 12) for _ in range(60)]
    rows = _sessions("control", values) + _sessions("variant_b", values)
    context = _context(raw_spec, rows, {**SESSIONS, "baseline": sum(values) / 60})

    report = guardrail_report(context)

    assert RES_004.evaluate(context) is None
    (entry,) = report["tests"]
    assert entry["status"] == "within_tolerance"
    assert entry["references"]["control"]["not_verified"] is True
    assert report["summary"]["not_verified"] == 1
    assert (
        "2 within the tolerance (1 of them" not in report["summary"]["line"]
        and "1 within the tolerance (1 of them with an interval that reaches beyond it, so the "
        "data cannot rule out a breach)"
        in report["summary"]["line"]
    )
    assert "safe" not in report["summary"]["line"] and "proven" not in report["summary"]["line"]
    assert (
        "within the tolerance on the point estimate, but the data cannot rule out a breach."
    ) in report["notes"][1]
    assert "though the interval reaches beyond it" in report["notes"][1]


def test_a_spec_without_guardrails_has_nothing_to_report(raw_spec) -> None:
    context = _context(raw_spec, _sessions("control", [3, 4]) + _sessions("variant_b", [3, 5]))

    report = guardrail_report(context)

    assert RES_004.evaluate(context) is None
    assert report["tests"] == [] and report["summary"]["tests"] == 0
    assert report["summary"]["line"].startswith("RES-004: 0 comparisons of an arm")
    assert report["settings"]["guardrails"] == [] and "(none)" in report["notes"][0]
    assert len(report["notes"]) == 1  # no comparison, so no note on how the intervals were made


def test_a_comparison_that_cannot_be_measured_is_counted_and_does_not_fire(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1])
    context = _context(raw_spec, rows, SESSIONS)

    report = guardrail_report(context)

    assert RES_004.evaluate(context) is None
    (entry,) = report["tests"]
    assert entry["status"] == "not_evaluated" and entry["tier"] is None
    assert report["summary"]["not_evaluated"] == 1
    assert "Neither reference could be measured" in report["notes"][1]
    assert "variant_b has fewer than 2 players" in report["notes"][1]


def test_one_comparison_that_is_shown_makes_the_finding_a_blocker_whatever_the_others(
    raw_spec,
) -> None:
    rows, possible = _drawn(4)  # the sessions: a breach that is only possible
    for row in rows:  # and purchases in the same players: 1 of 60, against 12 of 60
        arm_events = 1 if row.arm == "control" else 12
        row.purchases = 1 if int(row.player_id.rsplit("_", 1)[1]) < arm_events else 0

    finding = RES_004.evaluate(_context(raw_spec, rows, possible, PURCHASED))

    assert finding is not None and finding.severity == "blocker"
    status = {e["guardrail"]: e["status"] for e in finding.evidence["tests"]}
    assert status == {"sessions_7d": "breach_possible", "purchased_7d": "breach_shown"}
    summary = finding.evidence["summary"]
    assert (summary["breach_shown"], summary["breach_possible"]) == (1, 1)


def test_every_arm_but_control_is_a_test_of_its_own(raw_spec) -> None:
    from results_helpers import results_spec as spec_of

    rows = (
        _sessions("control", [3, 4, 2, 3] * 80)
        + _sessions("variant_b", [3, 4, 2, 3] * 80)
        + _sessions("variant_c", [2, 3, 1, 2] * 80)
    )
    spec = spec_of(raw_spec, guardrails=[SESSIONS], **PRIMARY)  # the three-arm default
    finding = RES_004.evaluate(ResultsContext.of(spec, build_data(rows)))

    assert finding is not None and finding.severity == "blocker"
    assert [(e["arm"], e["status"]) for e in finding.evidence["tests"]] == [
        ("variant_b", "within_tolerance"),
        ("variant_c", "breach_shown"),
    ]


def test_a_control_far_from_the_registered_baseline_is_said_to_have_moved_it(raw_spec) -> None:
    # both arms sit near 2 sessions against a registered baseline of 3
    rows = _sessions("control", [2, 2, 3, 1] * 60) + _sessions("variant_b", [2, 2, 3, 1] * 60)

    finding = RES_004.evaluate(_context(raw_spec, rows, SESSIONS))

    assert finding is not None and finding.severity == "blocker"
    (entry,) = finding.evidence["tests"]
    assert entry["references"]["control"]["tier"] == "within"
    assert entry["baseline_has_moved"] is True and entry["decided_by"] == ["baseline"]
    text = " ".join(finding.evidence["notes"])
    assert "Control itself is beyond the tolerance of the registered baseline (a harm of" in text
    assert "a breach against the baseline alone does not show that variant_b caused it" in text


def test_a_binary_guardrail_with_few_events_says_its_intervals_are_rough(raw_spec) -> None:
    rows = [Row(f"p_{i}", "control", purchases=1 if i < 2 else 0) for i in range(200)]
    rows += [Row(f"q_{i}", "variant_b", purchases=1 if i < 12 else 0) for i in range(200)]

    finding = RES_004.evaluate(_context(raw_spec, rows, PURCHASED))

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert entry["small_counts"] is True
    assert entry["events"] == {"arm": 12, "control": 2} and entry["kind"] == "binary"
    assert (
        f"A group has fewer than {SMALL_COUNT} players on one side of its rate, so these "
        "intervals are rough."
    ) in " ".join(finding.evidence["notes"])


def test_a_group_with_one_value_throughout_has_an_interval_with_no_width_and_says_so(
    raw_spec,
) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 40) + _sessions("variant_b", [0] * 160)

    finding = RES_004.evaluate(_context(raw_spec, rows, SESSIONS))

    # nobody in control is at 0 sessions, so 160 players there cannot be put down to chance: the
    # interval with no width is believed and the breach is shown
    assert finding is not None and finding.severity == "blocker"
    (entry,) = finding.evidence["tests"]
    baseline = entry["references"]["baseline"]
    assert baseline["no_variation"] is True and baseline["harm"]["point"] == 1.0
    assert baseline["tier"] == "shown" and baseline["capped_by"] is None
    assert baseline["constant_group"] == "arm" and baseline["chance_all_alike"] == 0.0
    text = " ".join(finding.evidence["notes"])
    assert (
        "Every player of variant_b (160) has the same value, so that interval has no width; at "
        "control's share of players with that value, so many alike would arise by chance in "
        "under 0.1% of samples, which chance does not explain."
    ) in text
    # against control the log of the ratio of the means is not there: said, and not as a zero
    # control, whose mean is 3
    reference = entry["references"]["control"]
    assert reference["evaluated"] is False
    assert reference["reason"] == (
        "the mean of variant_b is not above 0, so the ratio of the means has no logarithm "
        "and no interval can be formed"
    )
    assert (
        "The mean of variant_b is 0 and control's 3.00 sessions per player, a fall of the whole "
        "of control's mean."
    ) in text
    assert "Only the reference to the registered baseline could be measured." in text
    assert "Against control's mean: not measured (the mean of variant_b is not above 0, so" in text


def test_a_small_arm_at_zero_is_held_and_the_note_says_chance_is_not_ruled_out(raw_spec) -> None:
    # half of control's players are at 0 sessions: three of them all at 0 is one time in eight
    rows = _sessions("control", [0] * 100 + [3, 4, 2, 3] * 25) + _sessions("variant_b", [0] * 3)

    finding = RES_004.evaluate(_context(raw_spec, rows, SESSIONS))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    baseline = entry["references"]["baseline"]
    assert (baseline["tier"], baseline["capped_by"]) == ("possible", "no_variation")
    assert baseline["uncapped_tier"] == "shown"
    assert baseline["chance_all_alike"] == pytest.approx(0.5**3)
    text = " ".join(finding.evidence["notes"])
    assert "so many alike would arise by chance in about 12% of samples" in text
    assert "which chance does not explain" not in text
    # the arm is at 0 and control is not, which the note says; but chance explains an arm that
    # small, so it does not call the arm plainly the difference
    assert "The mean of variant_b is 0 and control's 1.50 sessions per player" in text
    assert "a breach against the baseline alone does not show that variant_b caused it" in text


@pytest.mark.parametrize(
    ("players", "severity"), [(3, "warning"), (30, "warning"), (300, "blocker")]
)
def test_an_all_zero_revenue_arm_is_a_blocker_only_when_chance_cannot_explain_it(
    raw_spec, players, severity
) -> None:
    """With 2 in 100 players buying, 30 players are all at 0 more than half of the time, and 300
    players in about one time in 400."""
    control = [
        Row(f"c_{i:04d}", "control", revenue=10.0 if i % 50 == 0 else 0.0) for i in range(300)
    ]
    arm = [Row(f"v_{i:04d}", "variant_b", revenue=0.0) for i in range(players)]
    guardrail = {**REVENUE_GUARDRAIL, "baseline": 0.2}

    finding = RES_004.evaluate(_context(raw_spec, control + arm, guardrail))

    assert finding is not None and finding.severity == severity
    (entry,) = finding.evidence["tests"]
    assert entry["n"]["arm"] == players
    assert entry["status"] == ("breach_shown" if severity == "blocker" else "breach_possible")
    text = " ".join(finding.evidence["notes"])
    assert f"Every player of variant_b ({players}) has the same value" in text
    chance = entry["references"]["baseline"]["chance_all_alike"]
    assert chance == pytest.approx(0.98**players)
    if severity == "warning":
        assert "which is not below 2.5%, so chance is not ruled out." in text
    else:
        assert "in about 0.23% of samples, which chance does not explain." in text


def test_a_held_reading_names_how_often_chance_gives_so_many_alike(raw_spec) -> None:
    control = [
        Row(f"c_{i:04d}", "control", revenue=10.0 if i % 50 == 0 else 0.0) for i in range(300)
    ]
    arm = [Row(f"v_{i:04d}", "variant_b", revenue=0.0) for i in range(30)]

    note = guardrail_report(
        _context(raw_spec, control + arm, {**REVENUE_GUARDRAIL, "baseline": 0.2})
    )["notes"][1]

    assert (
        "Every player of variant_b (30) has the same value, so that interval has no width; at "
        "control's share of players with that value, so many alike would arise by chance in "
        "about 55% of samples, which is not below 2.5%, so chance is not ruled out."
    ) in note
    assert (
        "and the whole interval is beyond the tolerance, but this reading is held to possible"
        in note
    )


def test_a_constant_group_in_the_ratio_to_control_is_explained_in_the_note(raw_spec) -> None:
    control = [2, 3, 3, 3, 4] * 40  # one in five has exactly 2 sessions
    rows = _sessions("control", control) + _sessions("variant_b", [2, 2])

    report = guardrail_report(_context(raw_spec, rows, SESSIONS))

    (entry,) = report["tests"]
    ratio = entry["references"]["control"]
    assert ratio["constant_group"] == "arm" and ratio["capped_by"] == "no_variation"
    assert ratio["chance_all_alike"] == pytest.approx(0.04)
    assert (
        "Every player of variant_b (2) has the same value, so the interval for the ratio takes "
        "its width from control alone; at control's share of players with that value, so many "
        "alike would arise by chance in about 4.0% of samples, which is not below 2.5%, so "
        "chance is not ruled out."
    ) in report["notes"][1]


# --- The evidence and the notes ---------------------------------------------------------------


def test_the_evidence_is_plain_json_and_deterministic(raw_spec) -> None:
    context = _regression(raw_spec, PURCHASED)

    first, second = guardrail_report(context), guardrail_report(context)

    assert first == second
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_the_settings_are_the_levels_of_the_code(raw_spec) -> None:
    settings = _evidence(_regression(raw_spec, PURCHASED))["settings"]

    assert settings == {
        "confidence": 0.95,
        "decision_digits": 6,
        "small_count": 10,
        "references": ["control", "baseline"],
        "guardrails": ["sessions_7d", "purchased_7d"],
        "arms": ["variant_b"],
    }


def test_the_first_note_says_what_is_read_and_what_a_breach_is(raw_spec) -> None:
    first = _evidence(_regression(raw_spec, PURCHASED))["notes"][0]

    assert first.startswith(
        "RES-004 reads each non-control arm against control on each guardrail of the spec "
        "(sessions_7d and purchased_7d), on the analysed players."
    )
    for phrase in (
        "A guardrail is breached when it is worse than its registered baseline by more than its "
        "tolerance.",
        "against two references and takes the stricter: control's observed mean",
        "the registered baseline (the arm's own mean with a t interval, or its rate with a "
        "Wilson interval)",
        "A breach is shown when the whole 95% interval for the harm is beyond the tolerance, "
        "and possible when only the point estimate is;",
        "in which case the data cannot rule out a breach",
        "an interval with no width that chance could explain, and the t interval of a "
        "revenue-like guardrail against the registered baseline when a fall is harmful and the "
        "group has some spread, can only make a breach possible",
        "rounded to 6 places",
    ):
        assert phrase in " ".join(first.split()), phrase


def test_the_note_of_a_comparison_prints_the_figures_of_the_evidence(raw_spec) -> None:
    evidence = _evidence(_regression(raw_spec))
    (entry,) = evidence["tests"]
    note = evidence["notes"][1]
    control, baseline = entry["references"]["control"], entry["references"]["baseline"]

    assert note.startswith(
        "arm variant_b, guardrail sessions_7d (decrease is harmful, tolerance 10.0%): "
        "a breach is shown. Against control's mean: the mean of variant_b is 2.00 and "
        "control's 3.00 sessions per player, a ratio of 0.6667 (95% interval "
    )
    assert entry["n"] == {"arm": 320, "control": 320}
    assert entry["means"] == {"arm": 2.0, "control": 3.0}
    for reference, of_what in ((control, "control's mean"), (baseline, "the baseline")):
        harm = reference["harm"]
        assert f"the harm is {100 * harm['point']:.1f}% of {of_what} " in note
        assert f"({100 * harm['low']:.1f}% to {100 * harm['high']:.1f}%)" in note
    assert "Against the registered baseline of 3.00 sessions per player:" in note
    assert "variant_b's own mean is 2.00 sessions per player (95% interval " in note
    assert "against a tolerance of 10.0%, and the whole interval is beyond the tolerance." in note
    assert note.endswith("The two references agree.")


def test_a_guardrail_that_got_better_is_said_to_be_a_gain(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [4, 5, 3, 4] * 80)
    context = _context(raw_spec, rows, SESSIONS)
    report = guardrail_report(context)
    note = report["notes"][1]
    harm = report["tests"][0]["references"]["control"]["harm"]

    assert RES_004.evaluate(context) is None
    assert harm["point"] == pytest.approx(-0.333333, abs=1e-6)
    assert (
        f"the harm is -33.3% of control's mean (a gain; {100 * harm['low']:.1f}% to "
        f"{100 * harm['high']:.1f}%)"
    ) in note
    assert "(a gain; " in note.split("Against the registered baseline")[1]
    positive = _evidence(_regression(raw_spec))["notes"][1]
    assert "a gain" not in positive


def test_a_rate_is_printed_as_a_percentage_of_players(raw_spec) -> None:
    rows = [Row(f"p_{i}", "control", purchases=1 if i < 40 else 0) for i in range(1000)]
    rows += [Row(f"q_{i}", "variant_b", purchases=1 if i < 80 else 0) for i in range(1000)]

    note = _evidence(_context(raw_spec, rows, PURCHASED))["notes"][1]

    assert "the rate of variant_b is 8.00% and control's 4.00% of players" in note
    assert "Against the registered baseline of 1.80% of players:" in note
    wilson = proportion_interval(80, 1000)
    low, high = (f"{100 * x:.2f}" for x in (wilson.ci_low, wilson.ci_high))
    assert (
        f"variant_b's own rate is 8.00% of players (95% interval {low}% to {high}% of players)"
        in note
    )


def test_the_unit_of_a_revenue_guardrail_is_money_and_the_heavy_tail_is_mentioned(
    raw_spec,
) -> None:
    rng = random.Random(3)
    rows = [
        Row(f"c_{i:04d}", "control", revenue=round(rng.lognormvariate(0, 1.2), 3) if i % 5 else 0.0)
        for i in range(400)
    ] + [
        Row(
            f"v_{i:04d}",
            "variant_b",
            revenue=round(rng.lognormvariate(-1, 1.2), 3) if i % 5 else 0.0,
        )
        for i in range(400)
    ]
    evidence = _evidence(_context(raw_spec, rows, REVENUE_GUARDRAIL))

    assert "USD per player" in evidence["notes"][1]
    assert any("For a revenue-like guardrail (most players at 0" in n for n in evidence["notes"])
    quiet = _evidence(_regression(raw_spec))
    assert not any(n.startswith("For a revenue-like guardrail") for n in quiet["notes"])


def test_the_last_notes_are_printed_once_and_say_the_intervals_are_unadjusted(raw_spec) -> None:
    notes = _evidence(_regression(raw_spec, PURCHASED))["notes"]

    unadjusted = [n for n in notes if n.startswith("The intervals are unadjusted 95% intervals")]
    assert len(unadjusted) == 1 and notes.index(unadjusted[0]) == len(notes) - 2
    assert "a reason to look at the guardrail, not a verdict on the arm" in unadjusted[0]
    assert notes[-1].startswith("For a count guardrail (sessions, purchases) whose fall is harmful")
    assert sum(n.startswith("For a count guardrail") for n in notes) == 1


def _summary_entry(status: str, *, not_verified=(False, False), unreachable=()) -> dict:
    references = {
        name: {"evaluated": True, "not_verified": flag}
        for name, flag in zip(("control", "baseline"), not_verified, strict=True)
    }
    return {"status": status, "references": references, "unreachable": list(unreachable)}


def test_the_summary_counts_and_its_line_are_those_of_the_entries() -> None:
    entries = [
        _summary_entry("breach_shown"),
        _summary_entry("breach_possible"),
        _summary_entry("within_tolerance", not_verified=(True, True)),
        _summary_entry("within_tolerance"),
        _summary_entry("not_evaluated"),
    ]

    summary = summarise(entries)

    assert summary["tests"] == 5 and summary["not_verified"] == 1
    assert summary["tolerance_out_of_reach"] == 0
    assert summary["line"] == (
        "RES-004: 5 comparisons of an arm against control on a guardrail, a breach shown in 1, "
        "possible in 1, 2 within the tolerance (1 of them with an interval that reaches beyond "
        "it, so the data cannot rule out a breach), 1 not evaluated."
    )
    assert summarise(entries[:1])["line"].startswith("RES-004: 1 comparison of an arm")


def test_a_comparison_is_not_ruled_out_if_either_reference_reaches_beyond_the_tolerance() -> None:
    one_side = _summary_entry("within_tolerance", not_verified=(False, True))
    unmeasured = _summary_entry("within_tolerance", not_verified=(True, False))
    unmeasured["references"]["control"] = {"evaluated": False, "reason": "no"}  # no key at all
    not_within = _summary_entry("breach_possible", not_verified=(True, True))

    assert summarise([one_side])["not_verified"] == 1
    assert summarise([unmeasured])["not_verified"] == 0  # its only mark is on the unmeasured side
    assert summarise([not_within])["not_verified"] == 0  # it is a finding, not a pass


def test_the_summary_line_says_how_many_comparisons_no_data_could_have_breached() -> None:
    both = ["control", "baseline"]
    entries = [
        _summary_entry("within_tolerance", unreachable=both),
        _summary_entry("within_tolerance", unreachable=["baseline"]),
        _summary_entry("within_tolerance"),
    ]

    summary = summarise(entries)

    assert summary["tolerance_out_of_reach"] == 1
    assert summary["line"].endswith(
        " In 1 of them the tolerance is not below the largest possible harm, so no data could "
        "show a breach."
    )
    assert "largest possible harm" not in summarise(entries[1:])["line"]


@pytest.mark.parametrize(
    "scenario", ["regression", "possible", "moved", "binary", "unreachable", "not_evaluated"]
)
def test_every_note_is_ascii_and_names_no_cause(raw_spec, scenario: str) -> None:
    if scenario == "unreachable":  # a fall of all of the baseline: the sentence about the limit
        rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1, 1, 0, 1] * 20)
        context = _context(raw_spec, rows, {**SESSIONS, "tolerance_relative": 1.0})
    elif scenario == "not_evaluated":  # neither reading could be made: the reasons are given
        rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1])
        context = _context(raw_spec, rows, SESSIONS)
    elif scenario == "regression":
        context = _regression(raw_spec, PURCHASED)
    elif scenario == "possible":
        rows, guardrail = _drawn(4)
        context = _context(raw_spec, rows, guardrail)
    elif scenario == "moved":
        rows = _sessions("control", [2, 2, 3, 1] * 60) + _sessions("variant_b", [2, 2, 3, 1] * 60)
        context = _context(raw_spec, rows, SESSIONS)
    else:
        rows = [Row(f"p_{i}", "control", purchases=1 if i < 2 else 0) for i in range(200)]
        rows += [Row(f"q_{i}", "variant_b", purchases=1 if i < 12 else 0) for i in range(200)]
        context = _context(raw_spec, rows, PURCHASED)

    for note in guardrail_report(context)["notes"]:
        assert note.isascii(), note
        for word in BANNED:
            assert word not in note.lower(), (word, note)


def test_late_exposed_players_are_not_read(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [3, 4, 2, 3] * 80)
    rows += [
        Row(f"late_{i}", "variant_b", sessions=0, purchases=1, first_purchase_at=at())
        for i in range(60)
    ]  # first exposed after their first purchase: not analysed (design section 21.3)

    context = _context(raw_spec, rows, SESSIONS)

    assert RES_004.evaluate(context) is None
    assert guardrail_report(context)["tests"][0]["n"]["arm"] == 320


def test_groups_that_do_not_vary_leave_only_the_registered_baseline_to_read(raw_spec) -> None:
    rows = crowd("control", 5, sessions=3) + crowd("variant_b", 5, sessions=3)

    report = guardrail_report(_context(raw_spec, rows, SESSIONS))

    (entry,) = report["tests"]
    assert entry["references"]["control"]["reason"].startswith(
        "neither variant_b nor control varies"
    )
    assert entry["references"]["baseline"]["no_variation"] is True
    assert entry["status"] == "within_tolerance" and entry["references_agree"] is None


# --- What is held back, what is not measured, and how the figures are written ---------------


def _revenue_rows(seed: int, *, control_mean: float, arm_mean: float | None, n: int = 400):
    """Revenue of players, a fifth of them at 0 and the rest lognormal around a given mean; the
    arm has the same values as control when `arm_mean` is None."""
    rng = random.Random(seed)

    def draw(mean: float) -> list[float]:
        return [
            0.0 if i % 5 == 0 else round(rng.lognormvariate(0, 1.2) * mean / 1.2, 3)
            for i in range(n)
        ]

    control = draw(control_mean)
    arm = control if arm_mean is None else draw(arm_mean)
    return [Row(f"c_{i:04d}", "control", revenue=v) for i, v in enumerate(control)] + [
        Row(f"v_{i:04d}", "variant_b", revenue=v) for i, v in enumerate(arm)
    ]


def test_the_registered_baseline_alone_cannot_show_a_fall_of_a_revenue_like_guardrail(
    raw_spec,
) -> None:
    """Both arms sit near 0.4 USD per player against a registered baseline of 1.0: the interval
    for the arm's own mean is wholly below the baseline, and so would be a blocker for any
    skewed guardrail whose true mean the sample happened to under-run."""
    rows = _revenue_rows(11, control_mean=0.35, arm_mean=None)

    finding = RES_004.evaluate(_context(raw_spec, rows, REVENUE_GUARDRAIL))

    assert finding is not None and finding.severity == "warning"
    (entry,) = finding.evidence["tests"]
    baseline = entry["references"]["baseline"]
    assert baseline["uncapped_tier"] == "shown" and baseline["tier"] == "possible"
    assert baseline["capped_by"] == "heavy_tail" and entry["status"] == "breach_possible"
    assert entry["references"]["control"]["tier"] == "within"
    text = " ".join(finding.evidence["notes"])
    assert "but this reading is held to possible" in text
    assert "the t interval for a mean cannot be trusted to show a breach on its own" in text
    assert "the reading against control's mean is not held." in text


def test_a_real_fall_of_revenue_against_control_is_still_shown(raw_spec) -> None:
    rows = _revenue_rows(12, control_mean=1.6, arm_mean=0.6)

    finding = RES_004.evaluate(_context(raw_spec, rows, REVENUE_GUARDRAIL))

    assert finding is not None and finding.severity == "blocker"
    (entry,) = finding.evidence["tests"]
    assert entry["references"]["control"]["tier"] == "shown" and "control" in entry["decided_by"]
    assert entry["references"]["control"]["capped_by"] is None


def test_the_moved_baseline_sentence_blames_the_arm_for_nothing_when_the_arm_is_within(
    raw_spec,
) -> None:
    """Control sits at 2 against a baseline of 3, the arm at 3.2: the baseline has moved, the arm
    breaches nothing, and the note must not speak of a breach that is not there."""
    rows = _sessions("control", [2, 2, 3, 1] * 60) + _sessions("variant_b", [3, 4, 3, 3] * 60)
    report = guardrail_report(_context(raw_spec, rows, SESSIONS))

    (entry,) = report["tests"]
    note = report["notes"][1]

    assert entry["baseline_has_moved"] and entry["references"]["baseline"]["tier"] == "within"
    assert "so the baseline may no longer describe this traffic." in note
    assert "caused it" not in note


def test_an_arm_at_zero_against_a_control_that_is_not_is_not_excused_by_the_baseline(
    raw_spec,
) -> None:
    rows = _sessions("control", [1, 2, 1, 2] * 50) + _sessions("variant_b", [0] * 200)

    note = guardrail_report(_context(raw_spec, rows, {**SESSIONS, "baseline": 3.0}))["notes"][1]

    assert "Control itself is beyond the tolerance of the registered baseline" in note
    assert "so the baseline may no longer describe this traffic." in note
    assert "caused it" not in note  # the arm is plainly the difference


@pytest.mark.parametrize(
    ("tolerance", "label", "harm_text"),
    [
        (0.0125, "tolerance 1.25%", "a tolerance of 1.25%,"),
        (0.29, "tolerance 29.0%", "a tolerance of 29.0%,"),
        (0.018, "tolerance 1.8%", "a tolerance of 1.8%,"),
        (0.072, "tolerance 7.2%", "a tolerance of 7.2%,"),
        (0.10, "tolerance 10.0%", "a tolerance of 10.0%,"),
    ],
)
def test_the_registered_tolerance_is_printed_as_it_was_registered(
    raw_spec, tolerance, label, harm_text
) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [2, 3, 1, 2] * 80)

    note = guardrail_report(
        _context(raw_spec, rows, {**SESSIONS, "tolerance_relative": tolerance})
    )["notes"][1]

    assert f"({'decrease'} is harmful, {label}):" in note
    assert harm_text in note
    assert "0000%" not in note


def test_a_harm_just_past_the_tolerance_is_not_printed_as_at_it(raw_spec) -> None:
    rng = random.Random(21)
    control = [rng.randint(2, 4) for _ in range(4000)]
    arm = list(control)
    arm[:400] = [max(0, v - 1) for v in arm[:400]]  # a few percent fewer sessions
    rows = _sessions("control", control) + _sessions("variant_b", arm)
    guardrail = {**SESSIONS, "baseline": sum(control) / len(control)}
    first = guardrail_report(_context(raw_spec, rows, guardrail))
    harm = first["tests"][0]["references"]["baseline"]["harm"]["point"]
    tolerance = int(1000 * harm) / 1000  # below the harm, and at 1 decimal of a percent the same
    assert 0.0 < harm - tolerance < 0.001

    report = guardrail_report(
        _context(raw_spec, rows, {**guardrail, "tolerance_relative": tolerance})
    )

    note = report["notes"][1]
    assert f"tolerance {100 * tolerance:.1f}%" in note
    assert f"the harm is {100 * harm:.2f}% of the baseline" in note  # not 1 decimal: at it


def test_a_tolerance_no_fall_can_exceed_says_so_and_is_counted(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [1, 1, 0, 1] * 80)
    context = _context(raw_spec, rows, {**SESSIONS, "tolerance_relative": 1.0})

    report = guardrail_report(context)

    assert RES_004.evaluate(context) is None  # a fall of 100% is not more than 100%
    (entry,) = report["tests"]
    assert entry["unreachable"] == ["control", "baseline"] and entry["status"] == "within_tolerance"
    assert report["summary"]["tolerance_out_of_reach"] == 1
    assert (
        "In 1 of them the tolerance is not below the largest possible harm"
        in (report["summary"]["line"])
    )
    assert (
        "so a tolerance of 100.0% cannot be exceeded and no data could show a breach of this "
        "guardrail."
    ) in report["notes"][1]


def test_a_rate_that_cannot_double_cannot_breach_a_baseline_of_half_with_a_tolerance_of_all(
    raw_spec,
) -> None:
    guardrail = {**PURCHASED, "baseline": 0.5, "tolerance_relative": 1.0}
    rows = [Row(f"p_{i}", "control", purchases=1 if i < 20 else 0) for i in range(200)]
    rows += [Row(f"q_{i}", "variant_b", purchases=1 if i < 100 else 0) for i in range(200)]

    report = guardrail_report(_context(raw_spec, rows, guardrail))

    (entry,) = report["tests"]
    assert entry["unreachable"] == ["baseline"]
    assert entry["references"]["baseline"]["tier"] == "within"
    assert entry["references"]["control"]["tier"] == "shown"  # from 10% to 50% is five times
    assert report["summary"]["tolerance_out_of_reach"] == 0
    assert (
        "so the reading against the registered baseline cannot show a breach; the reading "
        "against control's mean can only if control's rate is below 50.0%."
    ) in report["notes"][1]


def test_numbers_too_large_or_too_small_are_reported_as_such_and_never_crash(raw_spec) -> None:
    control = [Row(f"c_{i}", "control", revenue=1e-170 * (1 + i % 2)) for i in range(20)]
    arm = [Row(f"v_{i}", "variant_b", revenue=1e150 * (1 + i % 2)) for i in range(20)]
    for direction in ("decrease", "increase"):
        guardrail = {**REVENUE_GUARDRAIL, "harmful_direction": direction}

        report = guardrail_report(_context(raw_spec, control + arm, guardrail))

        (entry,) = report["tests"]
        assert entry["references"]["control"]["evaluated"] is False
        assert "too large to represent" in entry["references"]["control"]["reason"]
        json.dumps(report, allow_nan=False)  # no infinity reaches the evidence
        assert max(len(token) for note in report["notes"] for token in note.split()) < 30


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baseline", 1e300),
        ("baseline", 1e-300),
        ("baseline", 1e-307),  # a share of it is beyond the floats
        ("baseline", 2e-308),
        ("tolerance_relative", 1e-300),
        ("tolerance_relative", 1e300),
    ],
)
def test_a_registered_number_of_extreme_size_is_written_with_an_exponent_and_never_as_infinity(
    raw_spec, field, value
) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [2, 3, 1, 2] * 20)

    report = guardrail_report(_context(raw_spec, rows, {**SESSIONS, field: value}))

    json.dumps(report, allow_nan=False)
    text = " ".join(report["notes"])
    assert "inf" not in text.lower().replace("information", "")
    assert max(len(token) for token in text.split()) < 40


def test_the_reasons_name_the_group_and_none_of_the_internals(raw_spec) -> None:
    arm = [Row(f"v_{i}", "variant_b", revenue=10.0**200 * (1 + i % 3)) for i in range(20)]
    control = [Row(f"c_{i}", "control", revenue=1.0 + i % 3) for i in range(20)]

    report = guardrail_report(_context(raw_spec, control + arm, REVENUE_GUARDRAIL))

    text = " ".join(report["notes"])
    for internal in ("treatment", "values holds", "group needs"):
        assert internal not in text, internal


def test_two_groups_at_zero_are_not_a_collapse_of_one_of_them(raw_spec) -> None:
    rows = _sessions("control", [0] * 100) + _sessions("variant_b", [0] * 100)

    note = guardrail_report(_context(raw_spec, rows, SESSIONS))["notes"][1]

    assert "control's mean is not above 0, so a share of it is undefined" in note
    assert "a fall of the whole" not in note


def test_the_note_on_revenue_is_there_once_if_any_comparison_is_revenue_like(raw_spec) -> None:
    rows = (
        _sessions("control", [3, 4, 2, 3] * 80)
        + _sessions("variant_b", [3, 4, 2, 3] * 80)
        + _sessions("variant_c", [3, 4, 2, 3] * 80)
    )
    rows = [
        Row(r.player_id, r.arm, sessions=r.sessions, revenue=2.0 if i % 5 == 0 else 0.0)
        for i, r in enumerate(rows)
    ]
    guardrails = [SESSIONS, REVENUE_GUARDRAIL]
    spec = results_spec(raw_spec, guardrails=guardrails, **PRIMARY)  # the three-arm default

    report = guardrail_report(ResultsContext.of(spec, build_data(rows)))

    assert sum(e["family"] == "revenue_like" for e in report["tests"]) == 2  # one for each arm
    assert sum(n.startswith("For a revenue-like guardrail") for n in report["notes"]) == 1


# --- Numbers beyond the floats, wording of what moved, and the notes on the families -------------


@pytest.mark.parametrize("direction", ["decrease", "increase"])
@pytest.mark.parametrize("huge_arm", ["control", "variant_b"])
def test_a_group_of_huge_equal_values_does_not_crash_the_report(
    raw_spec, direction, huge_arm
) -> None:
    """Forty players at 1e307 sum to more than any float, but their mean is their value."""
    small = [1.0, 2.0, 3.0] * 14
    rows = [
        Row(f"c_{i:03d}", "control", revenue=1e307 if huge_arm == "control" else small[i])
        for i in range(40)
    ] + [
        Row(f"v_{i:03d}", "variant_b", revenue=1e307 if huge_arm == "variant_b" else small[i])
        for i in range(40)
    ]
    guardrail = {**REVENUE_GUARDRAIL, "harmful_direction": direction}

    report = guardrail_report(_context(raw_spec, rows, guardrail))
    RES_004.evaluate(_context(raw_spec, rows, guardrail))  # no TypeError from a missing mean

    (entry,) = report["tests"]
    assert entry["means"]["control" if huge_arm == "control" else "arm"] == 1e307
    json.dumps(report, allow_nan=False)
    assert "None" not in " ".join(report["notes"])


@pytest.mark.parametrize("where", ["control", "variant_b"])
def test_a_value_beyond_every_float_is_a_mean_that_is_not_there_and_does_not_crash(
    raw_spec, where
) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [3, 4, 2, 3] * 20)
    rows[0 if where == "control" else -1] = Row("odd_0000", where, sessions=10**400)

    context = _context(raw_spec, rows, SESSIONS)
    report = guardrail_report(context)
    RES_004.evaluate(context)

    (entry,) = report["tests"]
    assert entry["means"]["control" if where == "control" else "arm"] is None
    json.dumps(report, allow_nan=False)
    assert "None" not in " ".join(report["notes"])


def test_the_caveat_about_cause_is_left_out_where_the_reading_against_control_shows_it_too(
    raw_spec,
) -> None:
    """Control sits at 2 against a baseline of 3 and the arm at 1: both readings show a breach,
    and the arm is plainly part of it."""
    rows = _sessions("control", [2, 2, 3, 1] * 60) + _sessions("variant_b", [1, 1, 2, 0] * 60)

    report = guardrail_report(_context(raw_spec, rows, SESSIONS))

    (entry,) = report["tests"]
    assert entry["baseline_has_moved"] and entry["references"]["control"]["tier"] == "shown"
    assert "so the baseline may no longer describe this traffic." in report["notes"][1]
    assert "caused it" not in report["notes"][1]


def test_the_moved_baseline_says_that_control_own_reading_was_held_and_why(raw_spec) -> None:
    rows = _revenue_rows(11, control_mean=0.35, arm_mean=None)

    note = guardrail_report(_context(raw_spec, rows, REVENUE_GUARDRAIL))["notes"][1]

    assert (
        "Control itself is possibly beyond the tolerance of the registered baseline (a harm of"
        in note
    )
    assert (
        ": the whole interval is beyond the tolerance, but this reading is held to possible for "
        "a revenue-like guardrail whose fall is harmful), so the baseline may no longer describe "
        "this traffic"
    ) in note


def test_the_moved_baseline_says_so_when_control_is_a_group_with_no_width(raw_spec) -> None:
    # half of the arm is at 2 sessions, as control is: four alike is one time in sixteen
    rows = _sessions("control", [2] * 4) + _sessions("variant_b", [2, 2, 3, 1] * 25)

    note = guardrail_report(_context(raw_spec, rows, SESSIONS))["notes"][1]

    assert (
        ": every control player (4) has the same value, so that interval has no width and chance "
        "could explain that, so the reading is held to possible), so the baseline may no longer "
        "describe this traffic"
    ) in note


def test_controls_own_place_is_judged_by_chance_and_so_is_not_a_cliff(raw_spec) -> None:
    arm = _sessions("variant_b", [3, 4, 2, 3] * 25)
    for control in ([0] * 100, [0] * 99 + [1]):
        note = guardrail_report(_context(raw_spec, _sessions("control", control) + arm, SESSIONS))[
            "notes"
        ][1]

        assert "Control itself is beyond the tolerance of the registered baseline" in note
        assert "held to possible" not in note.split("Control itself")[1]


def test_a_comparison_that_could_not_be_measured_still_says_that_its_tolerance_is_out_of_reach(
    raw_spec,
) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1])

    report = guardrail_report(_context(raw_spec, rows, {**SESSIONS, "tolerance_relative": 1.0}))

    (entry,) = report["tests"]
    assert entry["status"] == "not_evaluated" and report["summary"]["tolerance_out_of_reach"] == 1
    assert (
        "so a tolerance of 100.0% cannot be exceeded and no data could show a breach"
        in (report["notes"][1])
    )


def test_a_binary_guardrail_with_no_analysed_control_has_no_rate_to_call_rough(raw_spec) -> None:
    rows = [Row(f"q_{i}", "variant_b", purchases=1 if i < 250 else 0) for i in range(500)]

    (entry,) = guardrail_report(_context(raw_spec, rows, PURCHASED))["tests"]

    assert entry["n"]["control"] == 0 and entry["small_counts"] is False


def test_the_note_on_revenue_is_pinned_in_every_part(raw_spec) -> None:
    fall = _revenue_rows(11, control_mean=0.35, arm_mean=None)
    rise = {**REVENUE_GUARDRAIL, "harmful_direction": "increase", "baseline": 0.3}

    for guardrail, held in ((REVENUE_GUARDRAIL, True), (rise, False)):
        notes = guardrail_report(_context(raw_spec, fall, guardrail))["notes"]
        (note,) = [n for n in notes if n.startswith("For a revenue-like guardrail")]
        note = " ".join(note.split())

        for phrase in (
            "a guardrail is taken to be one by its metric name, and Referee has not looked at "
            "its values",
            "less reliable than 95% suggests, and Referee has not measured by how much",
            "lies wholly below the true mean more often than it should, and hardly ever wholly "
            "above it",
            "RES-008 reports simulated rates for Welch's interval for a difference of means; "
            "those are not the rates of these intervals.",
        ):
            assert phrase in note, phrase
        assert ("a breach is shown only by the reading against control's mean" in note) is held
        assert ("so a rise is carried by the reading against control's mean" in note) is not held
        assert "RES-008 gives the measured rates" not in note


def test_a_harm_of_exactly_zero_is_not_a_gain_and_is_written_as_zero(raw_spec) -> None:
    values = [3, 4, 2, 3] * 20
    rows = _sessions("control", values) + _sessions("variant_b", values)

    note = guardrail_report(
        _context(raw_spec, rows, {**SESSIONS, "baseline": sum(values) / len(values)})
    )["notes"][1]

    assert "the harm is 0.0% of control's mean (-" in note and "a gain" not in note


def test_a_control_possibly_beyond_the_baseline_has_its_whole_sentence_pinned(raw_spec) -> None:
    rng = random.Random(1)
    guardrail = {**SESSIONS, "harmful_direction": "increase"}
    rows = [Row(f"c_{i:03d}", "control", sessions=rng.randint(0, 8)) for i in range(40)]
    rows += [Row(f"v_{i:03d}", "variant_b", sessions=rng.randint(0, 8)) for i in range(40)]

    note = guardrail_report(_context(raw_spec, rows, guardrail))["notes"][1]

    assert (
        "Control itself is possibly beyond the tolerance of the registered baseline (a harm of "
        "32.5%, 2.9% to 62.1%), so the baseline may no longer describe this traffic; a breach "
        "against the baseline alone does not show that variant_b caused it."
    ) in note


def test_a_group_of_one_value_that_was_not_compared_is_not_believed_to_show_a_breach() -> None:
    entry = {"arm": "variant_b", "n": {"arm": 12, "control": 500}}
    reference = {"constant_group": "arm", "chance_all_alike": None, "capped_by": "no_variation"}

    text = _same_value_sentence(entry, reference, "baseline")

    assert text == (
        " Every player of variant_b (12) has the same value, so that interval has no width, and "
        "an interval with no width is not believed to show a breach."
    )
    ratio = _same_value_sentence(entry, {**reference, "constant_group": "control"}, "control")
    assert ratio.startswith(" Every player of control (500) has the same value, so the interval")
    assert "takes its width from variant_b alone" in ratio


# --- Round three: chance in the wording, the caveat for a rate, the families -----------------


@pytest.mark.parametrize(
    ("control", "arm", "chance_text", "explained"),
    [
        ([3] * 80 + [4] * 10 + [2] * 10, [3, 3, 3], "about 51% of samples", False),
        ([3] * 50 + [1] * 25 + [5] * 25, [3] * 5, "about 3.1% of samples", False),
        ([3] * 40 + [1] * 60, [3] * 12, "under 0.1% of samples", True),
    ],
)
def test_a_constant_group_that_is_not_held_is_still_told_the_truth_about_chance(
    raw_spec, control, arm, chance_text, explained
) -> None:
    """The ending follows the chance, not whether the reading happened to be capped: 51% is not
    something that 'chance does not explain'."""
    rows = _sessions("control", control) + _sessions("variant_b", arm)

    note = guardrail_report(_context(raw_spec, rows, SESSIONS))["notes"][1]

    assert chance_text in note
    explain = "which chance does not explain." in note
    not_ruled_out = "so chance is not ruled out." in note
    assert (explain, not_ruled_out) == (explained, not explained)


@pytest.mark.parametrize(("players", "caveat"), [(5, True), (14, True), (30, False), (200, False)])
def test_a_rate_at_zero_keeps_the_caveat_until_chance_cannot_explain_it(
    raw_spec, players, caveat
) -> None:
    """Control's rate is 20% against a baseline of 40%: 5 players with no purchase is one time in
    three (0.8 to the fifth), 30 about one time in 800."""
    guardrail = {**PURCHASED, "baseline": 0.4, "harmful_direction": "decrease"}
    rows = [Row(f"c_{i}", "control", purchases=1 if i < 20 else 0) for i in range(100)]
    rows += [Row(f"v_{i}", "variant_b", purchases=0) for i in range(players)]

    note = guardrail_report(_context(raw_spec, rows, guardrail))["notes"][1]

    assert "Control itself is beyond the tolerance of the registered baseline" in note
    assert ("does not show that variant_b caused it" in note) is caveat


def test_the_note_on_a_revenue_fall_says_a_group_with_no_spread_is_judged_by_chance(
    raw_spec,
) -> None:
    rows = _revenue_rows(11, control_mean=0.35, arm_mean=None)

    notes = guardrail_report(_context(raw_spec, rows, REVENUE_GUARDRAIL))["notes"]

    (note,) = [n for n in notes if n.startswith("For a revenue-like guardrail")]
    assert "of a group with some spread is held to possible there" in note
    assert "is judged by chance, as said with its reading" in note


@pytest.mark.parametrize(
    ("guardrail", "direction", "present"),
    [
        (SESSIONS, "decrease", True),
        (SESSIONS, "increase", False),
        (REVENUE_GUARDRAIL, "decrease", False),  # revenue has a note of its own
    ],
)
def test_the_count_note_is_for_a_count_whose_fall_is_harmful(
    raw_spec, guardrail, direction, present
) -> None:
    rows = [
        Row(f"{arm}_{i:05d}", arm, sessions=v, revenue=2.0 if i % 5 == 0 else 0.0)
        for arm in ("control", "variant_b")
        for i, v in enumerate([3, 4, 2, 3] * 20)
    ]

    notes = guardrail_report(
        _context(raw_spec, rows, {**guardrail, "harmful_direction": direction})
    )["notes"]

    assert any(n.startswith("For a count guardrail") for n in notes) is present
    assert not any("too" in n and n.startswith("A count") for n in notes)


def test_the_limit_for_control_is_never_stated_below_the_true_limit(raw_spec) -> None:
    """A tolerance of 70% on a baseline of 60%: control's rate can show a rise only below
    100 / 1.7 = 58.82...%, which is stated as 58.9% and not as 58.8%."""
    guardrail = {**PURCHASED, "baseline": 0.6, "tolerance_relative": 0.7}
    rows = [Row(f"c_{i}", "control", purchases=1 if i < 50 else 0) for i in range(100)]
    rows += [Row(f"v_{i}", "variant_b", purchases=1 if i < 50 else 0) for i in range(100)]

    note = guardrail_report(_context(raw_spec, rows, guardrail))["notes"][1]

    assert "control's rate is below 58.9%." in note


@pytest.mark.parametrize(
    ("chance", "text"),
    [
        (0.0005, "under 0.1% of samples"),
        (0.00099, "under 0.1% of samples"),
        (0.001, "about 0.10% of samples"),
        (0.0234, "about 2.3% of samples"),
        (0.5, "about 50% of samples"),
    ],
)
def test_the_chance_is_written_with_two_figures_and_rare_chances_as_a_bound(chance, text) -> None:
    assert _chance_text(chance) == text


def test_a_moved_baseline_with_an_arm_that_cannot_be_read_does_not_describe_control(
    raw_spec,
) -> None:
    """With a baseline of 1e-300 and huge arm values the arm's own reading is not measured; the
    note must not speak of control's place against a reading it does not have."""
    control = [Row(f"c_{i}", "control", revenue=1.0 + i % 3) for i in range(20)]
    arm = [Row(f"v_{i}", "variant_b", revenue=1e10 * (1 + i % 3)) for i in range(20)]
    guardrail = {**REVENUE_GUARDRAIL, "harmful_direction": "increase", "baseline": 1e-300}

    report = guardrail_report(_context(raw_spec, control + arm, guardrail))

    (entry,) = report["tests"]
    assert entry["baseline_has_moved"] and not entry["references"]["baseline"]["evaluated"]
    assert "Control itself is" not in report["notes"][1]
    json.dumps(report, allow_nan=False)
