"""The results rules (design section 21.4), one at a time."""

import json
from pathlib import Path

import pytest
from results_helpers import (
    TWO_ARMS,
    at,
    build_data,
    crowd,
    evaluate_results,
    results_spec,
)

from referee.data import load_export
from referee.methods import srm_test
from referee.results import ResultsContext
from referee.review import review_results
from referee.rules import RESULTS_RULES

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _rule(rule_id: str):
    return next(rule for rule in RESULTS_RULES if rule.id == rule_id)


@pytest.fixture(scope="module")
def export():
    return load_export(FIXTURE, "hybrid_offer_page")


# --- RES-001: sample ratio mismatch ---------------------------------------------------------

RES_001 = _rule("RES-001")


def test_res_001_is_a_blocker_citing_the_sample_ratio_literature() -> None:
    assert RES_001.severity == "blocker"
    assert any("Sample Ratio Mismatch" in reference for reference in RES_001.references)
    assert "0.001" in RES_001.fires_when


def test_res_001_is_quiet_when_the_arms_are_the_registered_size(raw_spec) -> None:
    rows = [*crowd("control", 100), *crowd("variant_b", 100), *crowd("variant_c", 100)]

    assert evaluate_results(RES_001, results_spec(raw_spec), rows) is None


@pytest.mark.parametrize(
    ("control", "variant", "flagged"),
    [(552, 448, False), (553, 447, True), (500, 500, False), (448, 552, False), (447, 553, True)],
)
def test_res_001_fires_when_p_is_below_one_in_a_thousand_and_not_at_it(
    raw_spec, control: int, variant: int, flagged: bool
) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    rows = [*crowd("control", control), *crowd("variant_b", variant)]

    finding = evaluate_results(RES_001, spec, rows)

    assert srm_test([control, variant], [0.5, 0.5]).flagged is flagged
    assert (finding is not None) is flagged


def test_res_001_reports_the_counts_the_test_and_the_week_by_week_check(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    rows = [
        *crowd("control", 300, prefix="c0"),
        *crowd("variant_b", 200, prefix="v0"),
        *crowd("control", 100, prefix="c3", assigned_at=at(22), exposed_at=at(22, 1)),
        *crowd("variant_b", 100, prefix="v3", assigned_at=at(22), exposed_at=at(22, 1)),
    ]

    finding = evaluate_results(RES_001, spec, rows)

    assert finding is not None
    evidence = finding.evidence
    total = srm_test([400, 300], [0.5, 0.5])
    assert evidence["assigned"] == {"control": 400, "variant_b": 300}
    assert evidence["allocation"] == {"control": 0.5, "variant_b": 0.5}
    assert evidence["expected"] == {"control": 350.0, "variant_b": 350.0}
    assert evidence["chi_square"] == round(total.chi_square, 4) == 14.2857
    assert evidence["degrees_of_freedom"] == 1 and evidence["alpha"] == 0.001
    assert evidence["p_value"] == total.p_value
    # Weeks 0 and 3 hold players; weeks 1 and 2 hold nobody and are not listed.
    assert [w["week"] for w in evidence["by_week"]] == [0, 3]
    assert evidence["by_week"][0] == {
        "week": 0,
        "assigned": {"control": 300, "variant_b": 200},
        "p_value": srm_test([300, 200], [0.5, 0.5]).p_value,
    }
    assert evidence["by_week"][1]["p_value"] == 1.0  # 100 against 100


def test_res_001_evidence_can_be_written_as_json(raw_spec) -> None:
    spec = results_spec(raw_spec, arms=TWO_ARMS)
    finding = evaluate_results(RES_001, spec, [*crowd("control", 600), *crowd("variant_b", 400)])

    assert finding is not None
    assert json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_001_counts_every_assigned_player_not_only_the_analysed(raw_spec) -> None:
    # Equal arms as assigned, but half of variant_b was never exposed: the check is on
    # assignment, so a loss at exposure cannot hide a mismatch, or make one.
    rows = [
        *crowd("control", 100),
        *crowd("variant_b", 50),
        *crowd("variant_b", 50, prefix="never", exposed_at=None),
    ]
    spec = results_spec(raw_spec, arms=TWO_ARMS)

    assert evaluate_results(RES_001, spec, rows) is None


def test_res_001_counts_late_exposed_players_too(raw_spec) -> None:
    late = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
    rows = [
        *crowd("control", 100),
        *crowd("variant_b", 40),
        *crowd("variant_b", 60, prefix="late", **late),
    ]

    assert evaluate_results(RES_001, results_spec(raw_spec, arms=TWO_ARMS), rows) is None


def test_res_001_tests_against_the_registered_allocation_not_against_equal_arms(raw_spec) -> None:
    arms = [
        {"name": "control", "allocation": 0.7, "is_control": True},
        {"name": "variant_b", "allocation": 0.3},
    ]
    spec = results_spec(raw_spec, arms=arms)

    assert (
        evaluate_results(RES_001, spec, [*crowd("control", 700), *crowd("variant_b", 300)]) is None
    )
    finding = evaluate_results(RES_001, spec, [*crowd("control", 300), *crowd("variant_b", 700)])
    assert finding is not None and finding.evidence["allocation"] == {
        "control": 0.7,
        "variant_b": 0.3,
    }


def test_res_001_pairs_each_arm_with_its_own_allocation_whatever_the_order_of_the_arms(
    raw_spec,
) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.3},
        {"name": "control", "allocation": 0.7, "is_control": True},
    ]
    spec = results_spec(raw_spec, arms=arms)

    assert (
        evaluate_results(RES_001, spec, [*crowd("control", 700), *crowd("variant_b", 300)]) is None
    )
    finding = evaluate_results(RES_001, spec, [*crowd("control", 300), *crowd("variant_b", 700)])
    assert finding is not None and list(finding.evidence["assigned"]) == ["variant_b", "control"]


