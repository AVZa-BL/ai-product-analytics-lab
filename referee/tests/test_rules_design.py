"""DES rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee.rules import design as des

# --- DES-001 ---------------------------------------------------------------------------


def test_des_001_reports_an_unattainable_effect_instead_of_a_sample_size(raw_spec: dict) -> None:
    """A 0.8 relative lift on a 60% rate would be a 108% rate: no sample size reaches it."""
    finding = evaluate(
        des.DES_001, raw_spec, primary_metric__baseline=0.6, design__mde_relative=0.8
    )

    assert finding is not None
    assert finding.evidence == {
        "unattainable": True,
        "reason": (
            "a relative effect of 0.8 on a rate of 0.6 leaves the range 0 to 1 "
            "in every direction the hypothesis allows"
        ),
        "requested_mde_relative": 0.8,
    }


# --- DES-002 ---------------------------------------------------------------------------


@pytest.mark.parametrize(("days", "next_weeks"), [(15, 21), (20, 21), (22, 28), (10, 14)])
def test_des_002_fires_otherwise_and_names_the_next_whole_week(
    clean_raw_spec: dict, days: int, next_weeks: int
) -> None:
    finding = evaluate(
        des.DES_002, clean_raw_spec, design__planned_duration_days=days, design__min_duration_days=1
    )

    assert finding is not None
    assert finding.evidence == {"planned_duration_days": days, "next_whole_weeks_days": next_weeks}


# --- DES-003 ---------------------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 7, 13])
def test_des_003_fires_below_14_days(clean_raw_spec: dict, days: int) -> None:
    finding = evaluate(
        des.DES_003, clean_raw_spec, design__planned_duration_days=days, design__min_duration_days=1
    )

    assert finding is not None
    assert finding.evidence == {"planned_duration_days": days, "recommended_minimum_days": 14}


# --- DES-004 ---------------------------------------------------------------------------


def test_des_004_states_the_cost_of_a_70_30_split(clean_raw_spec: dict) -> None:
    """Amendment 2 section 17.3: +18.2% for 70/30 at a 10% effect on a 3.2% baseline."""
    clean_raw_spec["arms"][0]["allocation"] = 0.7
    clean_raw_spec["arms"][1]["allocation"] = 0.3
    clean_raw_spec["design"]["mde_relative"] = 0.10

    finding = evaluate(des.DES_004, clean_raw_spec)

    assert finding is not None
    assert finding.severity == "info"
    assert finding.evidence == {
        "allocations": {"control": 0.7, "variant_b": 0.3},
        "extra_units_vs_equal_split": 0.1816,
    }


def test_des_004_can_report_a_saving(clean_raw_spec: dict) -> None:
    """With two variants, a larger control is slightly cheaper than an equal split."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.5, "is_control": True},
        {"name": "b", "allocation": 0.25},
        {"name": "c", "allocation": 0.25},
    ]

    finding = evaluate(des.DES_004, clean_raw_spec, design__alpha_adjustment="bonferroni")

    assert finding is not None
    assert finding.evidence["extra_units_vs_equal_split"] == -0.0036


# --- DES-005 ---------------------------------------------------------------------------


@pytest.fixture
def three_arm_spec(clean_raw_spec: dict) -> dict:
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "b", "allocation": 0.3},
        {"name": "c", "allocation": 0.3},
    ]
    return clean_raw_spec


@pytest.mark.parametrize("adjustment", [None, "none"], ids=["absent", "explicit none"])
def test_des_005_fires_for_three_arms_without_an_adjustment(
    three_arm_spec: dict, adjustment: str | None
) -> None:
    finding = evaluate(des.DES_005, three_arm_spec, design__alpha_adjustment=adjustment)

    assert finding is not None
    assert finding.evidence == {"arms": 3, "comparisons": 2, "alpha_adjustment": adjustment}


# --- DES-006 ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["player", "user"])
@pytest.mark.parametrize("interference", [None, "possible"], ids=["undeclared", "possible"])
def test_des_006_fires_for_player_or_user_units_unless_none_is_expected(
    clean_raw_spec: dict, unit: str, interference: str | None
) -> None:
    finding = evaluate(
        des.DES_006,
        clean_raw_spec,
        population__randomization_unit=unit,
        population__analysis_unit=unit,
        population__interference=interference,
    )

    assert finding is not None
    assert finding.evidence == {"randomization_unit": unit, "interference": interference}


@pytest.mark.parametrize("unit", ["device", "session", "cluster"])
def test_des_006_leaves_other_units_alone(clean_raw_spec: dict, unit: str) -> None:
    assert (
        evaluate(
            des.DES_006,
            clean_raw_spec,
            population__randomization_unit=unit,
            population__analysis_unit=unit,
            population__interference="possible",
        )
        is None
    )


# --- DES-007 ---------------------------------------------------------------------------


def test_des_007_fires_for_post_treatment_exposure(clean_raw_spec: dict) -> None:
    finding = evaluate(des.DES_007, clean_raw_spec, population__exposure_timing="post_treatment")

    assert finding is not None
    assert finding.severity == "blocker"
    assert finding.evidence == {
        "exposure_timing": "post_treatment",
        "exposure_trigger": "offer_page_view",
    }


# --- DES-008 ---------------------------------------------------------------------------


# --- The whole review ------------------------------------------------------------------


