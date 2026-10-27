"""RES-007: the effect differs between cohorts of first exposure (design sections 21.5 to 21.7).

The data are exact: every cohort holds 80 players whose session counts have a known mean and
spread, so each scenario's outcome can be reasoned out before it is run.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import get_args

import pytest
from cohort_helpers import (
    THREE_ARMS,
    cohort_context,
    cohort_rows,
    sized_context,
    spread,
)
from results_helpers import TWO_ARMS, Row, at

from referee.cohort_effects import (
    NULL_FLAG_RATE_MAX,
    NULL_FLAG_RATE_MEAN,
    DropReason,
    ScaleTest,
    cohort_test,
    detectable_shifts,
)
from referee.cohorts import (
    Attempt,
    Binding,
    CohortPlan,
    GateReason,
    Minimum,
    NotEvaluated,
    Price,
    plan_cohorts,
    traffic_needed,
)
from referee.methods import StatsError
from referee.results import ResultsContext
from referee.rules import RESULTS_RULES
from referee.rules.cohorts import (
    _amount,
    _binding_text,
    _count,
    _entry_note,
    _players,
    _price_evidence,
    _price_text,
    _scale,
    _share,
    _shifts,
    _times,
    _when,
    cohort_report,
    summarise,
)

RES_007 = next(rule for rule in RESULTS_RULES if rule.id == "RES-007")
RES_013 = next(rule for rule in RESULTS_RULES if rule.id == "RES-013")
BANNED = ("novelty", "decay", "stable", "no difference", "found no")
GUARDRAIL = {
    "name": "purchased_7d",
    "kind": "binary",
    "baseline": 0.05,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.1,
}


def _weeks(means: list[int], unit: int = 1) -> dict[int, list[int]]:
    """Weekly cohorts of 80 players each: `means[b]` is the exact mean of week b."""
    return {block: spread(mean, unit) for block, mean in enumerate(means)}


FLAT = [10] * 5
FADE = [16, 14, 12, 11, 10]  # against FLAT: differences of 6, 4, 2, 1 and 0


def _context(
    raw_spec,
    variants: dict[str, dict[int, list[int]]],
    *,
    control: dict[int, list[int]] | None = None,
    days: int = 35,
    stretch: bool = True,
    **more,
) -> ResultsContext:
    """Control and the variants, one row per player, planned for `days` days.

    With `stretch`, one control player is assigned on the last day, so that the assignments
    span the planned duration and the run is not an interim look.
    """
    rows = cohort_rows("control", _weeks(FLAT) if control is None else control)
    for arm, sessions in variants.items():
        rows += cohort_rows(arm, sessions)
    if stretch:
        last = max(i for i, row in enumerate(rows) if row.arm == "control")
        rows[last].assigned_at = at(days - 1, 23)
        rows[last].exposed_at = at(days - 1, 23.5)
    arms = TWO_ARMS if len(variants) == 1 else THREE_ARMS
    return cohort_context(raw_spec, rows, days=days, arms=arms, **more)


def _quiet(raw_spec):
    return _context(raw_spec, {"variant_b": _weeks(FLAT), "variant_c": _weeks(FLAT)})


def _fading(raw_spec, **more):
    return _context(raw_spec, {"variant_b": _weeks(FADE), "variant_c": _weeks(FLAT)}, **more)


def _low_information(raw_spec):
    control = _weeks([20] * 5, unit=4)
    variant = _weeks([28, 24, 22, 21, 20], unit=4)
    return _context(raw_spec, {"variant_b": variant}, control=control, design__mde_relative=0.05)


def _baseline_moves(raw_spec):
    """A constant +50% relative effect on a control mean that climbs from 10 to 50."""
    scale = [2, 4, 6, 8, 10]
    control = {b: [c * v for v in (3, 4, 5, 6, 7)] * 16 for b, c in enumerate(scale)}
    variant = {b: [3 * c * v // 2 for v in (3, 4, 5, 6, 7)] * 16 for b, c in enumerate(scale)}
    return _context(raw_spec, {"variant_b": variant}, control=control)


def _too_short(raw_spec):
    return _context(raw_spec, {"variant_b": _weeks(FADE[:2])}, control=_weeks(FLAT[:2]), days=14)


def _units(raw_spec):
    return _fading(raw_spec, population__randomization_unit="session")


def _missing_scale(raw_spec):
    """The variant has no sessions at all in 4 of 5 weeks: its log ratio cannot be taken."""
    variant = {**{b: [0] * 80 for b in range(4)}, 4: spread(10)}
    return _context(raw_spec, {"variant_b": variant})


def _guardrail_without_variation(raw_spec):
    return _fading(raw_spec, guardrails=[GUARDRAIL])


def _configuration_change(raw_spec):
    """The fade, with arm variant_b moving to version 2 half way through week 2."""
    variant = _weeks(FADE)
    early = {0: variant[0], 1: variant[1], 2: variant[2][:40]}
    late = {2: variant[2][40:], 3: variant[3], 4: variant[4]}
    rows = cohort_rows("control", _weeks(FLAT))
    rows += cohort_rows("variant_b", early, tag="a") + cohort_rows(
        "variant_b", late, tag="b", version_of=lambda block: 2
    )
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(34, 23), at(34, 23.5)
    return cohort_context(raw_spec, rows, days=35, arms=TWO_ARMS)


def _absolute_effect_constant(raw_spec):
    """A constant +5 on a control mean that climbs from 10 to 50: the relative effect shrinks."""
    scale = [2, 4, 6, 8, 10]
    control = {b: [c * v for v in (3, 4, 5, 6, 7)] * 16 for b, c in enumerate(scale)}
    variant = {b: [value + 5 for value in control[b]] for b in control}
    return _context(raw_spec, {"variant_b": variant}, control=control)


def _unequal_arms(raw_spec):
    """Twice as many players in the variant as in control, in every week."""
    variant = {b: spread(mean, 1, 160) for b, mean in enumerate(FADE)}
    return _context(raw_spec, {"variant_b": variant})


def _configuration_boundary(raw_spec):
    """The fade, with variant_b moving to version 2 exactly at the start of week 2."""
    rows = cohort_rows("control", _weeks(FLAT))
    rows += cohort_rows("variant_b", _weeks(FADE), version_of=lambda block: 1 + (block >= 2))
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(34, 23), at(34, 23.5)
    return cohort_context(raw_spec, rows, days=35, arms=TWO_ARMS)


def _sized(raw_spec, arm, control, days, **more):
    return sized_context(raw_spec, arm, control, days=days, **more)


def _flat_sizes(count: int, weeks: int) -> dict[int, int]:
    return dict.fromkeys(range(weeks), count)


TRAFFIC_SCENARIOS = {
    "traffic_median": lambda raw: _sized(raw, _flat_sizes(20, 5), _flat_sizes(20, 5), 35),
    "traffic_median_complete": lambda raw: _sized(
        raw, _flat_sizes(20, 5), _flat_sizes(20, 5), 35, stretch=True
    ),
    "traffic_fortnight": lambda raw: _sized(raw, _flat_sizes(10, 8), _flat_sizes(10, 8), 56),
    "traffic_raised_floor": lambda raw: _sized(raw, _flat_sizes(80, 5), _flat_sizes(20, 5), 35),
    "traffic_floor_ratio": lambda raw: _sized(raw, EARLY_ARM, EARLY_CONTROL, 35),
    "traffic_spiky": lambda raw: _sized(raw, SPIKY, SPIKY, 35),
    "traffic_empty": lambda raw: _sized(
        raw, _flat_sizes(80, 3), {**_flat_sizes(80, 3), 4: 1}, 35, stretch=True
    ),
    "traffic_empty_interim": lambda raw: _sized(raw, _flat_sizes(80, 3), _flat_sizes(80, 3), 35),
    "traffic_short": lambda raw: _sized(raw, _flat_sizes(80, 2), _flat_sizes(80, 2), 14),
    "traffic_unequal": lambda raw: _sized(raw, _flat_sizes(100, 5), _flat_sizes(10, 5), 35),
    "traffic_waiting": lambda raw: _sized(
        raw, _flat_sizes(80, 3), _flat_sizes(80, 3), 21, exported_at=at(19)
    ),
    "traffic_after_waiting": lambda raw: _sized(raw, SPIKY, SPIKY, 35, exported_at=at(27)),
    "traffic_mixed": lambda raw: _sized(
        raw, _flat_sizes(40, 6), _flat_sizes(40, 6), 42, exported_at=at(40)
    ),
    "traffic_two_lengths_waiting": lambda raw: _sized(
        raw, _flat_sizes(20, 8), _flat_sizes(20, 8), 56, exported_at=at(30)
    ),
    "traffic_one_length_waiting": lambda raw: _sized(
        raw, {0: 10, 3: 10, 6: 10}, {0: 10, 3: 10, 6: 10}, 56, exported_at=at(30)
    ),
    "traffic_two_left_out": lambda raw: _sized(raw, LATE_THIN, LATE_THIN, 42, exported_at=at(33)),
    "traffic_exported_early": lambda raw: _sized(raw, EARLY, EARLY, 35, exported_at=at(33)),
    "traffic_one_length": lambda raw: _sized(raw, {0: 10, 3: 10, 6: 10}, {0: 10, 3: 10, 6: 10}, 56),
    "traffic_one_priced_arm": lambda raw: _sized(
        raw,
        _flat_sizes(20, 5),
        _flat_sizes(30, 5),
        35,
        extra={"variant_c": _flat_sizes(2, 5)},
        arms=THREE_ARMS,
    ),
    "traffic_three_arms": lambda raw: _sized(
        raw,
        _flat_sizes(20, 5),
        _flat_sizes(30, 5),
        35,
        extra={"variant_c": _flat_sizes(60, 5)},
        arms=THREE_ARMS,
    ),
}
SPIKY = {0: 100, 1: 100, 2: 100, 3: 10, 4: 10}
EARLY = {0: 40, 1: 40, 2: 40, 3: 12, 4: 25}
EARLY_ARM = {0: 100, 1: 100, 2: 100, 3: 20, 4: 20}
EARLY_CONTROL = {0: 60, 1: 60, 2: 60, 3: 13, 4: 13}
LATE_THIN = {0: 100, 1: 100, 2: 100, 3: 20, 4: 20, 5: 20}

SCENARIOS = {
    "quiet": _quiet,
    "fading": _fading,
    "low_information": _low_information,
    "baseline_moves": _baseline_moves,
    "too_short": _too_short,
    "units": _units,
    "missing_scale": _missing_scale,
    "guardrail_without_variation": _guardrail_without_variation,
    "configuration_change": _configuration_change,
    "configuration_boundary": _configuration_boundary,
    "absolute_effect_constant": _absolute_effect_constant,
    "unequal_arms": _unequal_arms,
    "existing_users": lambda raw_spec: _fading(raw_spec, population__kind="existing_users"),
    "interim": lambda raw_spec: _context(
        raw_spec, {"variant_b": _weeks(FADE)}, stretch=False, days=56
    ),
    **TRAFFIC_SCENARIOS,
}


def _by_arm(report: dict, metric: str | None = None) -> dict[str, dict]:
    return {t["arm"]: t for t in report["tests"] if metric in (None, t["metric"])}


def _config_of(context: ResultsContext):
    """The evidence of RES-013 for this context, as the rule's own check gives it."""
    return RES_013.check(context)


