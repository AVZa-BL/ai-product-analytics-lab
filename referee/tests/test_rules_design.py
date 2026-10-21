"""DES rules, each fired and not fired (design section 8, amendment 2 section 17.3)."""

import pytest
from rule_helpers import evaluate

from referee import cohorts
from referee.review import review_design
from referee.rules import design as des
from referee.spec import ExperimentSpec

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


@pytest.mark.parametrize(("days", "next_weeks"), [(10, 14)])
def test_des_002_fires_otherwise_and_names_the_next_whole_week(
    clean_raw_spec: dict, days: int, next_weeks: int
) -> None:
    finding = evaluate(
        des.DES_002, clean_raw_spec, design__planned_duration_days=days, design__min_duration_days=1
    )

    assert finding is not None
    assert finding.evidence == {"planned_duration_days": days, "next_whole_weeks_days": next_weeks}


# --- DES-003 ---------------------------------------------------------------------------


@pytest.mark.parametrize("days", [13])
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


# --- DES-005 ---------------------------------------------------------------------------


@pytest.fixture
def three_arm_spec(clean_raw_spec: dict) -> dict:
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "b", "allocation": 0.3},
        {"name": "c", "allocation": 0.3},
    ]
    return clean_raw_spec


@pytest.mark.parametrize("adjustment", ["none"], ids=["explicit none"])
def test_des_005_fires_for_three_arms_without_an_adjustment(
    three_arm_spec: dict, adjustment: str | None
) -> None:
    finding = evaluate(des.DES_005, three_arm_spec, design__alpha_adjustment=adjustment)

    assert finding is not None
    assert finding.evidence == {"arms": 3, "comparisons": 2, "alpha_adjustment": adjustment}


# --- DES-006 ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["user"])
@pytest.mark.parametrize("interference", ["possible"], ids=["possible"])
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


@pytest.mark.parametrize("unit", ["cluster"])
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
