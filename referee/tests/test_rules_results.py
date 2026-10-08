"""The results rules (design section 21.4), one at a time."""

import json
from pathlib import Path

import pytest
from results_helpers import (
    TWO_ARMS,
    at,
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
    assert review.blocking_rule_ids == ("RES-001",)
    assert review.rules_run == tuple(sorted(rule.id for rule in RESULTS_RULES))