# --- The rule ------------------------------------------------------------------------------


def test_res_007_is_a_warning_between_res_003_and_res_008_citing_the_heterogeneity_literature():
    ids = [rule.id for rule in RESULTS_RULES]

    assert RES_007.severity == "warning" and RES_007.escalation is None
    assert ids[ids.index("RES-004") + 1 : ids.index("RES-008")] == ["RES-007"]
    assert ids[ids.index("RES-007") + 1 : ids.index("RES-011")] == ["RES-008"]
    for author in ("Cochran", "Higgins", "Trustworthy"):
        assert any(author in reference for reference in RES_007.references), author
    assert "0.025 divided by the number of non-control arms" in RES_007.fires_when


@pytest.mark.parametrize("name", SCENARIOS)
def test_no_text_of_the_rule_or_its_findings_names_a_cause_or_reads_a_quiet_result_as_none(
    raw_spec, name
) -> None:
    context = SCENARIOS[name](raw_spec)
    report = cohort_report(context, _config_of(context))
    texts = [
        RES_007.title,
        RES_007.fires_when,
        RES_007.why_it_matters,
        RES_007.remediation,
        *report["notes"],
    ]

    for text in texts:
        hits = [word for word in BANNED if word in text.lower()]
        assert not hits, (hits, text)


@pytest.mark.parametrize("name", SCENARIOS)
def test_the_evidence_is_plain_json(raw_spec, name) -> None:
    context = SCENARIOS[name](raw_spec)

    evidence = cohort_report(context, _config_of(context))

    assert json.loads(json.dumps(evidence, allow_nan=False)) == evidence


# --- Quiet, flagged and not evaluated ------------------------------------------------------


def test_a_quiet_experiment_raises_no_finding_but_the_report_still_counts_the_tests(
    raw_spec,
) -> None:
    context = _quiet(raw_spec)

    report = cohort_report(context, None)

    assert RES_007.evaluate(context) is None
    assert report["summary"]["line"] == (
        "RES-007: 2 tests, 0 flagged, 0 not evaluated, 0 low information"
    )
    assert {t["status"] for t in report["tests"]} == {"not_flagged"}


def test_a_fading_arm_is_flagged_and_an_unchanged_arm_is_not(raw_spec) -> None:
    context = _fading(raw_spec)

    finding = RES_007.evaluate(context)

    assert finding is not None and finding.severity == "warning"
    tests = _by_arm(finding.evidence)
    assert {arm: t["status"] for arm, t in tests.items()} == {
        "variant_b": "flagged",
        "variant_c": "not_flagged",
    }
    assert tests["variant_b"]["trigger"] == {"level": 0.0125, "absolute": True, "log_ratio": True}
    assert tests["variant_c"]["trigger"] == {"level": 0.0125, "absolute": False, "log_ratio": False}
    assert finding.evidence["summary"]["line"] == (
        "RES-007: 2 tests, 1 flagged, 0 not evaluated, 0 low information"
    )


def test_the_evidence_carries_the_numbers_of_the_cohort_test_it_ran(raw_spec) -> None:
    context = _fading(raw_spec)
    plan = plan_cohorts(context, "variant_b")
    expected = cohort_test(context, plan, context.metrics["sessions_7d"])

    shown = _by_arm(cohort_report(context, None))["variant_b"]

    assert shown["block_days"] == 7
    for scale in expected.scales:
        found = shown["scales"][scale.scale]
        heterogeneity = scale.heterogeneity
        assert found["q"]["p_value"] == heterogeneity.q_p_value
        assert found["q"]["degrees_of_freedom"] == heterogeneity.degrees_of_freedom == 4
        assert found["slope"]["p_value"] == heterogeneity.slope_p_value
        assert [c["block"] for c in found["cohorts"]] == [0, 1, 2, 3, 4]
        for cohort, number in zip(found["cohorts"], scale.cohorts, strict=True):
            assert cohort["estimate"] == pytest.approx(number.estimate, abs=1e-6)
            assert cohort["corrected_std_error"] == pytest.approx(
                number.corrected_std_error, abs=1e-6
            )
            assert (cohort["n_arm"], cohort["n_control"]) == (80, 80)
    estimates = [c["estimate"] for c in shown["scales"]["absolute"]["cohorts"]]
    assert estimates == pytest.approx([6, 4, 2, 1, 0], abs=1e-6)
    assert [c["mean_arm"] for c in shown["scales"]["absolute"]["cohorts"]] == FADE
    assert [c["mean_control"] for c in shown["scales"]["absolute"]["cohorts"]] == FLAT
    for cohort, number in zip(
        shown["scales"]["log_ratio"]["cohorts"], expected.log_ratio.cohorts, strict=True
    ):
        assert cohort["std_error"] == pytest.approx(number.std_error, abs=1e-6)
        assert cohort["std_error"] < cohort["corrected_std_error"]


def test_the_numbers_of_the_fading_arm_are_the_ones_worked_out_by_hand(raw_spec) -> None:
    """Each cohort holds 16 copies of mean-2 .. mean+2: variance 160/79 in both arms.

    The squared standard error of a difference is 2 * (160/79) / 80 = 0.050633, times the
    correction 158/156 (equal variances and sizes: nu = 158) gives 0.051282, a weight of 19.5.
    The differences 6, 4, 2, 1, 0 have mean 2.6 and sum of squares 23.2, so Q = 19.5 * 23.2 =
    452.4 on 4 degrees of freedom, I-squared is (452.4 - 4) / 452.4, and the slope over the
    block numbers is (-2*6 - 1*4 + 1*1) / 10 = -1.5 with standard error 1/sqrt(19.5 * 10). The
    control mean is 10 in every cohort, with a t interval of 10 +- 1.9905 * sqrt(160/79 / 80).
    """
    shown = _by_arm(cohort_report(_fading(raw_spec), None))["variant_b"]["scales"]["absolute"]

    assert shown["q"] == {
        "statistic": 452.4,
        "degrees_of_freedom": 4,
        "p_value": shown["q"]["p_value"],
        "i_squared": pytest.approx(0.991158, abs=1e-6),
    }
    assert shown["q"]["p_value"] == pytest.approx(1.3152e-96, rel=1e-3)
    assert shown["slope"]["value"] == pytest.approx(-1.5, abs=1e-6)
    assert shown["slope"]["std_error"] == pytest.approx(0.071611, abs=1e-6)
    assert shown["slope"]["p_value"] == pytest.approx(2.0253e-97, rel=1e-3)
    baseline = _by_arm(cohort_report(_fading(raw_spec), None))["variant_b"]["control_baseline"]
    assert [(c["n"], c["mean"]) for c in baseline["cohorts"]] == [(80, 10.0)] * 5
    assert baseline["cohorts"][0]["ci_low"] == pytest.approx(9.683297, abs=1e-6)
    assert baseline["cohorts"][0]["ci_high"] == pytest.approx(10.316703, abs=1e-6)
    assert baseline["homogeneity_p"] == pytest.approx(1.0) and baseline["moves"] is False


def test_the_plan_of_an_arm_shows_every_block_and_the_minimum_it_needed(raw_spec) -> None:
    context = _fading(raw_spec)
    registered = context.required_n("variant_b")
    minimum = {"registered": registered, "achieved": 400, "preferred": 30, "used": 30}

    plan = cohort_report(context, None)["plans"]["variant_b"]

    assert plan == {
        "block_days": 7,
        "usable": [0, 1, 2, 3, 4],
        "reason": None,
        "floor": 30,
        "allocation_ratio": 1.0,
        "as_of": None,
        "completeness_checked": False,
        "traffic_needed": None,
        "attempts": [
            {
                "block_days": 7,
                "window_blocks": 5,
                "sizes": [{"block": b, "arm": 80, "control": 80} for b in range(5)],
                "usable": [0, 1, 2, 3, 4],
                "usable_at_floor": [0, 1, 2, 3, 4],
                "preferred_used": False,
                "minimum_arm": minimum,
                "minimum_control": minimum,
                "median_smaller_arm": 80.0,
                "covers_window": True,
                "incomplete": [],
                "reason": None,
            }
        ],
    }


