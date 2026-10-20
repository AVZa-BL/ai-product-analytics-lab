"""DES rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee import cohorts
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


@pytest.mark.parametrize("kind", [None, "existing_users", "mixed"])
def test_des_003_says_nothing_about_new_users_unless_they_are_declared(
    clean_raw_spec: dict, kind: str | None
) -> None:
    changes = {"design__planned_duration_days": 7, "design__min_duration_days": 1}
    if kind is not None:
        changes["population__kind"] = kind

    finding = evaluate(des.DES_003, clean_raw_spec, **changes)

    assert finding is not None
    assert finding.evidence == {"planned_duration_days": 7, "recommended_minimum_days": 14}


def test_des_003_explains_the_accrual_and_outcome_windows_for_new_users(
    clean_raw_spec: dict,
) -> None:
    finding = evaluate(
        des.DES_003,
        clean_raw_spec,
        design__planned_duration_days=10,
        design__min_duration_days=1,
        population__kind="new_users",
    )

    assert finding is not None
    assert finding.evidence["planned_duration_days"] == 10
    assert finding.evidence["population_kind"] == "new_users"
    assert finding.evidence["note"] == (
        "population.kind is new_users: design.planned_duration_days is the accrual window, the "
        "days in which new players are assigned. Each player's outcome window of 7 days "
        "follows that player's assignment, so the last outcomes arrive 7 days after accrual "
        "ends, and the accrual window and the outcome window must both fit in the time "
        "available. The cohort check (RES-007) needs 3 weekly cohorts of new players, which is "
        "21 days of accrual; 4 weekly cohorts, 28 days, if the export is taken when accrual "
        "ends, because the outcome windows of the last week are still open then and that "
        "cohort is left out."
    )


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


# --- DES-009 ---------------------------------------------------------------------------


def test_des_009_states_the_plan_it_judged_and_what_would_pass(raw_spec: dict) -> None:
    """The section 6 example: 14 days at 4,200 units a day, half and half."""
    finding = evaluate(des.DES_009, raw_spec)

    assert finding is not None and finding.severity == "info"
    assert finding.evidence == {
        "reasons": ["window_holds_fewer_than_3_blocks"],
        "planned_duration_days": 14,
        "whole_weekly_blocks": 2,
        "minimum_weekly_blocks": 3,
        "daily_eligible_units": 4_200,
        "arms_checked": 1,
        "comparisons": [
            {
                "arm": "variant_b",
                "reason": "window_holds_fewer_than_3_blocks",
                "allocation_ratio": 1.0,
                "expected_players_per_week": {"arm": 14_700.0, "control": 14_700.0},
            }
        ],
        "minimum_planned_days": 21,
        "daily_eligible_units_for_even_arrivals": 4_200,
    }


def test_des_009_prices_the_units_where_it_goes_quiet(clean_raw_spec: dict) -> None:
    """28 days at 10 units a day is 35 players a week in each arm; the weekly median of 60 asks
    for 3.5 players per unit a day, so 18 units. The price is where the rule stops firing."""
    finding = evaluate(
        des.DES_009,
        clean_raw_spec,
        design__planned_duration_days=28,
        population__daily_eligible_units=10,
    )

    assert finding is not None
    assert finding.evidence["reasons"] == ["cohorts_too_small_for_weekly_blocks"]
    price = finding.evidence["daily_eligible_units_for_even_arrivals"]
    assert price == 18
    for daily, fires in ((price - 1, True), (price, False)):
        again = evaluate(
            des.DES_009,
            clean_raw_spec,
            design__planned_duration_days=28,
            population__daily_eligible_units=daily,
        )
        assert (again is not None) is fires


def test_des_009_judges_each_arm_against_control_on_its_own_allocation(
    clean_raw_spec: dict,
) -> None:
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.5, "is_control": True},
        {"name": "variant_b", "allocation": 0.4},
        {"name": "variant_c", "allocation": 0.1},
    ]

    finding = evaluate(des.DES_009, clean_raw_spec, population__daily_eligible_units=100)

    # variant_b and control hold 280 and 350 a week; variant_c holds 70, 5 to 1 below control,
    # where the floor rises to 128
    assert finding is not None and finding.evidence["arms_checked"] == 2
    assert [(c["arm"], c["reason"]) for c in finding.evidence["comparisons"]] == [
        ("variant_c", "fewer_than_3_cohorts_reach_minimum")
    ]
    assert finding.evidence["comparisons"][0]["allocation_ratio"] == 5.0


def test_des_009_reads_control_as_the_smaller_arm_too(clean_raw_spec: dict) -> None:
    """Control at 0.2 against 0.8 and 50 units a day: 70 players a week in control, 280 in the
    arm, 4 to 1, where the floor rises to 97 and control's 70 do not reach it."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.2, "is_control": True},
        {"name": "variant_b", "allocation": 0.8},
    ]

    finding = evaluate(
        des.DES_009,
        clean_raw_spec,
        design__planned_duration_days=28,
        population__daily_eligible_units=50,
    )

    assert finding is not None
    (comparison,) = finding.evidence["comparisons"]
    assert comparison == {
        "arm": "variant_b",
        "reason": "fewer_than_3_cohorts_reach_minimum",
        "allocation_ratio": 4.0,
        "expected_players_per_week": {"arm": 280.0, "control": 70.0},
    }