def test_res_001_sees_an_arm_that_vanished(raw_spec) -> None:
    rows = [*crowd("control", 100), *crowd("variant_b", 100)]  # variant_c has nobody

    finding = evaluate_results(RES_001, results_spec(raw_spec), rows)

    assert finding is not None
    assert finding.evidence["assigned"] == {"control": 100, "variant_b": 100, "variant_c": 0}


def test_res_001_leaves_out_players_assigned_before_the_registered_start(raw_spec) -> None:
    early = crowd("control", 300, prefix="early", assigned_at=at(-5), exposed_at=at(-5, 1))
    rows = [*early, *crowd("control", 100), *crowd("variant_b", 100)]
    spec_without = results_spec(raw_spec, arms=TWO_ARMS)
    spec_with = results_spec(raw_spec, arms=TWO_ARMS, design__start_utc="2026-04-11T00:00:00Z")

    assert evaluate_results(RES_001, spec_without, rows) is not None
    assert evaluate_results(RES_001, spec_with, rows) is None


# --- On the committed export of the lab's 5,000-player experiment ---------------------------


def test_res_001_finds_the_planted_mismatch_in_the_committed_export(raw_spec, export) -> None:
    context = ResultsContext.of(results_spec(raw_spec), export)

    finding = RES_001.evaluate(context)

    assert finding is not None
    evidence = finding.evidence
    assert evidence["assigned"] == {"control": 997, "variant_b": 1046, "variant_c": 781}
    assert evidence["expected"] == {arm: 941.33 for arm in evidence["assigned"]}
    assert evidence["chi_square"] == 42.2387 and evidence["degrees_of_freedom"] == 2
    assert evidence["p_value"] == pytest.approx(6.7e-10, rel=0.01, abs=0)
    weeks = {w["week"]: w for w in evidence["by_week"]}
    assert sorted(weeks) == [0, 1, 2]
    assert weeks[0]["assigned"] == {"control": 327, "variant_b": 357, "variant_c": 322}
    assert weeks[1]["assigned"] == {"control": 343, "variant_b": 356, "variant_c": 252}
    assert weeks[2]["assigned"] == {"control": 327, "variant_b": 333, "variant_c": 207}
    assert weeks[0]["p_value"] == pytest.approx(0.34, abs=0.005)
    assert weeks[1]["p_value"] == pytest.approx(4.0e-5, rel=0.01, abs=0)
    assert weeks[2]["p_value"] == pytest.approx(2.6e-8, rel=0.02, abs=0)


def test_a_results_review_of_the_committed_export_is_invalid_because_of_res_001(
    raw_spec, export
) -> None:
    review = review_results(results_spec(raw_spec), export)

    assert review.verdict == "invalid"
    assert "RES-001" in review.blocking_rule_ids
    assert review.rules_run == tuple(sorted(rule.id for rule in RESULTS_RULES))