def test_a_scale_that_was_not_evaluated_has_no_detectable_shift(raw_spec) -> None:
    context = _missing_scale(raw_spec)
    test = cohort_test(context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"])

    assert _shifts(test.absolute, 0.025)["linear_fade"] > 0
    with pytest.raises(ValueError, match="the log_ratio scale was not evaluated"):
        _shifts(test.log_ratio, 0.025)


def test_every_arm_and_metric_is_listed_the_primary_metric_first(raw_spec) -> None:
    context = _fading(raw_spec, guardrails=[GUARDRAIL])

    report = cohort_report(context, None)

    assert [(t["metric"], t["arm"]) for t in report["tests"]] == [
        ("sessions_7d", "variant_b"),
        ("sessions_7d", "variant_c"),
        ("purchased_7d", "variant_b"),
        ("purchased_7d", "variant_c"),
    ]
    assert report["summary"]["tests"] == 4


def test_the_level_of_each_statistic_is_the_trigger_level_over_the_non_control_arms(
    raw_spec,
) -> None:
    three = cohort_report(_fading(raw_spec), None)["settings"]
    two = cohort_report(_context(raw_spec, {"variant_b": _weeks(FADE)}), None)["settings"]

    assert (three["non_control_arms"], three["level_per_statistic"]) == (2, 0.0125)
    assert (two["non_control_arms"], two["level_per_statistic"]) == (1, 0.025)
    assert three["trigger_level"] == two["trigger_level"] == 0.025


def test_a_test_that_could_not_run_is_reported_with_its_reason_and_the_cohort_sizes(
    raw_spec,
) -> None:
    context = _too_short(raw_spec)

    finding = RES_007.evaluate(context)

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert (entry["status"], entry["reason"]) == (
        "not_evaluated",
        "window_holds_fewer_than_3_blocks",
    )
    plan = finding.evidence["plans"]["variant_b"]
    assert plan["reason"] == "window_holds_fewer_than_3_blocks" and plan["usable"] == []
    assert plan["attempts"][0]["sizes"][0] == {"block": 0, "arm": 80, "control": 80}
    assert finding.evidence["summary"]["line"] == (
        "RES-007: 1 test, 0 flagged, 1 not evaluated, 0 low information"
    )
    assert (
        "arm variant_b, metric sessions_7d: not evaluated (window_holds_fewer_than_3_blocks)."
        in (finding.evidence["notes"])
    )
    assert finding.evidence["summary"]["evaluated"] == 0
    assert not any("flags" in note and "chance" in note for note in finding.evidence["notes"])


def test_units_that_are_not_independent_stop_every_test(raw_spec) -> None:
    finding = RES_007.evaluate(_units(raw_spec))

    assert finding is not None
    assert {(t["status"], t["reason"]) for t in finding.evidence["tests"]} == {
        ("not_evaluated", "unit_not_independent")
    }
    assert all("scales" not in t for t in finding.evidence["tests"])


def test_a_metric_with_no_variation_in_any_cohort_is_not_evaluated_on_either_scale(
    raw_spec,
) -> None:
    finding = RES_007.evaluate(_guardrail_without_variation(raw_spec))

    assert finding is not None
    purchased = _by_arm(finding.evidence, "purchased_7d")["variant_b"]
    assert (purchased["status"], purchased["reason"]) == ("not_evaluated", "no_variation")
    assert purchased["scales_not_evaluated"] == ["absolute", "log_ratio"]
    assert _by_arm(finding.evidence, "sessions_7d")["variant_b"]["status"] == "flagged"
    assert (
        "arm variant_b, metric purchased_7d: not evaluated on the absolute and log_ratio scale"
        " (no_variation)." in finding.evidence["notes"]
    )


def test_a_scale_that_cannot_be_evaluated_stops_the_test_and_is_named(raw_spec) -> None:
    finding = RES_007.evaluate(_missing_scale(raw_spec))

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert (entry["status"], entry["reason"]) == ("not_evaluated", "non_positive_mean")
    assert entry["scales_not_evaluated"] == ["log_ratio"]
    assert entry["scales"]["log_ratio"]["dropped"] == [
        {"block": b, "reason": "non_positive_mean"} for b in range(4)
    ]
    assert entry["scales"]["log_ratio"]["reason"] == "non_positive_mean"
    assert entry["scales"]["absolute"]["dropped"] == []
    assert entry["scales"]["absolute"]["reason"] is None
    assert entry["scales"]["absolute"]["q"] is not None
    assert entry["scales"]["log_ratio"]["q"] is None
    assert "on the log_ratio scale (non_positive_mean)" in " ".join(finding.evidence["notes"])


# --- What a finding says -------------------------------------------------------------------


def test_every_finding_says_what_the_test_cannot_tell_apart(raw_spec) -> None:
    notes = cohort_report(_fading(raw_spec), None)["notes"]

    assert notes[0].startswith("The test says that the effect differs between cohorts")
    assert "cannot be told from one tied to each player's own time since first exposure" in notes[0]
    assert "seven-day totals only" in notes[0]


def test_a_quiet_result_says_what_it_could_have_seen_in_units_and_as_a_share_of_the_control_mean(
    raw_spec,
) -> None:
    context = _fading(raw_spec)
    report = cohort_report(context, None)
    quiet = _by_arm(report)["variant_c"]
    plan = plan_cohorts(context, "variant_c")
    expected = detectable_shifts(
        cohort_test(context, plan, context.metrics["sessions_7d"]).absolute, 0.0125
    )

    found = quiet["detectable"]
    assert found["power"] == 0.8 and found["control_mean"] == pytest.approx(10.0)
    for shape in ("linear_fade", "step"):
        shift = found["absolute"][shape]["shift"]
        assert shift == pytest.approx(expected[shape], abs=1e-6) and shift > 0
        assert found["absolute"][shape]["share_of_control_mean"] == pytest.approx(
            shift / 10.0, abs=1e-6
        )
    note = next(n for n in report["notes"] if n.startswith("arm variant_c, metric sessions_7d"))
    fade = found["absolute"]["linear_fade"]
    assert (
        f"a linear fade (a difference between the arm and control of {fade['shift']:.3g} (" in note
    )
    assert f"({100 * fade['share_of_control_mean']:.0f}% of the control mean)" in note
    step = found["absolute"]["step"]
    assert f"or a step (a difference of {step['shift']:.3g} (" in note
    assert f"({100 * step['share_of_control_mean']:.0f}% of the control mean)" in note
    assert "low information" not in note and found["log_ratio"] == pytest.approx(
        {
            shape: value
            for shape, value in detectable_shifts(
                cohort_test(context, plan, context.metrics["sessions_7d"]).log_ratio, 0.0125
            ).items()
        },
        abs=1e-6,
    )
    assert "The usual power calculation puts at 80% the chance that the test would have" in note
    assert "the test could have missed anything smaller" in note
    assert "a little optimistic" not in note
    assert "The step was not simulated" in note
    assert "does not show that the effect is the same in every cohort" in note


def test_the_control_mean_of_a_flagged_arm_is_the_controls_and_not_the_arms(raw_spec) -> None:
    flagged = _by_arm(cohort_report(_fading(raw_spec), None))["variant_b"]

    assert flagged["status"] == "flagged"
    assert flagged["detectable"]["control_mean"] == pytest.approx(10.0)
    shift = flagged["detectable"]["absolute"]["linear_fade"]
    assert shift["share_of_control_mean"] == pytest.approx(shift["shift"] / 10.0, abs=1e-6)
    assert flagged["detectable"]["log_ratio"]["linear_fade"] > 0


def test_a_flagged_result_does_not_state_what_it_could_have_missed(raw_spec) -> None:
    notes = cohort_report(_fading(raw_spec), None)["notes"]

    flagged = next(n for n in notes if n.startswith("arm variant_b, metric sessions_7d"))

    assert flagged == (
        "arm variant_b, metric sessions_7d: the effect differs between cohorts of first exposure."
    )


def test_a_flagged_result_with_low_information_is_called_a_lead_to_re_check(raw_spec) -> None:
    context = _low_information(raw_spec)

    finding = RES_007.evaluate(context)

    assert finding is not None
    (entry,) = finding.evidence["tests"]
    assert entry["status"] == "flagged"
    assert entry["low_information"] == ["shift_exceeds_4_times_registered_mde"]
    assert finding.evidence["summary"]["low_information"] == 1
    assert finding.evidence["summary"]["line"].endswith(
        "1 flagged, 0 not evaluated, 1 low information"
    )
    assert (
        "arm variant_b, metric sessions_7d: the effect differs between cohorts of first exposure."
        " The test has low information here (shift_exceeds_4_times_registered_mde): treat the flag"
        " as a lead to re-check, not as a finding."
    ) in finding.evidence["notes"]


def test_without_a_registered_effect_that_small_the_same_flag_has_no_such_label(raw_spec) -> None:
    control = _weeks([20] * 5, unit=4)
    variant = _weeks([28, 24, 22, 21, 20], unit=4)
    context = _context(raw_spec, {"variant_b": variant}, control=control)

    report = cohort_report(context, None)

    (entry,) = report["tests"]
    assert entry["status"] == "flagged" and entry["low_information"] == []
    assert not any("lead to re-check" in note for note in report["notes"])


def test_the_catalogue_names_every_reason_the_test_can_give_for_not_running() -> None:
    codes = [*get_args(NotEvaluated), *get_args(GateReason), *get_args(DropReason)]

    assert len(codes) == 11
    assert [code for code in codes if code not in RES_007.fires_when] == []


def test_one_scale_alone_does_not_flag_and_the_note_says_so_and_why(raw_spec) -> None:
    context = _baseline_moves(raw_spec)

    report = cohort_report(context, None)

    (entry,) = report["tests"]
    assert entry["trigger"] == {"level": 0.025, "absolute": True, "log_ratio": False}
    assert entry["status"] == "not_flagged"
    note = next(
        n for n in report["notes"] if n.startswith("arm variant_b, metric sessions_7d: not")
    )
    assert (
        " The absolute scale alone shows a difference between cohorts; an arm is flagged only when"
        " both do, because a baseline that moves can make either scale show one."
    ) in note


def test_the_one_scale_clause_blames_a_moving_baseline_only_where_it_moves(raw_spec) -> None:
    (entry,) = cohort_report(_baseline_moves(raw_spec), None)["tests"]
    still = {**entry, "control_baseline": {**entry["control_baseline"], "moves": False}}

    note = _entry_note(still)

    assert "an arm is flagged only when both do, and one scale alone is not enough" in note
    assert "baseline that moves" not in note
    assert "because a baseline that moves" in _entry_note(entry)


def test_the_changing_baseline_sentence_appears_only_when_the_control_mean_moves(raw_spec) -> None:
    moving = cohort_report(_baseline_moves(raw_spec), None)
    flat = cohort_report(_fading(raw_spec), None)

    (entry,) = moving["tests"]
    assert entry["control_baseline"]["moves"] is True
    assert entry["control_baseline"]["homogeneity_p"] < 0.05
    assert [c["mean"] for c in entry["control_baseline"]["cohorts"]] == pytest.approx(
        [10, 20, 30, 40, 50], abs=0.1
    )
    assert any(
        "A control baseline that changes can raise Cochran's Q" in n for n in moving["notes"]
    )
    assert any(
        "the control's mean differs between the cohorts compared (p = " in n
        for n in moving["notes"]
    )
    assert all(t["control_baseline"]["moves"] is False for t in flat["tests"])
    assert not any("A control baseline that changes" in n for n in flat["notes"])
    assert not any("the control's mean differs" in n for n in flat["notes"])


# --- The declarations and the circumstances ------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (None, "population.kind is not declared, so the kind of players is unknown."),
        ("new_users", "population.kind is declared as new_users. Referee cannot check this"),
        ("mixed", "population.kind is declared as mixed. Referee cannot check this"),
        ("existing_users", "players who see a change first can be the most active"),
    ],
)
def test_the_population_kind_is_reported_as_declared_and_unchecked(
    raw_spec, kind, expected
) -> None:
    more = {} if kind is None else {"population__kind": kind}
    notes = cohort_report(_fading(raw_spec, **more), None)["notes"]

    assert expected in notes[1]
    if kind is not None:
        assert "the export has no column for how long a player has existed" in notes[1]


def test_only_existing_users_are_told_that_early_exposed_players_can_be_the_most_active(
    raw_spec,
) -> None:
    for kind in (None, "new_users", "mixed"):
        more = {} if kind is None else {"population__kind": kind}
        assert "most active" not in " ".join(
            cohort_report(_fading(raw_spec, **more), None)["notes"]
        )