def test_des_009_does_not_refuse_nine_to_one_which_floats_write_as_a_hair_over(
    clean_raw_spec: dict,
) -> None:
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.27, "is_control": True},
        {"name": "variant_b", "allocation": 0.03},
        {"name": "variant_c", "allocation": 0.70},
    ]

    assert 0.27 / 0.03 > 9  # the float quotient, though the arms are 9 to 1 and not beyond
    assert evaluate(des.DES_009, clean_raw_spec) is None


def test_des_009_prices_the_arm_that_needs_the_most(clean_raw_spec: dict) -> None:
    """Weekly blocks of a 28-day plan need 60 in the smaller arm of each pair: variant_b
    (0.3 against 0.5) at 29 units a day, variant_c (0.2 against 0.5, a floor of 55) at 43."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.5, "is_control": True},
        {"name": "variant_b", "allocation": 0.3},
        {"name": "variant_c", "allocation": 0.2},
    ]
    changes = {"design__planned_duration_days": 28}

    finding = evaluate(des.DES_009, clean_raw_spec, population__daily_eligible_units=20, **changes)

    assert finding is not None
    assert [(c["arm"], c["allocation_ratio"]) for c in finding.evidence["comparisons"]] == [
        ("variant_b", 1.6667),
        ("variant_c", 2.5),
    ]
    assert finding.evidence["daily_eligible_units_for_even_arrivals"] == 43
    at_43 = evaluate(des.DES_009, clean_raw_spec, population__daily_eligible_units=43, **changes)
    at_42 = evaluate(des.DES_009, clean_raw_spec, population__daily_eligible_units=42, **changes)
    assert at_43 is None and [c["arm"] for c in at_42.evidence["comparisons"]] == ["variant_c"]


def test_des_009_gives_no_price_for_arms_too_far_apart(clean_raw_spec: dict) -> None:
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.95, "is_control": True},
        {"name": "variant_b", "allocation": 0.05},
    ]

    finding = evaluate(des.DES_009, clean_raw_spec)

    assert finding is not None
    assert finding.evidence["reasons"] == ["allocation_too_unequal"]
    assert "daily_eligible_units_for_even_arrivals" not in finding.evidence


@pytest.mark.parametrize("unit", ["session", "cluster"])
def test_des_009_fires_for_units_the_cohort_check_refuses_however_many_players(
    clean_raw_spec: dict, unit: str
) -> None:
    finding = evaluate(des.DES_009, clean_raw_spec, population__analysis_unit=unit)

    assert finding is not None
    assert finding.evidence["reasons"] == ["unit_not_independent"]
    assert finding.evidence["analysis_unit"] == unit and finding.evidence["comparisons"] == []
    assert "daily_eligible_units_for_even_arrivals" not in finding.evidence


def test_a_fourteen_day_plan_gets_only_the_info_finding_and_still_proceeds(
    clean_raw_spec: dict,
) -> None:
    clean_raw_spec["design"]["planned_duration_days"] = 14

    review = review_design(ExperimentSpec.from_dict(clean_raw_spec))

    assert [f.rule_id for f in review.findings] == ["DES-009"]
    assert review.recommendation == "proceed" and review.blocking_rule_ids == ()


def test_the_numbers_in_the_rule_text_are_the_ones_the_cohort_check_uses() -> None:
    text = " ".join(des.DES_009.fires_when.split())
    least = cohorts.MIN_COHORTS * cohorts.WEEK_DAYS

    for phrase in (
        f"fewer than {cohorts.MIN_COHORTS} whole weekly blocks",
        f"design.planned_duration_days is {least - 1} or less",
        f"floor of {cohorts.FLOOR} players",
        f"more than {cohorts.RATIO_FLOOR_KNEE} to 1",
        f"median of {cohorts.WEEKLY_MEDIAN_MINIMUM} players",
        f"a plan of {cohorts.FALLBACK_MIN_PLAN_DAYS} days or more",
        f"blocks of {cohorts.FALLBACK_BLOCK_DAYS} days",
        f"more than {cohorts.MAX_ALLOCATION_RATIO:.0f} to 1",
    ):
        assert phrase in text, phrase
    assert f"plan at least {least} days" in des.DES_009.remediation


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
        "DES-009",
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


@pytest.mark.parametrize("kind", ["new_users", "existing_users", "mixed"])
def test_des_008_is_not_suppressed_by_a_declared_population_kind(
    clean_raw_spec: dict, kind: str
) -> None:
    finding = evaluate(
        des.DES_008, clean_raw_spec, design__pre_period_covariate=None, population__kind=kind
    )

    assert finding is not None