# --- RES-002: fewer players than the registered sample size ---------------------------------

RES_002 = _rule("RES-002")
SMALL = {"design__mde_relative": 1.5}  # a large effect, so the registered n is small (222 a arm)


def _required(raw_spec, **changes) -> dict[str, int]:
    """The registered n per arm of a two-arm spec with `changes`, found the way the rule does."""
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL, **changes)
    context = ResultsContext.of(spec, build_data(crowd("control", 1) + crowd("variant_b", 1)))
    return {arm: context.required_n(arm) for arm in ("control", "variant_b")}


def test_res_002_is_a_blocker_about_the_registered_size() -> None:
    assert RES_002.severity == "blocker"
    assert "fewer players than" in RES_002.fires_when and "power plan" in RES_002.fires_when


def test_res_002_is_quiet_when_every_arm_has_exactly_its_registered_size(raw_spec) -> None:
    required = _required(raw_spec)
    rows = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"])]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    assert required == {"control": 222, "variant_b": 222}
    assert evaluate_results(RES_002, spec, rows) is None


def test_res_002_fires_for_one_player_short_and_names_the_arm(raw_spec) -> None:
    required = _required(raw_spec)
    rows = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"] - 1)]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence == {
        "required": {"control": 222, "variant_b": 222},
        "analysed": {"control": 222, "variant_b": 221},
        "assigned": {"control": 222, "variant_b": 221},
        "short_arms": ["variant_b"],
        "missing": {"variant_b": 1},
    }


def test_res_002_counts_the_analysed_players_not_the_assigned(raw_spec) -> None:
    required = _required(raw_spec)
    late = {"exposed_at": at(0, 5), "purchases": 1, "first_purchase_at": at(0, 1)}
    rows = [
        *crowd("control", required["control"]),
        *crowd("variant_b", required["variant_b"] - 10),
        *crowd("variant_b", 5, prefix="never", exposed_at=None),
        *crowd("variant_b", 5, prefix="late", **late),
    ]
    spec = results_spec(raw_spec, arms=TWO_ARMS, **SMALL)

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence["assigned"]["variant_b"] == 222  # enough were assigned...
    assert finding.evidence["analysed"]["variant_b"] == 212  # ...but 10 left the analysis
    assert finding.evidence["missing"] == {"variant_b": 10}


def test_res_002_finds_each_arms_requirement_by_name(raw_spec) -> None:
    arms = [
        {"name": "variant_b", "allocation": 0.3},
        {"name": "control", "allocation": 0.7, "is_control": True},
    ]
    spec = results_spec(raw_spec, arms=arms, **SMALL)
    required = {"control": 344, "variant_b": 148}
    enough = [*crowd("control", required["control"]), *crowd("variant_b", required["variant_b"])]
    swapped = [*crowd("control", required["variant_b"]), *crowd("variant_b", required["control"])]

    assert evaluate_results(RES_002, spec, enough) is None
    finding = evaluate_results(RES_002, spec, swapped)
    assert finding is not None and finding.evidence["short_arms"] == ["control"]
    assert finding.evidence["required"] == {"variant_b": 148, "control": 344}


def test_res_002_reports_an_arm_nobody_is_in(raw_spec) -> None:
    spec = results_spec(raw_spec, **SMALL)
    rows = [*crowd("control", 300), *crowd("variant_b", 300)]  # variant_c has nobody

    finding = evaluate_results(RES_002, spec, rows)

    assert finding is not None
    assert finding.evidence["short_arms"] == ["variant_c"]
    assert finding.evidence["analysed"]["variant_c"] == 0


def test_res_002_says_so_when_the_design_cannot_be_sized(raw_spec) -> None:
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        primary_metric={"name": "purchased_7d", "kind": "binary", "baseline": 0.9},
        design__mde_relative=0.2,
    )

    finding = evaluate_results(RES_002, spec, [*crowd("control", 50), *crowd("variant_b", 50)])

    assert finding is not None
    assert finding.evidence["unattainable"] is True and finding.evidence["reason"]
    assert finding.evidence["analysed"] == {"control": 50, "variant_b": 50}


