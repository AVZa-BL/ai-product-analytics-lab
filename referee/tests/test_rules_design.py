"""DES rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee.review import review_design
from referee.rules import design as des
from referee.spec import ExperimentSpec

# --- DES-001 ---------------------------------------------------------------------------


def test_des_001_fires_for_the_section_6_example_and_states_what_it_can_detect(
    raw_spec: dict,
) -> None:
    """The example needs 389,060 units; its 14 days at 4,200 a day deliver 58,800."""
    finding = evaluate(des.DES_001, raw_spec)

    assert finding is not None
    assert finding.severity == "blocker"
    assert finding.evidence == {
        "required_total": 389_060,
        "achievable_total": 58_800,
        "required_days": 93,
        "required_days_whole_weeks": 98,
        "planned_duration_days": 14,
        "requested_mde_relative": 0.05,
        "achievable_mde_relative": 0.131,
    }


def test_des_001_stays_quiet_when_the_duration_delivers_enough(clean_raw_spec: dict) -> None:
    assert evaluate(des.DES_001, clean_raw_spec) is None


def test_des_001_stays_quiet_at_the_exact_boundary(raw_spec: dict) -> None:
    """389,060 units over 14 days is 27,790 a day exactly: enough, with nothing to spare."""
    raw_spec["population"]["daily_eligible_units"] = 27_790

    assert evaluate(des.DES_001, raw_spec) is None


def test_des_001_fires_one_unit_a_day_below_the_boundary(raw_spec: dict) -> None:
    raw_spec["population"]["daily_eligible_units"] = 27_789

    assert evaluate(des.DES_001, raw_spec) is not None


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


def test_des_001_uses_no_adjustment_only_when_none_is_declared(raw_spec: dict) -> None:
    """With three arms, Bonferroni (the default) needs more units than no adjustment."""
    raw_spec["arms"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "b", "allocation": 0.3},
        {"name": "c", "allocation": 0.3},
    ]
    # 14 days at 42,000 a day deliver 588,000 units. Bonferroni needs 686,047 and no adjustment
    # 566,616, so only the cheaper plan fits.
    raw_spec["population"]["daily_eligible_units"] = 42_000

    with_default = evaluate(des.DES_001, raw_spec)
    with_none = evaluate(des.DES_001, raw_spec, design__alpha_adjustment="none")
    with_dunnett = evaluate(des.DES_001, raw_spec, design__alpha_adjustment="dunnett")

    assert with_default is not None
    assert with_none is None
    assert with_dunnett is not None  # planned as Bonferroni, the conservative stand-in


# --- DES-002 ---------------------------------------------------------------------------


@pytest.mark.parametrize("days", [14, 21, 28, 7], ids=str)
def test_des_002_stays_quiet_for_whole_weeks(clean_raw_spec: dict, days: int) -> None:
    assert (
        evaluate(
            des.DES_002,
            clean_raw_spec,
            design__planned_duration_days=days,
            design__min_duration_days=days,
        )
        is None
    )


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


@pytest.mark.parametrize("days", [14, 15, 28])
def test_des_003_stays_quiet_from_14_days(clean_raw_spec: dict, days: int) -> None:
    assert evaluate(des.DES_003, clean_raw_spec, design__planned_duration_days=days) is None


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


def test_des_004_stays_quiet_for_an_equal_two_arm_split(clean_raw_spec: dict) -> None:
    assert evaluate(des.DES_004, clean_raw_spec) is None


def test_des_004_treats_thirds_written_to_ten_places_as_equal(clean_raw_spec: dict) -> None:
    """Valid specs may round an allocation; 3e-11 of rounding is not an unequal split."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.3333333333, "is_control": True},
        {"name": "b", "allocation": 0.3333333333},
        {"name": "c", "allocation": 0.3333333334},
    ]

    assert evaluate(des.DES_004, clean_raw_spec, design__alpha_adjustment="bonferroni") is None


def test_des_004_fires_for_a_split_unequal_beyond_rounding(clean_raw_spec: dict) -> None:
    clean_raw_spec["arms"][0]["allocation"] = 0.5000001
    clean_raw_spec["arms"][1]["allocation"] = 0.4999999

    assert evaluate(des.DES_004, clean_raw_spec) is not None