def test_the_interim_note_appears_only_when_the_assignments_stop_before_the_planned_end(
    raw_spec,
) -> None:
    interim = cohort_report(SCENARIOS["interim"](raw_spec), None)
    complete = cohort_report(_fading(raw_spec), None)

    assert interim["settings"]["interim"] is True
    assert (interim["settings"]["observed_days"], interim["settings"]["planned_duration_days"]) == (
        28,
        56,
    )
    assert any(
        n.startswith("The assignments span 28 days of the 56 planned") for n in interim["notes"]
    )
    assert "11% to 13% of experiments with no change" in " ".join(interim["notes"])
    assert complete["settings"]["interim"] is False
    assert complete["settings"]["observed_days"] == 35
    assert not any("interim" in n for n in complete["notes"])


def test_a_test_that_did_not_run_does_not_say_that_completeness_was_unchecked(raw_spec) -> None:
    notes = cohort_report(_units(raw_spec), None)["notes"]

    assert not any(n.startswith("No as-of time") for n in notes)


def test_the_export_time_decides_whether_unfinished_outcome_windows_were_looked_for(
    raw_spec,
) -> None:
    unknown = cohort_report(_fading(raw_spec), None)
    known = cohort_report(_fading(raw_spec, exported_at=at(60)), None)
    early = cohort_report(_fading(raw_spec, exported_at=at(33)), None)

    no_time = (
        "No as-of time was known, so cohorts whose outcome windows had not closed were not "
        "looked for."
    )
    assert (
        no_time in unknown["notes"]
        and unknown["plans"]["variant_b"]["completeness_checked"] is False
    )
    assert (
        no_time not in known["notes"]
        and known["plans"]["variant_b"]["completeness_checked"] is True
    )
    assert known["plans"]["variant_b"]["as_of"] == at(60).isoformat()
    # An export on day 33 cannot hold week 4's outcomes: those cohorts are left out and listed.
    plan = early["plans"]["variant_b"]
    assert plan["attempts"][0]["incomplete"] == [4] and plan["usable"] == [0, 1, 2, 3]
    assert [c["block"] for c in _by_arm(early)["variant_b"]["scales"]["absolute"]["cohorts"]] == [
        0,
        1,
        2,
        3,
    ]


def test_a_change_of_configuration_is_said_to_fall_in_the_same_weeks_as_the_cohorts(
    raw_spec,
) -> None:
    context = SCENARIOS["configuration_change"](raw_spec)
    configuration = _config_of(context)

    with_it = cohort_report(context, configuration)["notes"]
    without_it = cohort_report(context, None)["notes"]
    clean = cohort_report(_fading(raw_spec), _config_of(_fading(raw_spec)))["notes"]

    assert configuration["arms"]["variant_b"]["mixed_weeks"] == [2]
    assert (
        "RES-013: the configuration of arm variant_b changed during the test (weeks of first"
        " exposure holding more than one version: 2). The version change falls in the same weeks"
        " as the cohorts compared, so a difference between cohorts may be the change itself."
    ) in with_it
    assert not any("RES-013" in note for note in without_it + clean)


# --- Chance, and the counts ----------------------------------------------------------------


def test_the_flags_chance_alone_would_give_are_the_measured_rates_times_the_tests_that_ran(
    raw_spec,
) -> None:
    report = cohort_report(_fading(raw_spec, guardrails=[GUARDRAIL]), None)

    summary = report["summary"]
    assert (summary["tests"], summary["evaluated"], summary["not_evaluated"]) == (4, 2, 2)
    assert summary["flags_by_chance"] == pytest.approx(2 * NULL_FLAG_RATE_MEAN)
    assert summary["flags_by_chance_at_most"] == pytest.approx(2 * NULL_FLAG_RATE_MAX)
    assert (
        "2 tests ran. In the simulations of design section 21.5 (two arms of equal size, no change"
        " over time) the trigger flagged 3.5% of tests on average and at most 5.1%, so about 0.069"
        " flags (at most"
        " 0.1) would be expected by chance alone."
    ) in report["notes"]


def test_the_chance_sentence_uses_the_singular_for_one_test(raw_spec) -> None:
    notes = cohort_report(_context(raw_spec, {"variant_b": _weeks(FADE)}), None)["notes"]

    assert any(note.startswith("1 test ran. ") for note in notes)


def test_the_summary_counts_the_entries_by_status_and_prints_the_report_line() -> None:
    entries = [
        {
            "status": "flagged",
            "low_information": ["shift_exceeds_control_mean", "fewer_than_5_expected_events"],
        },
        {"status": "flagged", "low_information": []},
        {"status": "not_flagged", "low_information": ["fewer_than_5_expected_events"]},
        {"status": "not_flagged", "low_information": []},
        {"status": "not_evaluated", "reason": "allocation_too_unequal"},
    ]

    summary = summarise(entries)

    assert summary["line"] == "RES-007: 5 tests, 2 flagged, 1 not evaluated, 2 low information"
    assert (summary["tests"], summary["evaluated"], summary["flagged"]) == (5, 4, 2)
    assert (
        summarise([])["line"] == "RES-007: 0 tests, 0 flagged, 0 not evaluated, 0 low information"
    )
    assert summarise(entries[:1])["line"].startswith("RES-007: 1 test, ")


def test_the_assignments_span_is_counted_in_whole_days_rounded_up(raw_spec) -> None:
    exact = _context(raw_spec, {"variant_b": _weeks(FADE)}, stretch=False)
    partial = _context(raw_spec, {"variant_b": _weeks(FADE)})
    span = max(p.assigned_at for p in partial.players) - min(p.assigned_at for p in partial.players)

    assert exact.observed_days == 28
    assert span == timedelta(days=34, hours=23) and partial.observed_days == 35


def test_the_log_ratio_scale_alone_is_named_when_only_it_shows_a_difference(raw_spec) -> None:
    report = cohort_report(_absolute_effect_constant(raw_spec), None)

    (entry,) = report["tests"]
    assert entry["trigger"] == {"level": 0.025, "absolute": False, "log_ratio": True}
    assert entry["status"] == "not_flagged"
    assert " The log-ratio scale alone shows a difference between cohorts;" in " ".join(
        report["notes"]
    )
    assert " The absolute scale alone" not in " ".join(report["notes"])


def test_a_quiet_result_with_both_scales_agreeing_names_neither_scale(raw_spec) -> None:
    notes = " ".join(cohort_report(_quiet(raw_spec), None)["notes"])

    assert "scale alone shows" not in notes


def test_arms_of_different_sizes_raise_the_floor_and_the_sizes_are_each_the_arms_own(
    raw_spec,
) -> None:
    report = cohort_report(_unequal_arms(raw_spec), None)

    plan = report["plans"]["variant_b"]
    assert (plan["allocation_ratio"], plan["floor"]) == (2.0, 43)
    attempt = plan["attempts"][0]
    assert attempt["sizes"][0] == {"block": 0, "arm": 160, "control": 80}
    assert attempt["minimum_arm"]["used"] == attempt["minimum_control"]["used"] == 43
    (entry,) = report["tests"]
    cohort = entry["scales"]["absolute"]["cohorts"][0]
    assert (cohort["n_arm"], cohort["n_control"]) == (160, 80)


def test_a_version_change_at_a_week_boundary_is_reported_with_no_mixed_weeks(raw_spec) -> None:
    context = _configuration_boundary(raw_spec)

    notes = cohort_report(context, _config_of(context))["notes"]

    assert _config_of(context)["arms"]["variant_b"]["mixed_weeks"] == []
    assert (
        "RES-013: the configuration of arm variant_b changed during the test (weeks of first"
        " exposure holding more than one version: none). The version change falls in the same"
        " weeks as the cohorts compared, so a difference between cohorts may be the change itself."
    ) in notes


def _hotfix(raw_spec, arm, **more):
    """The fade, with `arm` moving to version 2 half way through week 4, the last week."""
    flat, fade = _weeks(FLAT), _weeks(FADE)
    weeks = {"control": flat, "variant_b": fade}
    rows = []
    for name, per_week in weeks.items():
        if name != arm:
            rows += cohort_rows(name, per_week)
            continue
        rows += cohort_rows(name, {**per_week, 4: per_week[4][:40]}, tag="a")
        rows += cohort_rows(name, {4: per_week[4][40:]}, tag="b", version_of=lambda block: 2)
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(34, 23), at(34, 23.5)
    return cohort_context(raw_spec, rows, days=35, arms=TWO_ARMS, **more)


def _head(arm, weeks):
    return (
        f"RES-013: the configuration of arm {arm} changed during the test (weeks of first"
        f" exposure holding more than one version: {weeks}). "
    )


INSIDE = (
    "The version change falls in the same weeks as the cohorts compared, so a difference"
    " between cohorts may be the change itself."
)
OUTSIDE = (
    "In each test the cohorts compared first saw a single version of it, so the version"
    " change falls outside them."
)


@pytest.mark.parametrize("arm", ["variant_b", "control"])
def test_a_version_change_is_said_to_fall_among_the_cohorts_only_if_they_were_compared(
    raw_spec, arm
) -> None:
    left_out = _hotfix(raw_spec, arm, exported_at=at(33))
    counted = _hotfix(raw_spec, arm, exported_at=at(60))

    notes = {
        name: cohort_report(context, _config_of(context))
        for name, context in (("left_out", left_out), ("counted", counted))
    }

    assert notes["left_out"]["plans"]["variant_b"]["usable"] == [0, 1, 2, 3]
    assert notes["counted"]["plans"]["variant_b"]["usable"] == [0, 1, 2, 3, 4]
    assert _head(arm, 4) + OUTSIDE in notes["left_out"]["notes"]
    assert _head(arm, 4) + INSIDE in notes["counted"]["notes"]


def test_a_version_change_in_an_arm_whose_test_did_not_run_has_no_cohorts_to_fall_among(
    raw_spec,
) -> None:
    short = cohort_rows("control", _weeks(FLAT[:2]))
    short += cohort_rows("variant_b", _weeks(FADE[:2]), version_of=lambda block: 1 + block)
    # variant_b has no sessions before week 4, so its log ratio is missing; variant_c is tested
    variant = {**{block: [0] * 80 for block in range(4)}, 4: spread(10)}
    three = cohort_rows("control", _weeks(FLAT)) + cohort_rows("variant_c", _weeks(FLAT))
    three += cohort_rows("variant_b", variant, version_of=lambda block: 1 + (block >= 4))
    contexts = {
        "plan": cohort_context(raw_spec, short, days=14, arms=TWO_ARMS),
        "scale": cohort_context(raw_spec, three, days=35, arms=THREE_ARMS),
    }

    said = {
        "plan": "The cohort test did not run for it, so no cohorts were compared.",
        # the absolute scale did compare cohorts, and they hold both versions
        "scale": INSIDE,
    }
    for name, context in contexts.items():
        report = cohort_report(context, _config_of(context))

        assert _by_arm(report)["variant_b"]["status"] == "not_evaluated"
        assert _head("variant_b", "none") + said[name] in report["notes"]
    assert _by_arm(cohort_report(contexts["scale"], None))["variant_c"]["status"] != (
        "not_evaluated"
    )


