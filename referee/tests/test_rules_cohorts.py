"""RES-007: the effect differs between cohorts of first exposure (design sections 21.5 to 21.7).

The data are exact: every cohort holds 80 players whose session counts have a known mean and
spread, so each scenario's outcome can be reasoned out before it is run.
"""

import json
from datetime import timedelta

import pytest
from cohort_helpers import THREE_ARMS, cohort_context, cohort_rows, spread
from results_helpers import TWO_ARMS, at

from referee.cohort_effects import (
    NULL_FLAG_RATE_MAX,
    NULL_FLAG_RATE_MEAN,
    ScaleTest,
    cohort_test,
    detectable_shifts,
)
from referee.cohorts import plan_cohorts
from referee.results import ResultsContext
from referee.rules import RESULTS_RULES
from referee.rules.cohorts import _amount, _scale, _share, _shifts, cohort_report, summarise

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
}


def _by_arm(report: dict, metric: str | None = None) -> dict[str, dict]:
    return {t["arm"]: t for t in report["tests"] if metric in (None, t["metric"])}


def _config_of(context: ResultsContext):
    """The evidence of RES-013 for this context, as the rule's own check gives it."""
    return RES_013.check(context)


# --- The rule ------------------------------------------------------------------------------


def test_res_007_is_a_warning_between_res_003_and_res_011_citing_the_heterogeneity_literature():
    ids = [rule.id for rule in RESULTS_RULES]

    assert RES_007.severity == "warning" and RES_007.escalation is None
    assert ids[ids.index("RES-003") + 1 : ids.index("RES-011")] == ["RES-007"]
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
        "RES-007: 1 tests, 0 flagged, 1 not evaluated, 0 low information"
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
    assert "With 80% probability" in note and "it could have missed anything smaller" in note
    assert "a little optimistic" in note
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
        "2 tests ran. In the simulations of design section 21.5 (two arms, no change over time) the"
        " trigger flagged 3.5% of tests on average and at most 5.1%, so about 0.069 flags (at most"
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