def test_des_004_fires_when_only_some_arms_sit_at_the_equal_share(clean_raw_spec: dict) -> None:
    """Four arms with two of them at exactly 0.25 are still not an equal split."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.25, "is_control": True},
        {"name": "b", "allocation": 0.25},
        {"name": "c", "allocation": 0.4},
        {"name": "d", "allocation": 0.1},
    ]

    assert evaluate(des.DES_004, clean_raw_spec, design__alpha_adjustment="bonferroni") is not None


def test_des_004_still_reports_the_split_when_the_effect_is_unattainable(
    clean_raw_spec: dict,
) -> None:
    clean_raw_spec["arms"][0]["allocation"] = 0.7
    clean_raw_spec["arms"][1]["allocation"] = 0.3

    finding = evaluate(
        des.DES_004, clean_raw_spec, primary_metric__baseline=0.6, design__mde_relative=0.8
    )

    assert finding is not None
    assert finding.evidence["extra_units_vs_equal_split"] is None


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


@pytest.mark.parametrize("adjustment", ["bonferroni", "dunnett"])
def test_des_005_stays_quiet_when_an_adjustment_is_declared(
    three_arm_spec: dict, adjustment: str
) -> None:
    assert evaluate(des.DES_005, three_arm_spec, design__alpha_adjustment=adjustment) is None


def test_des_005_stays_quiet_for_two_arms(clean_raw_spec: dict) -> None:
    assert evaluate(des.DES_005, clean_raw_spec) is None


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


@pytest.mark.parametrize("unit", ["player", "user"])
def test_des_006_stays_quiet_when_no_interference_is_expected(
    clean_raw_spec: dict, unit: str
) -> None:
    assert (
        evaluate(
            des.DES_006,
            clean_raw_spec,
            population__randomization_unit=unit,
            population__analysis_unit=unit,
        )
        is None
    )


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


@pytest.mark.parametrize("timing", ["pre_treatment", None], ids=["pre", "undeclared"])
def test_des_007_stays_quiet_unless_exposure_is_declared_post_treatment(
    clean_raw_spec: dict, timing: str | None
) -> None:
    assert evaluate(des.DES_007, clean_raw_spec, population__exposure_timing=timing) is None


# --- DES-008 ---------------------------------------------------------------------------


def test_des_008_fires_without_a_covariate(clean_raw_spec: dict) -> None:
    finding = evaluate(des.DES_008, clean_raw_spec, design__pre_period_covariate=None)

    assert finding is not None
    assert finding.evidence == {"field": "design.pre_period_covariate", "value": None}


def test_des_008_stays_quiet_with_a_covariate(clean_raw_spec: dict) -> None:
    assert evaluate(des.DES_008, clean_raw_spec) is None


# --- The whole review ------------------------------------------------------------------


def test_the_section_6_example_is_told_to_revise_because_it_is_underpowered(
    raw_spec: dict,
) -> None:
    review = review_design(ExperimentSpec.from_dict(raw_spec))

    assert [f.rule_id for f in review.findings] == [
        "DES-001",
        "PRO-001",
        "DES-006",
        "DES-008",
        "PRO-002",
        "PRO-004",
    ]
    assert review.blocking_rule_ids == ("DES-001", "PRO-001")
    assert review.recommendation == "revise"


def test_the_clean_spec_proceeds_with_no_findings(clean_raw_spec: dict) -> None:
    review = review_design(ExperimentSpec.from_dict(clean_raw_spec))

    assert review.findings == ()
    assert review.recommendation == "proceed"


def test_an_unattainable_effect_is_a_blocker_and_the_review_still_completes(
    clean_raw_spec: dict,
) -> None:
    clean_raw_spec["primary_metric"]["baseline"] = 0.6
    clean_raw_spec["design"]["mde_relative"] = 0.8

    review = review_design(ExperimentSpec.from_dict(clean_raw_spec))

    assert review.blocking_rule_ids == ("DES-001",)
    assert review.recommendation == "revise"