def test_a_change_of_the_control_falls_among_the_cohorts_if_any_test_compared_them(
    raw_spec,
) -> None:
    flat = _weeks(FLAT)
    rows = cohort_rows("control", {**flat, 4: flat[4][:40]}, tag="a")
    rows += cohort_rows("control", {4: flat[4][40:]}, tag="b", version_of=lambda block: 2)
    rows += cohort_rows("variant_b", _weeks(FADE))
    rows += cohort_rows("variant_c", {**flat, 4: spread(10, n=5)})
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(34, 23), at(34, 23.5)
    context = cohort_context(raw_spec, rows, days=35, arms=THREE_ARMS)

    report = cohort_report(context, _config_of(context))

    # week 4 is too small for variant_c's test and large enough for variant_b's
    assert report["plans"]["variant_b"]["usable"] == [0, 1, 2, 3, 4]
    assert report["plans"]["variant_c"]["usable"] == [0, 1, 2, 3]
    assert _head("control", 4) + INSIDE in report["notes"]


@pytest.mark.parametrize("first_week_of_version_2", [6, 7])  # the first or second week of block 3
def test_a_block_of_two_weeks_is_judged_on_both_of_its_weeks(
    raw_spec, first_week_of_version_2: int
) -> None:
    rows = []
    for arm in ("control", "variant_b"):
        for week in range(8):
            version = 2 if arm == "variant_b" and week >= first_week_of_version_2 else 1
            rows += [
                Row(
                    f"{arm}_{week}_{i}",
                    arm,
                    assigned_at=at(7 * week),
                    exposed_at=at(7 * week, 1),
                    assigned_version=version,
                    exposure_version=version,
                    sessions=8 + i % 5,
                )
                for i in range(20)
            ]
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(55, 23), at(55, 23.5)
    context = cohort_context(raw_spec, rows, days=56, arms=TWO_ARMS)

    report = cohort_report(context, _config_of(context))

    assert report["plans"]["variant_b"]["block_days"] == 14
    assert _head("variant_b", "none") + INSIDE in report["notes"]


def test_the_rule_gives_the_report_the_evidence_of_res_013(raw_spec) -> None:
    finding = RES_007.evaluate(_configuration_change(raw_spec))

    assert finding is not None
    assert any(
        n.startswith("RES-013: the configuration of arm variant_b")
        for n in finding.evidence["notes"]
    )
    assert not any(
        n.startswith("RES-013") for n in RES_007.evaluate(_fading(raw_spec)).evidence["notes"]
    )


def test_a_share_of_a_control_mean_that_is_not_positive_is_left_out_and_not_divided() -> None:
    assert _share(0.5, 0.0) is None and _share(0.5, -1.0) is None
    assert _share(0.5, 2.0) == 0.25
    assert _amount({"shift": 1.5, "share_of_control_mean": None}) == "1.5"
    assert _amount({"shift": 1.5, "share_of_control_mean": 0.25}) == "1.5 (25% of the control mean)"


def _with_one_value(raw_spec, value: int) -> ResultsContext:
    """Five quiet weeks whose fourth control cohort holds one player with `value` sessions."""
    control = _weeks(FLAT)
    control[3] = [value, *control[3][1:]]
    return _context(raw_spec, {"variant_b": _weeks(FLAT)}, control=control)


@pytest.mark.parametrize(
    "value",
    [10**12, 2**63 - 1, 10**100, 10**155],  # the last is too large to square: its cohort is dropped
    ids=["1e12", "int64_max", "1e100", "1e155"],
)
def test_one_absurd_value_does_not_stop_the_test(raw_spec, value: int) -> None:
    (entry,) = cohort_report(_with_one_value(raw_spec, value), None)["tests"]

    assert entry["status"] == "not_flagged"
    assert 0 < entry["detectable"]["absolute"]["linear_fade"]["shift"] < 10


def test_a_failure_of_the_shifts_is_reported_with_its_message(raw_spec, monkeypatch) -> None:
    def fail(scale, level):
        raise StatsError("no change this size could be seen")

    monkeypatch.setattr("referee.rules.cohorts.detectable_shifts", fail)

    report = cohort_report(_context(raw_spec, {"variant_b": _weeks(FADE)}), None)

    (entry,) = report["tests"]
    assert (entry["status"], entry["reason"], entry["error"]) == (
        "not_evaluated",
        "not_estimable",
        "no change this size could be seen",
    )
    assert (
        "arm variant_b, metric sessions_7d: not evaluated (not_estimable: no change this size "
        "could be seen)."
    ) in report["notes"]


def test_a_failure_of_q_is_carried_into_the_evidence() -> None:
    failed = ScaleTest(
        scale="absolute",
        cohorts=(),
        dropped=(),
        reason="not_estimable",
        error="the variances are too large",
        heterogeneity=None,
    )

    shown = _scale(failed)

    assert (shown["reason"], shown["error"]) == ("not_estimable", "the variances are too large")
    assert shown["q"] is None and shown["slope"] is None and shown["cohorts"] == []