def test_res_002_evidence_can_be_written_as_json(raw_spec) -> None:
    finding = evaluate_results(
        RES_002,
        results_spec(raw_spec, arms=TWO_ARMS, **SMALL),
        [*crowd("control", 5), *crowd("variant_b", 5)],
    )

    assert finding is not None and json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_002_on_the_committed_export_every_arm_is_far_short(raw_spec, export) -> None:
    context = ResultsContext.of(results_spec(raw_spec), export)

    finding = RES_002.evaluate(context)

    assert finding is not None
    assert finding.evidence["analysed"] == {"control": 926, "variant_b": 969, "variant_c": 731}
    assert finding.evidence["short_arms"] == ["control", "variant_b", "variant_c"]
    assert finding.evidence["missing"] == {
        arm: context.required_n(arm) - n for arm, n in finding.evidence["analysed"].items()
    }


# --- RES-003: ran for less than the registered minimum duration ----------------------------

RES_003 = _rule("RES-003")


def _span(raw_spec, days: float, *, minimum: int = 14, extra: list | None = None):
    """A two-arm export whose assignments run from the start to `days` later."""
    rows = [
        *crowd("control", 5, prefix="first"),
        *crowd("variant_b", 5, prefix="last", assigned_at=at(days), exposed_at=at(days, 1)),
        *(extra or []),
    ]
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        design__min_duration_days=minimum,
        design__planned_duration_days=max(minimum, 30),
    )
    return evaluate_results(RES_003, spec, rows)


def test_res_003_is_a_blocker_about_the_minimum_duration() -> None:
    assert RES_003.severity == "blocker" and "design.min_duration_days" in RES_003.fires_when


@pytest.mark.parametrize(
    ("days", "fires"),
    [(14.0, False), (13.5, False), (13.0, True), (13.0001, False), (20.0, False), (0.0, True)],
    ids=["exactly-14", "13.5-rounds-up", "13", "just-over-13", "20", "one-day-of-assignment"],
)
def test_res_003_rounds_the_observed_days_up_and_compares_with_the_minimum(
    raw_spec, days: float, fires: bool
) -> None:
    assert (_span(raw_spec, days) is not None) is fires


def test_res_003_reports_what_was_observed(raw_spec) -> None:
    finding = _span(raw_spec, 9.25, minimum=14)

    assert finding is not None
    assert finding.evidence == {
        "observed_days": 10,
        "min_duration_days": 14,
        "planned_duration_days": 30,
        "first_assignment": "2026-04-11T00:00:00+00:00",
        "last_assignment": "2026-04-20T06:00:00+00:00",
        "ignored_before_start": [],
    }
    assert json.loads(json.dumps(finding.evidence)) == finding.evidence


def test_res_003_measures_from_the_first_assignment_after_the_registered_start(raw_spec) -> None:
    early = crowd("control", 2, prefix="early", assigned_at=at(-20), exposed_at=at(-20, 1))
    rows = [
        *early,
        *crowd("control", 5, prefix="first", assigned_at=at(0), exposed_at=at(0, 1)),
        *crowd("variant_b", 5, prefix="last", assigned_at=at(9), exposed_at=at(9, 1)),
    ]
    base = {"arms": TWO_ARMS, "design__min_duration_days": 14, "design__planned_duration_days": 30}

    without_start = evaluate_results(RES_003, results_spec(raw_spec, **base), rows)
    with_start = evaluate_results(
        RES_003, results_spec(raw_spec, design__start_utc="2026-04-10T00:00:00Z", **base), rows
    )

    assert without_start is None  # 29 days from the early rows
    assert with_start is not None
    assert with_start.evidence["observed_days"] == 9
    assert with_start.evidence["ignored_before_start"] == ["early_0000", "early_0001"]


def test_res_003_on_the_committed_export_the_run_lasted_21_days(raw_spec, export) -> None:
    quiet = ResultsContext.of(results_spec(raw_spec, design__planned_duration_days=30), export)
    long_minimum = results_spec(
        raw_spec, design__planned_duration_days=30, design__min_duration_days=22
    )

    assert RES_003.evaluate(quiet) is None  # min_duration_days of the shared spec is 14
    finding = RES_003.evaluate(ResultsContext.of(long_minimum, export))
    assert finding is not None
    assert finding.evidence["observed_days"] == 21
    assert finding.evidence["last_assignment"] == "2026-05-01T23:37:55+00:00"