def _arms_minimum(context: ResultsContext, arm: str, days: int) -> dict:
    """What the plan should say about an arm's minimum: the preferred one is ceil(7R / 4D)."""
    registered = context.required_n(arm)
    preferred = -(-7 * registered // (4 * days))
    return {"registered": registered, "preferred": preferred}


def test_the_preferred_minimum_is_not_used_when_fewer_than_nine_in_ten_cohorts_reach_it(
    raw_spec,
) -> None:
    """A registered n of about 1,700 asks for 84 players a cohort; the cohorts hold 80."""
    context = _fading(raw_spec, design__mde_relative=0.05)

    attempt = cohort_report(context, None)["plans"]["variant_b"]["attempts"][0]

    for who, name in (("minimum_arm", "variant_b"), ("minimum_control", "control")):
        wanted = _arms_minimum(context, name, 35)
        assert attempt[who] == {**wanted, "achieved": 400, "used": 30}
    assert (
        attempt["minimum_arm"]["preferred"] == 84 and attempt["minimum_control"]["preferred"] == 111
    )
    assert attempt["minimum_arm"]["registered"] != attempt["minimum_control"]["registered"]
    assert attempt["preferred_used"] is False
    assert attempt["usable"] == attempt["usable_at_floor"] == [0, 1, 2, 3, 4]


def test_the_preferred_minimum_is_used_when_nine_in_ten_cohorts_reach_it(raw_spec) -> None:
    """Ten weeks, one of them with 35 players where 40 are preferred: that week is left out."""
    arm, control = _weeks([10] * 10), _weeks([10] * 10)
    arm[4], control[4] = arm[4][:35], control[4][:35]
    context = _context(
        raw_spec, {"variant_b": arm}, control=control, days=70, design__mde_relative=0.05
    )

    attempt = cohort_report(context, None)["plans"]["variant_b"]["attempts"][0]

    minimum = {**_arms_minimum(context, "variant_b", 70), "achieved": 755, "used": 40}
    assert attempt["minimum_arm"] == attempt["minimum_control"] == minimum
    assert minimum["preferred"] == 40
    assert attempt["preferred_used"] is True
    assert attempt["usable"] == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    assert attempt["usable_at_floor"] == list(range(10))


def test_cohorts_that_do_not_cover_the_window_are_reported_for_each_block_length_tried(
    raw_spec,
) -> None:
    """Three weeks of players in a 56-day plan: all in its first half."""
    context = _context(
        raw_spec,
        {"variant_b": _weeks([10] * 3)},
        control=_weeks([10] * 3),
        days=56,
        stretch=False,
    )

    report = cohort_report(context, None)

    plan = report["plans"]["variant_b"]
    assert plan["reason"] == "cohorts_do_not_cover_the_window"
    weekly, fortnightly = plan["attempts"]
    assert (weekly["block_days"], weekly["covers_window"], weekly["usable"]) == (
        7,
        False,
        [0, 1, 2],
    )
    assert weekly["reason"] == "cohorts_do_not_cover_the_window"
    assert (fortnightly["block_days"], fortnightly["covers_window"]) == (14, False)
    assert fortnightly["reason"] == "fewer_than_3_cohorts_reach_minimum"
    (entry,) = report["tests"]
    assert entry["reason"] == "cohorts_do_not_cover_the_window"


def test_a_registered_effect_smaller_than_the_test_can_see_labels_even_a_quiet_result(
    raw_spec,
) -> None:
    """Four times the registered effect is 0.85: a fade of 0.948 exceeds it, a step of 0.747 not."""
    context = _fading(raw_spec, design__mde_relative=0.02125)

    report = cohort_report(context, None)

    quiet = _by_arm(report)["variant_c"]
    assert quiet["status"] == "not_flagged"
    assert quiet["detectable"]["absolute"]["linear_fade"]["shift"] == pytest.approx(
        0.948184, abs=1e-6
    )
    assert quiet["detectable"]["absolute"]["step"]["shift"] == pytest.approx(0.747011, abs=1e-6)
    assert quiet["low_information"] == ["shift_exceeds_4_times_registered_mde"]
    note = next(n for n in report["notes"] if n.startswith("arm variant_c, metric sessions_7d"))
    assert note.endswith(
        " The test has low information here (shift_exceeds_4_times_registered_mde)."
    )
    assert report["summary"]["low_information"] == 2


def test_expected_events_are_counted_for_a_binary_metric_and_not_for_a_continuous_one(
    raw_spec,
) -> None:
    """Two sessions and three purchases in 80 players: a few events either way."""
    few = {b: [1, 1] + [0] * 78 for b in range(5)}
    rows = cohort_rows("control", few) + cohort_rows("variant_b", few)
    for i, row in enumerate(rows):
        if i % 80 < 3:
            row.purchases = 1
            row.first_purchase_at = row.exposed_at + timedelta(hours=1)
    last = max(i for i, row in enumerate(rows) if row.arm == "control")
    rows[last].assigned_at, rows[last].exposed_at = at(34, 23), at(34, 23.5)
    context = cohort_context(raw_spec, rows, days=35, arms=TWO_ARMS, guardrails=[GUARDRAIL])

    report = cohort_report(context, None)

    sessions = _by_arm(report, "sessions_7d")["variant_b"]
    purchased = _by_arm(report, "purchased_7d")["variant_b"]
    assert sessions["low_information"] == ["shift_exceeds_control_mean"]
    assert purchased["low_information"] == [
        "shift_exceeds_control_mean",
        "fewer_than_5_expected_events",
    ]
    assert (sessions["detectable"]["control_mean"], purchased["detectable"]["control_mean"]) == (
        0.025,
        0.0375,
    )
    assert sessions["detectable"]["absolute"]["linear_fade"]["share_of_control_mean"] > 1


# --- The traffic a test that could not run would need ----------------------------------------

CAVEATS = (
    "About the traffic figures: they assume that the extra players arrive in the same weeks and in"
    " the same proportions between the arms, and are exposed at the same rate, so arrivals that"
    " come in spikes may not repeat; and they concern the sizes of the cohorts only, so a scale"
    " can still drop a cohort it cannot estimate (no variation, or a mean that is not positive)."
    " They do not price a longer run, or growing one arm only, which can cost less."
)
NUMBERING = (
    "Cohort numbers count blocks of 7 or 14 days from 0, starting at design.start_utc, or at the"
    " first assignment when the spec registers none."
)
INTERIM_TRAFFIC = (
    "This is an interim look: the weeks the assignments do not reach count as empty in the"
    " traffic figures, which describe the data so far and not a finished run, so a figure can"
    " fall as they fill."
)
EMPTY_INTERIM = (
    "The assignments cover only part of the planned window, so some weeks of it are empty here"
    " and more of the same traffic could not fill them. If the run is still going, run to the"
    " planned end and look again; if it stopped, check whether assignment or exposure stopped"
    " early."
)
PREFERRED = (
    " The preferred minimum is a quarter of the registered share of a block; it is used only"
    " while it keeps at least 90% of the cohorts that reach the floor."
)


def _left_out(when: str, cohorts: str) -> str:
    return (
        f"Cohorts were left out because their outcome windows had not closed by {when}: {cohorts}. "
    )


def _price(factor: str, unit: str, sets: str) -> str:
    return (
        f"{factor} times the traffic observed (every cohort of both arms scaled together) would"
        f" meet the size rules for the cohorts, with {unit} cohorts at that multiple, and keep"
        " meeting them at any larger multiple. At that multiple these sizes reach what is wanted"
        f" (the counts are as observed): {sets}."
    )


def _notes_of(raw_spec, name: str) -> list[str]:
    return cohort_report(TRAFFIC_SCENARIOS[name](raw_spec), None)["notes"]


def _arm_note(raw_spec, name: str, arm: str = "variant_b") -> str:
    (note,) = (
        n for n in _notes_of(raw_spec, name) if n.startswith(f"arm {arm}:") and ", metric " not in n
    )
    return note


def _shared(raw_spec, name: str) -> list[str]:
    """The notes about traffic that are not about one arm, in the order they are printed."""
    shared = (NUMBERING, INTERIM_TRAFFIC, CAVEATS)
    return [n for n in _notes_of(raw_spec, name) if n in shared]


def test_the_finding_prices_the_traffic_a_test_that_could_not_run_would_need(raw_spec) -> None:
    """Flat weeks of 20: the floor wants 1.5 times, the weekly median of 60 wants 3 times."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_median"](raw_spec), None)

    binding = {
        "kind": "weekly_median",
        "block_days": 7,
        "block": None,
        "side": "smaller_arm",
        "have": 20,
        "need": 60,
    }
    assert report["plans"]["variant_b"]["traffic_needed"] == {
        "windows_close_at": None,
        "now": {"factor": 3.0, "block_days": 7, "binding": [binding], "first_pass": None},
        "after_windows_close": None,
        "waiting_suffices": False,
        "blocker": None,
        "attempts": [
            {
                "block_days": 7,
                "reason": "fewer_than_3_cohorts_reach_minimum",
                "left_out": [],
                "now": 3.0,
                "after_windows_close": None,
            }
        ],
    }
    assert _arm_note(raw_spec, "traffic_median") == (
        "arm variant_b: 3 times the traffic observed (every cohort of both arms scaled together)"
        " would meet the size rules for the cohorts, with weekly cohorts at that multiple, and"
        " keep meeting them at any larger multiple. At that multiple these sizes reach what is"
        " wanted (the counts are as observed): the median over the weeks of the smaller arm's"
        " size is 20 players and 60 are wanted for weekly cohorts."
    )


def test_the_shared_notes_follow_the_arm_notes_and_the_interim_one_only_on_an_interim_look(
    raw_spec,
) -> None:
    """The weeks run to day 28 of a 35-day plan: an interim look. Stretched to the last day it is
    not, and the notes do not say so. The numbering note appears only if a cohort number does."""
    assert _shared(raw_spec, "traffic_median") == [INTERIM_TRAFFIC, CAVEATS]
    assert _shared(raw_spec, "traffic_median_complete") == [CAVEATS]
    assert _shared(raw_spec, "traffic_spiky") == [NUMBERING, INTERIM_TRAFFIC, CAVEATS]
    notes = _notes_of(raw_spec, "traffic_spiky")
    assert notes.index(NUMBERING) > notes.index(_arm_note(raw_spec, "traffic_spiky"))
    assert notes[-1] == CAVEATS


def test_the_numbering_note_is_printed_if_any_arm_names_a_cohort_and_not_only_the_last(
    raw_spec,
) -> None:
    """Variant b names weeks 3 and 4; variant c, 10 against 340, is more than 9 to 1 apart."""
    context = _sized(
        raw_spec,
        SPIKY,
        SPIKY,
        35,
        extra={"variant_c": _flat_sizes(2, 5)},
        arms=THREE_ARMS,
    )

    notes = cohort_report(context, None)["notes"]

    assert NUMBERING in notes and notes.count(NUMBERING) == 1


def test_a_plan_of_8_weeks_names_both_block_lengths_each_on_its_own(raw_spec) -> None:
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_fortnight"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert [(a["block_days"], a["now"]) for a in traffic["attempts"]] == [(7, 6.0), (14, 1.5)]
    assert (traffic["now"]["factor"], traffic["now"]["block_days"]) == (1.5, 14)
    assert {(b["block_days"], b["side"]) for b in traffic["now"]["binding"]} == {
        (14, "arm"),
        (14, "control"),
    }
    assert _arm_note(raw_spec, "traffic_fortnight") == (
        "arm variant_b: "
        + _price(
            "1.5",
            "14-day",
            "both arms have 20 players in 14-day cohorts 0, 1, 2 and 3, where 30 are wanted",
        )
        + " Each block length on its own: weekly cohorts, 6 times; 14-day cohorts, 1.5 times."
    )


def test_thin_weeks_are_named_and_so_is_a_raised_floor_with_the_arm_that_must_grow(
    raw_spec,
) -> None:
    assert _arm_note(raw_spec, "traffic_spiky") == "arm variant_b: " + _price(
        "3", "weekly", "both arms have 10 players in weekly cohorts 3 and 4, where 30 are wanted"
    )
    assert _arm_note(raw_spec, "traffic_raised_floor") == (
        "arm variant_b: "
        + _price(
            "4.9",
            "weekly",
            "control has 20 players in weekly cohorts 0, 1, 2, 3 and 4, where 98 are wanted",
        )
        + " The floor is 98 instead of 30 because the two arms differ about 4 to 1; a smaller gap"
        " between the arms lowers it."
    )


def test_the_ratio_of_the_arms_is_rounded_up_so_that_it_is_never_shown_at_or_below_the_knee(
    raw_spec,
) -> None:
    """The arms are 340 and 206 players: 1.6505 to 1, a floor of 34, shown as 1.66."""
    plan = cohort_report(TRAFFIC_SCENARIOS["traffic_floor_ratio"](raw_spec), None)["plans"]

    assert (plan["variant_b"]["floor"], plan["variant_b"]["allocation_ratio"]) == (34, 1.650485)
    assert _arm_note(raw_spec, "traffic_floor_ratio") == (
        "arm variant_b: "
        + _price(
            "2.62",
            "weekly",
            "control has 13 players in weekly cohorts 3 and 4, where 34 are wanted",
        )
        + " The floor is 34 instead of 30 because the two arms differ about 1.66 to 1; a smaller"
        " gap between the arms lowers it."
    )


def test_a_raised_floor_is_not_mentioned_when_it_is_not_what_sets_the_traffic(raw_spec) -> None:
    """Unequal arms 80 to 40 raise the floor to 43, but the weekly median of 60 sets 1.5 times."""
    context = _sized(raw_spec, _flat_sizes(80, 5), _flat_sizes(40, 5), 35)
    notes = cohort_report(context, None)["notes"]

    assert not any("The floor is" in n for n in notes)
    assert any(n.startswith("arm variant_b: 1.5 times the traffic") for n in notes)


def test_the_ratio_of_the_arms_in_the_price_is_rounded_up_without_the_error_of_a_float() -> None:
    """330 and 150 players are exactly 2.2 to 1, which is 220.00000000000003 hundredths."""
    _, plan = _island_for_text()
    floor = Binding(kind="floor", block_days=7, block=3, side="arm", have=20, need=60)

    text = _price_text(
        "a",
        replace(plan, allocation_ratio=330 / 150, floor=60),
        Price(factor=2.0, block_days=7, binding=(floor,)),
    )

    assert "because the two arms differ about 2.2 to 1;" in text


def test_the_preferred_minimum_is_explained_when_it_is_named_and_a_first_pass_is_said() -> None:
    """The plan passes at 1.08 times, fails above it, and keeps passing from 3.58."""
    attempt, plan = _island_for_text()
    traffic = traffic_needed(plan)

    text = _price_text("a", plan, traffic.now)

    assert (traffic.now.factor, traffic.now.first_pass) == (3.58, 1.08)
    assert text == (
        _price(
            "3.58",
            "weekly",
            "both arms have 28 players in weekly cohort 10, where the preferred minimum is 100",
        )
        + " The plan already passes at 1.08 times, but not at every larger multiple (the preferred"
        " minimum is judged again as the cohorts grow), so 3.58 is where it keeps passing."
        + PREFERRED
    )


@pytest.mark.parametrize(
    ("name", "blocker", "sentence"),
    [
        (
            "traffic_short",
            "plan_too_short",
            "More traffic would not help: the planned window holds fewer than 3 whole blocks. A"
            " plan of at least 21 days holds 3 weekly blocks.",
        ),
        (
            "traffic_unequal",
            "arms_too_unequal",
            "More traffic in the same proportions would not help: the two arms differ in size by"
            " more than 9 to 1, and the smaller arm would have to grow relative to the larger.",
        ),
        (
            "traffic_empty",
            "empty_cohorts",
            "More of the same traffic would not help: too few blocks of the window hold players of"
            " both arms (the test needs 3 usable cohorts, at least one in each half of the"
            " window, and for weekly blocks the median week must not be empty), and scaling what"
            " was observed cannot fill an empty one. Check whether assignment or exposure"
            " stopped or began late.",
        ),
        ("traffic_empty_interim", "empty_cohorts", EMPTY_INTERIM),
    ],
)
def test_when_more_traffic_is_not_the_remedy_the_finding_says_why(
    raw_spec, name, blocker, sentence
) -> None:
    report = cohort_report(TRAFFIC_SCENARIOS[name](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert (traffic["now"], traffic["after_windows_close"], traffic["blocker"]) == (
        None,
        None,
        blocker,
    )
    assert f"arm variant_b: {sentence}" in report["notes"]
    assert not _shared(raw_spec, name)


def test_when_waiting_is_the_remedy_the_finding_says_when_to_export_again(raw_spec) -> None:
    """Week 2 is left out of a 21-day plan; its windows close on day 21, 2026-05-02. Nothing
    helps as exported, and once it is counted the weekly cohorts meet the rules as they are."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_waiting"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert traffic["now"] is None and traffic["waiting_suffices"] is True
    assert traffic["windows_close_at"] == "2026-05-02T00:00:00+00:00"
    assert traffic["after_windows_close"] == {
        "factor": 1.0,
        "block_days": 7,
        "binding": [],
        "first_pass": None,
    }
    assert traffic["attempts"][0]["left_out"] == [2]
    assert _arm_note(raw_spec, "traffic_waiting") == (
        "arm variant_b: "
        + _left_out("2026-04-30 00:00 UTC", "weekly cohort 2")
        + "Export again after 2026-05-02 00:00 UTC, once they have closed: weekly cohorts would"
        " then meet the size rules at the traffic observed. As exported, no multiple of the"
        " traffic would do."
    )
    assert CAVEATS not in report["notes"] and NUMBERING in report["notes"]


def test_cohorts_left_out_are_not_called_empty_and_the_price_is_given_for_after_they_close(
    raw_spec,
) -> None:
    assert _arm_note(raw_spec, "traffic_after_waiting") == (
        "arm variant_b: "
        + _left_out("2026-05-08 00:00 UTC", "weekly cohorts 3 and 4")
        + "With those cohorts left out, no multiple of the traffic would do. Once they have"
        " closed (after 2026-05-16 00:00 UTC) and are counted, "
        + _price(
            "3",
            "weekly",
            "both arms have 10 players in weekly cohorts 3 and 4, where 30 are wanted",
        )
    )
    assert CAVEATS in _notes_of(raw_spec, "traffic_after_waiting")


def test_a_block_length_that_only_waits_is_not_priced_as_if_nothing_helped(raw_spec) -> None:
    """Six weeks of 40, exported on day 40: weekly blocks need 1.5 times for their median;
    14-day blocks need no traffic once week 5 is counted, and the finding says so first."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_mixed"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert traffic["waiting_suffices"] and traffic["now"]["factor"] == 1.5
    assert [
        (a["block_days"], a["reason"], a["left_out"], a["now"], a["after_windows_close"])
        for a in traffic["attempts"]
    ] == [
        (7, "cohorts_too_small_for_weekly_blocks", [5], 1.5, 1.5),
        (14, "outcome_window_incomplete", [2], None, 1.0),
    ]
    assert _arm_note(raw_spec, "traffic_mixed") == (
        "arm variant_b: "
        + _left_out("2026-05-21 00:00 UTC", "weekly cohort 5; 14-day cohort 2")
        + "Export again after 2026-05-23 00:00 UTC, once they have closed: 14-day cohorts would"
        " then meet the size rules at the traffic observed. Without waiting, "
        + _price(
            "1.5",
            "weekly",
            "the median over the weeks of the smaller arm's size is 40 players and 60 are wanted"
            " for weekly cohorts",
        )
        + " Each block length on its own: weekly cohorts, 1.5 times as exported and 1.5 times"
        " once the cohorts left out are counted; 14-day cohorts, no multiple would do as exported"
        " and no extra traffic once the cohorts left out are counted."
    )


def test_each_block_length_gives_both_its_prices_when_cohorts_were_left_out(raw_spec) -> None:
    """Eight weeks of 20, exported on day 30: weekly needs 3 times once counted, fortnights none."""
    assert _arm_note(raw_spec, "traffic_two_lengths_waiting") == (
        "arm variant_b: "
        + _left_out("2026-05-11 00:00 UTC", "weekly cohorts 4, 5, 6 and 7; 14-day cohorts 2 and 3")
        + "Export again after 2026-06-06 00:00 UTC, once they have closed: 14-day cohorts would"
        " then meet the size rules at the traffic observed. As exported, no multiple of the"
        " traffic would do. Each block length on its own: weekly cohorts, no multiple would do as"
        " exported and 3 times once the cohorts left out are counted; 14-day cohorts, no"
        " multiple would do as exported and no extra traffic once the cohorts left out are"
        " counted."
    )


def test_every_cohort_left_out_is_left_out_of_what_sets_the_traffic(raw_spec) -> None:
    """Weeks 4 and 5 are left out; week 3, with 20, is what sets 1.5 times, and only week 3."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_two_left_out"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert {(b["block"], b["side"]) for b in traffic["now"]["binding"]} == {
        (3, "arm"),
        (3, "control"),
    }
    assert traffic["attempts"][0]["left_out"] == [4, 5]
    assert traffic["windows_close_at"] == "2026-05-23T00:00:00+00:00"


def test_a_block_length_with_no_multiple_says_so_beside_the_one_that_has_one(raw_spec) -> None:
    """Players in weeks 0, 3 and 6 of 8: the weekly median is 0, so weekly blocks cannot be
    helped, while 14-day blocks of 10 need 3 times."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_one_length"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert [(a["block_days"], a["now"], a["after_windows_close"]) for a in traffic["attempts"]] == [
        (7, None, None),
        (14, 3.0, None),
    ]
    assert _arm_note(raw_spec, "traffic_one_length") == (
        "arm variant_b: "
        + _price(
            "3",
            "14-day",
            "both arms have 10 players in 14-day cohorts 0, 1 and 3, where 30 are wanted",
        )
        + " Each block length on its own: weekly cohorts, no multiple would do; 14-day cohorts,"
        " 3 times."
    )


def test_the_price_as_exported_and_the_price_after_the_windows_close_are_both_given(
    raw_spec,
) -> None:
    """Week 4 is left out. As exported, week 3's 12 players must reach 30: 2.5 times. Counted,
    week 4 has 25 and the weekly median of 40 is what binds: 1.5 times."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_exported_early"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert (traffic["now"]["factor"], traffic["after_windows_close"]["factor"]) == (2.5, 1.5)
    assert traffic["waiting_suffices"] is False
    assert _arm_note(raw_spec, "traffic_exported_early") == (
        "arm variant_b: "
        + _left_out("2026-05-14 00:00 UTC", "weekly cohort 4")
        + "As exported, "
        + _price(
            "2.5", "weekly", "both arms have 12 players in weekly cohort 3, where 30 are wanted"
        )
        + " Once they have closed (after 2026-05-16 00:00 UTC) and are counted, "
        + _price(
            "1.5",
            "weekly",
            "the median over the weeks of the smaller arm's size is 40 players and 60 are wanted"
            " for weekly cohorts",
        )
    )


def test_the_same_price_before_and_after_the_windows_close_is_given_once(raw_spec) -> None:
    """Five weeks of 40 in a 35-day plan, week 4 left out: the median of 40 sets 1.5 times
    whether or not week 4 is counted."""
    context = _sized(raw_spec, _flat_sizes(40, 5), _flat_sizes(40, 5), 35, exported_at=at(33))
    report = cohort_report(context, None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert (traffic["now"]["factor"], traffic["after_windows_close"]["factor"]) == (1.5, 1.5)
    note = next(
        n for n in report["notes"] if n.startswith("arm variant_b:") and ", metric" not in n
    )
    assert "Whether or not they are counted, 1.5 times the traffic" in note
    assert note.count("times the traffic observed (every cohort") == 1


def test_each_arm_gets_its_own_price_and_the_assumptions_are_said_once(raw_spec) -> None:
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_three_arms"](raw_spec), None)

    plans = report["plans"]
    assert {a: (p["traffic_needed"]["now"]["factor"], p["floor"]) for a, p in plans.items()} == {
        "variant_b": (3.0, 30),
        "variant_c": (2.0, 43),
    }
    assert _arm_note(raw_spec, "traffic_three_arms", "variant_b").startswith(
        "arm variant_b: 3 times the traffic"
    )
    assert _arm_note(raw_spec, "traffic_three_arms", "variant_c").startswith(
        "arm variant_c: 2 times the traffic"
    )
    notes = report["notes"]
    assert notes.count(CAVEATS) == 1 and notes[-1] == CAVEATS
    assert notes.index(_arm_note(raw_spec, "traffic_three_arms", "variant_b")) < notes.index(
        _arm_note(raw_spec, "traffic_three_arms", "variant_c")
    )


def test_the_assumptions_are_said_when_any_arm_is_priced_and_not_only_the_last(raw_spec) -> None:
    """Variant b is priced; variant c, 10 against control's 150, is more than 9 to 1 apart."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_one_priced_arm"](raw_spec), None)

    plans = report["plans"]
    assert plans["variant_b"]["traffic_needed"]["now"]["factor"] == 3.0
    assert plans["variant_c"]["traffic_needed"]["blocker"] == "arms_too_unequal"
    assert report["notes"].count(CAVEATS) == 1
    assert report["notes"].count(INTERIM_TRAFFIC) == 1


def test_a_stop_for_another_reason_gets_no_traffic_sentence(raw_spec) -> None:
    """The units are not independent, so no cohort plan is the reason; the plan still shows."""
    context = _sized(
        raw_spec,
        _flat_sizes(20, 5),
        _flat_sizes(20, 5),
        35,
        population__randomization_unit="session",
    )

    report = cohort_report(context, None)

    assert {t["reason"] for t in report["tests"]} == {"unit_not_independent"}
    assert not any("times the traffic" in n or "More traffic" in n for n in report["notes"])
    assert not any(n in (CAVEATS, NUMBERING, INTERIM_TRAFFIC) for n in report["notes"])
    assert report["plans"]["variant_b"]["traffic_needed"]["now"]["factor"] == 3.0


def test_a_plan_that_runs_has_no_traffic_to_price(raw_spec) -> None:
    report = cohort_report(_fading(raw_spec), None)

    assert all(plan["traffic_needed"] is None for plan in report["plans"].values())
    assert not any("traffic" in n for n in report["notes"])


def test_the_binding_sizes_read_as_sentences_for_each_kind_side_and_tie() -> None:
    thin = Binding(kind="preferred", block_days=7, block=10, side="control", have=28, need=100)
    two = [
        Binding(kind="floor", block_days=14, block=b, side="arm", have=20, need=30) for b in (1, 2)
    ]
    both = [
        Binding(kind="floor", block_days=7, block=3, side=side, have=1, need=30)
        for side in ("arm", "control")
    ]
    median = Binding(
        kind="weekly_median", block_days=7, block=None, side="smaller_arm", have=20.5, need=60
    )

    assert _binding_text("b", (thin,)) == (
        "control has 28 players in weekly cohort 10, where the preferred minimum is 100"
    )
    assert _binding_text("b", tuple(two)) == (
        "arm b has 20 players in 14-day cohorts 1 and 2, where 30 are wanted"
    )
    assert _binding_text("b", tuple(both)) == (
        "both arms have 1 player in weekly cohort 3, where 30 are wanted"
    )
    assert _binding_text("b", (thin, *two, median)) == (
        "control has 28 players in weekly cohort 10, where the preferred minimum is 100; "
        "arm b has 20 players in 14-day cohorts 1 and 2, where 30 are wanted; "
        "the median over the weeks of the smaller arm's size is 20.5 players and 60 are wanted "
        "for weekly cohorts"
    )
    big = Binding(kind="floor", block_days=7, block=0, side="arm", have=1_000_000, need=2_000_000)
    assert _binding_text("b", (big,)) == (
        "arm b has 1000000 players in weekly cohort 0, where 2000000 are wanted"
    )


def test_arm_and_control_naming_different_cohorts_are_told_apart() -> None:
    def binding(block, side):
        return Binding(kind="floor", block_days=7, block=block, side=side, have=20, need=30)

    named = (binding(1, "arm"), binding(2, "arm"), binding(3, "control"))

    assert _binding_text("b", named) == (
        "arm b has 20 players in weekly cohorts 1 and 2, where 30 are wanted; "
        "control has 20 players in weekly cohort 3, where 30 are wanted"
    )


def test_numbers_are_printed_whole_or_to_a_tenth_and_prices_to_a_hundredth() -> None:
    assert [_count(n) for n in (20, 20.0, 20.5, 1_000_000)] == ["20", "20", "20.5", "1000000"]
    assert [_players(n) for n in (1, 2, 0.5)] == ["1 player", "2 players", "0.5 players"]
    assert [_times(f) for f in (3.0, 1.5, 4.9, 1.43, 12345.64, 2.01)] == [
        "3",
        "1.5",
        "4.9",
        "1.43",
        "12345.64",
        "2.01",
    ]


def _island_for_text():
    """A 20-week plan: it passes at 1.08 times, fails from 1.11 and keeps passing from 3.58."""
    sizes = {b: (150, 150) for b in range(8)} | {8: (90, 90), 9: (90, 90), 10: (28, 28)}
    attempt = Attempt(
        block_days=7,
        window_blocks=20,
        sizes={b: {"a": x, "c": y} for b, (x, y) in sizes.items()},
        usable=(),
        usable_at_floor=(),
        preferred_used=False,
        minimum_arm=Minimum(registered=None, achieved=0, preferred=100, used=30),
        minimum_control=Minimum(registered=None, achieved=0, preferred=100, used=30),
        median_smaller_arm=0.0,
        covers_window=False,
        incomplete=(),
        reason="fewer_than_3_cohorts_reach_minimum",
    )
    plan = CohortPlan(
        arm="a",
        control="c",
        block_days=None,
        usable=(),
        reason=attempt.reason,
        attempts=(attempt,),
        floor=30,
    )
    return attempt, plan


def test_a_block_length_that_no_multiple_can_help_even_counted_is_said_so_beside_the_one_that_can(
    raw_spec,
) -> None:
    """Players in weeks 0, 3 and 6 of 8, exported on day 30 so that week 6 is left out: weekly
    blocks have a median of 0 however they are counted; 14-day blocks need 3 times once counted."""
    report = cohort_report(TRAFFIC_SCENARIOS["traffic_one_length_waiting"](raw_spec), None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert traffic["now"] is None and traffic["waiting_suffices"] is False
    assert traffic["after_windows_close"]["factor"] == 3.0
    assert [(a["block_days"], a["now"], a["after_windows_close"]) for a in traffic["attempts"]] == [
        (7, None, None),
        (14, None, 3.0),
    ]
    note = _arm_note(raw_spec, "traffic_one_length_waiting")
    assert note.endswith(
        " Each block length on its own: weekly cohorts, no multiple would do as exported and no"
        " multiple would do once the cohorts left out are counted; 14-day cohorts, no multiple"
        " would do as exported and 3 times once the cohorts left out are counted."
    )


def test_the_first_pass_is_carried_into_the_evidence() -> None:
    price = Price(factor=3.58, block_days=7, binding=(), first_pass=1.08)

    assert _price_evidence(price) == {
        "factor": 3.58,
        "block_days": 7,
        "binding": [],
        "first_pass": 1.08,
    }
    assert _price_evidence(None) is None


def test_the_time_to_export_again_is_in_utc_and_rounded_up_to_the_minute() -> None:
    moment = datetime(2026, 5, 2, 0, 0, tzinfo=UTC)

    assert _when(moment) == "2026-05-02 00:00 UTC"
    assert _when(moment + timedelta(seconds=1)) == "2026-05-02 00:01 UTC"
    assert _when(moment + timedelta(microseconds=1)) == "2026-05-02 00:01 UTC"
    assert _when(datetime(2026, 5, 2, 2, 0, tzinfo=timezone(timedelta(hours=2)))) == (
        "2026-05-02 00:00 UTC"
    )
    assert _when(datetime(2026, 5, 2, 0, 0)) == "2026-05-02 00:00 UTC"
    assert _when(datetime(2026, 5, 1, 23, 59, 59, tzinfo=UTC)) == "2026-05-02 00:00 UTC"


def _first_traffic_note(report: dict) -> str:
    return next(
        n for n in report["notes"] if n.startswith("arm variant_b:") and ", metric" not in n
    )


def _with_a_late_window(raw_spec, *, exported_at, who="control"):
    """Three weeks of 80 in a 21-day plan, with one player of week 2 whose window ends 30
    seconds after the usual seven days (an explicit window_end)."""
    rows = cohort_rows("control", _weeks([10] * 3)) + cohort_rows("variant_b", _weeks([10] * 3))
    late = next(r for r in rows if r.arm == who and r.player_id.rsplit("_", 2)[1] == "02")
    late.window_end = at(21) + timedelta(seconds=30)
    return cohort_context(raw_spec, rows, days=21, arms=TWO_ARMS, exported_at=exported_at)


@pytest.mark.parametrize("who", ["control", "variant_b"])
def test_exporting_again_after_the_time_given_makes_the_plan_pass_as_the_finding_says(
    raw_spec, who
) -> None:
    """Whichever arm holds the window that closes last, with a window_end of its own and a
    number of seconds: the time given, rounded up to the minute, is early enough and late enough,
    and the first moment at which the plan passes is the moment the window closes."""
    report = cohort_report(_with_a_late_window(raw_spec, exported_at=at(19), who=who), None)
    traffic = report["plans"]["variant_b"]["traffic_needed"]
    closes = datetime.fromisoformat(traffic["windows_close_at"])

    assert closes == at(21) + timedelta(seconds=30) and traffic["waiting_suffices"] is True
    note = next(
        n for n in report["notes"] if n.startswith("arm variant_b:") and ", metric" not in n
    )
    assert "Export again after 2026-05-02 00:01 UTC, once they have closed" in note

    def planned(moment):
        context = _with_a_late_window(raw_spec, exported_at=moment, who=who)
        return plan_cohorts(context, "variant_b")

    assert not planned(closes - timedelta(seconds=1)).evaluated
    at_closing = planned(closes)
    assert (
        at_closing.evaluated
        and at_closing.block_days == traffic["after_windows_close"]["block_days"]
    )
    assert planned(closes.replace(second=0) + timedelta(minutes=1)).evaluated


def test_the_last_window_to_close_is_the_controls_when_the_control_holds_it(raw_spec) -> None:
    """The control's window ends 30 seconds late and the arm's does not: the date is control's."""
    report = cohort_report(_with_a_late_window(raw_spec, exported_at=at(19)), None)
    traffic = report["plans"]["variant_b"]["traffic_needed"]

    assert traffic["windows_close_at"] == "2026-05-02T00:00:30+00:00"
    quiet = cohort_context(
        raw_spec,
        cohort_rows("control", _weeks([10] * 3)) + cohort_rows("variant_b", _weeks([10] * 3)),
        days=21,
        arms=TWO_ARMS,
        exported_at=at(19),
    )
    assert (
        cohort_report(quiet, None)["plans"]["variant_b"]["traffic_needed"]["windows_close_at"]
        == "2026-05-02T00:00:00+00:00"
    )


def test_a_window_that_closes_exactly_at_the_export_is_closed_and_names_no_time(raw_spec) -> None:
    """Five weeks of 20 in a 35-day plan exported at the moment week 4's windows close: nothing
    is left out, so there is no time to wait for, though the plan still needs 3 times."""
    context = _sized(raw_spec, _flat_sizes(20, 5), _flat_sizes(20, 5), 35, exported_at=at(35))

    report = cohort_report(context, None)

    traffic = report["plans"]["variant_b"]["traffic_needed"]
    assert traffic["windows_close_at"] is None and traffic["after_windows_close"] is None
    assert traffic["now"]["factor"] == 3.0
    assert all(a["left_out"] == [] for a in traffic["attempts"])


@pytest.mark.parametrize(
    ("kind", "days_before_assignment", "expected"),
    [
        (
            "existing_users",
            200,
            "population.kind is declared as existing_users, and the column agrees.",
        ),
        (
            "new_users",
            200,
            "population.kind is declared as new_users, but the column says existing users.",
        ),
        ("new_users", 0, "population.kind is declared as new_users, and the column agrees."),
        (
            "existing_users",
            0,
            "population.kind is declared as existing_users, but the column says new users.",
        ),
        (None, 200, "population.kind is not declared."),
    ],
)
def test_with_a_first_seen_column_the_declared_kind_is_checked_against_the_origin(
    raw_spec, kind, days_before_assignment, expected
) -> None:
    """A player first seen before the origin is an existing user and one first seen at or
    after it a new user: the note says what the column shows and whether the spec agrees."""
    rows = cohort_rows("control", _weeks(FLAT)) + cohort_rows("variant_b", _weeks(FADE))
    for row in rows:
        row.first_seen_at = row.assigned_at - timedelta(days=days_before_assignment)
    more = {} if kind is None else {"population__kind": kind}

    note = cohort_report(cohort_context(raw_spec, rows, days=35, **more), None)["notes"][1]

    assert expected in note
    assert "By first_seen_at_utc, " in note and "assigned players were first seen" in note
    existing = days_before_assignment > 0 or kind == "existing_users"  # declared or observed
    assert ("Existing users: players who see a change first" in note) is existing
