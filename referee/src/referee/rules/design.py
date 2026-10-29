"""Rules about how the experiment is sized and laid out (DES)."""

from __future__ import annotations

import math
from typing import Any

from referee.cohorts import MIN_COHORTS, forecast_reason, population_units_independent
from referee.rules.base import ReviewContext, Rule
from referee.rules.references import DENG_ET_AL_2013, DUNNETT_1955, KOHAVI_TANG_XU_2020
from referee.spec import ALLOCATION_TOLERANCE

DAYS_PER_WEEK = 7
MIN_DURATION_DAYS = 14
OUTCOME_WINDOW_DAYS = 7  # each player's outcome totals cover the seven days after assignment
# The cohorts the note on new users counts on (section 21.8): the fewest the cohort check can
# compare, and one more because the last week's outcome windows are still open when accrual ends.
WEEKLY_COHORTS_FOR_NEW_USERS = MIN_COHORTS + 1
_EFFECT_DIGITS = 4


def _underpowered(context: ReviewContext) -> dict[str, Any] | None:
    design = context.spec.design
    plan = context.plan
    if plan is None:
        return {
            "unattainable": True,
            "reason": context.power_error,
            "requested_mde_relative": design.mde_relative,
        }
    if plan.is_powered:
        return None
    achievable = plan.achievable_mde_relative
    return {
        "required_total": plan.required_total,
        "achievable_total": plan.achievable_total,
        "required_days": plan.required_days,
        "required_days_whole_weeks": plan.required_days_whole_weeks,
        "planned_duration_days": design.planned_duration_days,
        "requested_mde_relative": design.mde_relative,
        "achievable_mde_relative": None
        if achievable is None
        else round(achievable, _EFFECT_DIGITS),
    }


def _not_whole_weeks(context: ReviewContext) -> dict[str, Any] | None:
    days = context.spec.design.planned_duration_days
    if days % DAYS_PER_WEEK == 0:
        return None
    return {
        "planned_duration_days": days,
        "next_whole_weeks_days": math.ceil(days / DAYS_PER_WEEK) * DAYS_PER_WEEK,
    }


def _new_users_note() -> str:
    least = MIN_COHORTS * DAYS_PER_WEEK
    more = WEEKLY_COHORTS_FOR_NEW_USERS * DAYS_PER_WEEK
    return (
        "population.kind is new_users: design.planned_duration_days is the accrual window, the "
        "days in which new players are assigned. Each player's outcome window of "
        f"{OUTCOME_WINDOW_DAYS} days follows that player's assignment, so the last outcomes "
        f"arrive {OUTCOME_WINDOW_DAYS} days after accrual ends, and the accrual window and the "
        "outcome window must both fit in the time available. The cohort check (RES-007) needs "
        f"{MIN_COHORTS} weekly cohorts of new players, which is {least} days of accrual; "
        f"{WEEKLY_COHORTS_FOR_NEW_USERS} weekly cohorts, {more} days, if the export is taken "
        "when accrual ends, because the outcome windows of the last week are still open then "
        "and that cohort is left out."
    )


def _too_short(context: ReviewContext) -> dict[str, Any] | None:
    spec = context.spec
    days = spec.design.planned_duration_days
    if days >= MIN_DURATION_DAYS:
        return None
    evidence: dict[str, Any] = {
        "planned_duration_days": days,
        "recommended_minimum_days": MIN_DURATION_DAYS,
    }
    if spec.population.kind == "new_users":
        evidence["population_kind"] = "new_users"
        evidence["note"] = _new_users_note()
    return evidence


def _forecast(days: int, daily: int, arm_share: float, control_share: float) -> str | None:
    ratio = round(max(arm_share, control_share) / min(arm_share, control_share), 9)
    return forecast_reason(
        planned_days=days,
        arm_per_week=DAYS_PER_WEEK * daily * arm_share,
        control_per_week=DAYS_PER_WEEK * daily * control_share,
        ratio=ratio,
    )


def _daily_units_that_pass(days: int, daily: int, arm_share: float, control_share: float) -> int:
    """The fewest daily eligible units, at least `daily`, at which an even-arrival plan of
    `days` passes the cohort gates for this arm. The arms must be within 9:1 and the window
    must hold 3 weekly blocks, which the caller sees to; more players then only help, so the
    answer is found by doubling and then halving."""
    low, high = daily, daily
    while _forecast(days, high, arm_share, control_share) is not None:
        low, high = high, high * 2
    while high - low > 1:
        middle = (low + high) // 2
        if _forecast(days, middle, arm_share, control_share) is None:
            high = middle
        else:
            low = middle
    return high


def _cohort_check_unlikely(context: ReviewContext) -> dict[str, Any] | None:
    """The cohort check (RES-007) would not run on this plan even if players arrived evenly:
    the gates of `plan_cohorts` applied to the expected players (design section 21.13)."""
    spec = context.spec
    days = spec.design.planned_duration_days
    daily = spec.population.daily_eligible_units
    control = next(arm for arm in spec.arms if arm.is_control)
    versus = [arm for arm in spec.arms if not arm.is_control]
    weekly = DAYS_PER_WEEK * daily
    limited = []
    for arm in versus:
        reason = _forecast(days, daily, arm.allocation, control.allocation)
        if reason is not None:
            smaller, larger = sorted((arm.allocation, control.allocation))
            limited.append(
                {
                    "arm": arm.name,
                    "reason": reason,
                    "allocation_ratio": round(larger / smaller, _EFFECT_DIGITS),
                    "expected_players_per_week": {
                        "arm": round(weekly * arm.allocation, _EFFECT_DIGITS),
                        "control": round(weekly * control.allocation, _EFFECT_DIGITS),
                    },
                }
            )
    units_ok = population_units_independent(spec.population)
    if not limited and units_ok:
        return None
    evidence: dict[str, Any] = {
        "reasons": sorted(
            {item["reason"] for item in limited} | (set() if units_ok else {"unit_not_independent"})
        ),
        "planned_duration_days": days,
        "whole_weekly_blocks": days // DAYS_PER_WEEK,
        "minimum_weekly_blocks": MIN_COHORTS,
        "daily_eligible_units": daily,
        "arms_checked": len(versus),
        "comparisons": limited,
    }
    if not units_ok:
        evidence["randomization_unit"] = spec.population.randomization_unit
        evidence["analysis_unit"] = spec.population.analysis_unit
    if any(item["reason"] == "window_holds_fewer_than_3_blocks" for item in limited):
        evidence["minimum_planned_days"] = MIN_COHORTS * DAYS_PER_WEEK
    # More daily units help wherever the arms are within 9:1; a plan that is too short is priced
    # at the shortest window the check accepts.
    window = max(days, MIN_COHORTS * DAYS_PER_WEEK)
    by_name = {arm.name: arm for arm in versus}
    prices = [
        _daily_units_that_pass(window, daily, by_name[item["arm"]].allocation, control.allocation)
        for item in limited
        if item["reason"] != "allocation_too_unequal"
    ]
    if prices:
        evidence["daily_eligible_units_for_even_arrivals"] = max(prices)
    return evidence


def _unequal_allocation(context: ReviewContext) -> dict[str, Any] | None:
    arms = context.spec.arms
    equal = 1 / len(arms)
    if all(abs(arm.allocation - equal) <= ALLOCATION_TOLERANCE for arm in arms):
        return None
    plan = context.plan
    extra = None if plan is None else round(plan.extra_units_vs_equal_split, _EFFECT_DIGITS)
    return {
        "allocations": {arm.name: arm.allocation for arm in arms},
        "extra_units_vs_equal_split": extra,
    }


def _no_alpha_adjustment(context: ReviewContext) -> dict[str, Any] | None:
    spec = context.spec
    if len(spec.arms) <= 2 or spec.design.alpha_adjustment not in (None, "none"):
        return None
    return {
        "arms": len(spec.arms),
        "comparisons": len(spec.arms) - 1,
        "alpha_adjustment": spec.design.alpha_adjustment,
    }


def _possible_interference(context: ReviewContext) -> dict[str, Any] | None:
    population = context.spec.population
    if population.randomization_unit not in ("player", "user"):
        return None
    if population.interference == "none_expected":
        return None
    return {
        "randomization_unit": population.randomization_unit,
        "interference": population.interference,
    }


def _post_treatment_exposure(context: ReviewContext) -> dict[str, Any] | None:
    population = context.spec.population
    if population.exposure_timing != "post_treatment":
        return None
    return {
        "exposure_timing": population.exposure_timing,
        "exposure_trigger": population.exposure_trigger,
    }


def _no_covariate(context: ReviewContext) -> dict[str, Any] | None:
    if context.spec.design.pre_period_covariate is not None:
        return None
    return {"field": "design.pre_period_covariate", "value": None}


DES_001 = Rule(
    id="DES-001",
    severity="blocker",
    title="Design cannot reach the planned power",
    fires_when=(
        "The sample the design needs, at its alpha, power and target effect, is larger than "
        "the units the planned duration delivers (daily_eligible_units times "
        "planned_duration_days), or the target effect cannot exist, for example a rate above "
        "1 after the relative lift."
    ),
    why_it_matters=(
        "With too few units a real effect of the planned size is likely to be missed, and a "
        "result of no significant difference then says little. If the target effect cannot "
        "exist at all, for example a rate above 1 after the relative lift, no sample size "
        "can reach it."
    ),
    remediation=(
        "Run for the required days, bring in more eligible units, accept the larger minimum "
        "detectable effect the evidence reports, or choose a target effect that can exist."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_underpowered,
)

DES_002 = Rule(
    id="DES-002",
    severity="warning",
    title="Planned duration is not a whole number of weeks",
    fires_when="design.planned_duration_days is not a multiple of 7.",
    why_it_matters=(
        "Behaviour and treatment effects can differ by day of the week. A test that covers "
        "some weekdays more often than others estimates an effect weighted towards those "
        "days, which may differ from the effect over a typical week."
    ),
    remediation="Round the planned duration up to a whole number of weeks.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_not_whole_weeks,
)

DES_003 = Rule(
    id="DES-003",
    severity="warning",
    title="Planned duration is under 14 days",
    fires_when=(
        "design.planned_duration_days is below 14. When population.kind is new_users, the "
        "evidence adds a note on the accrual window and the 7-day outcome window."
    ),
    why_it_matters=(
        "Effects can be larger or smaller in the first days after a change than later, as "
        "users react to novelty or adapt to it. A short test cannot show which, so it may "
        "report an effect that does not last."
    ),
    remediation=(
        "Plan at least 14 days, or record why novelty and primacy effects are not expected "
        "for this change."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_too_short,
)

DES_004 = Rule(
    id="DES-004",
    severity="info",
    title="Allocation is not an equal split",
    fires_when=(
        "The arm allocations are not all equal, to within 1e-9. The evidence gives the extra "
        "units this allocation needs over an equal split; a negative value means it needs "
        "fewer."
    ),
    why_it_matters=(
        "For the same power, an unequal split usually needs more units than an equal one. "
        "The evidence states the difference for this allocation; a negative value means this "
        "split needs fewer units."
    ),
    remediation=(
        "Keep the split if there is a reason for it, such as limiting exposure to a risky "
        "variant, and budget the extra units; otherwise use an equal split."
    ),
    references=(),
    check=_unequal_allocation,
)

DES_005 = Rule(
    id="DES-005",
    severity="warning",
    title="More than two arms without an alpha adjustment",
    fires_when="There are more than two arms and design.alpha_adjustment is absent or none.",
    why_it_matters=(
        "Each extra variant adds a comparison against control, and each comparison is another "
        "chance of a false positive, so the chance of at least one across the experiment "
        "exceeds alpha. The sample size here assumes Bonferroni unless none is declared."
    ),
    remediation=(
        "Declare design.alpha_adjustment: bonferroni (simple, slightly conservative) or "
        "dunnett (less conservative when every variant is compared with control)."
    ),
    references=(DUNNETT_1955,),
    check=_no_alpha_adjustment,
)

DES_006 = Rule(
    id="DES-006",
    severity="warning",
    title="Interference between units is possible",
    fires_when=(
        "population.randomization_unit is player or user, and population.interference is "
        "absent or possible."
    ),
    why_it_matters=(
        "If one player's treatment can change another's behaviour, as with social or "
        "multiplayer features, units are not independent and the measured effect can be "
        "biased."
    ),
    remediation=(
        "Randomize at a level that contains the interaction (clusters of players), or set "
        "population.interference to none_expected and record why."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_possible_interference,
)

DES_007 = Rule(
    id="DES-007",
    severity="blocker",
    title="Exposure is recorded after the treatment starts acting",
    fires_when="population.exposure_timing is post_treatment.",
    why_it_matters=(
        "If units enter the analysis only after the treatment may have influenced whether "
        "they are exposed, the arms stop being comparable and the result is biased, however "
        "large the sample."
    ),
    remediation=(
        "Trigger exposure from an event that happens before the treatment can act, and log "
        "it the same way in every arm, including control."
    ),
    references=(),
    check=_post_treatment_exposure,
)

DES_008 = Rule(
    id="DES-008",
    severity="warning",
    title="No pre-period covariate declared",
    fires_when="design.pre_period_covariate is absent.",
    why_it_matters=(
        "A covariate measured before the experiment lets the analysis remove variance that "
        "has nothing to do with the treatment (CUPED), which can shorten the test or sharpen "
        "the estimate. How much depends on how well the covariate predicts the outcome: with a "
        "correlation of 0.7 about half of the variance goes, with 0.3 about a tenth, and with "
        "none the adjustment changes nothing."
    ),
    remediation=(
        "Declare design.pre_period_covariate: the name of a column of the experiment's outcomes "
        "file that holds, for each player, a measure taken before the player's first exposure, "
        "for example the primary metric over the week before. The results review then shows the "
        "adjusted estimate, which is the registered analysis, beside the unadjusted one, and "
        "checks that the covariate is balanced across the arms. A measure taken after the "
        "treatment can act would remove part of the real effect."
    ),
    references=(DENG_ET_AL_2013,),
    check=_no_covariate,
)

DES_009 = Rule(
    id="DES-009",
    severity="info",
    title="The cohort check of the results review would not run on this plan",
    fires_when=(
        "For a non-control arm against control, the plan fails a gate of the cohort check of "
        "the results review (RES-007) even if players arrive perfectly evenly: the planned "
        "window holds fewer than 3 whole weekly blocks (design.planned_duration_days is 20 or "
        "less); or the expected players of a week, 7 times population.daily_eligible_units "
        "times the arm's allocation, do not reach the floor of 30 players in the arm or in "
        "control (a floor that rises when the arms differ by more than 1.5 to 1), or, on "
        "weekly blocks, a median of 60 players in the smaller of the two, and a plan of 42 days "
        "or more does not pass on blocks of 14 days either; or the arms differ by more than "
        "9 to 1. It also fires when population.randomization_unit and population.analysis_unit "
        "are not one class of independent units (player and user, or device for both). The "
        "evidence gives the reasons, the arms concerned and what would be enough for even "
        "arrivals."
    ),
    why_it_matters=(
        "After the experiment, the cohort check of the results review (RES-007) compares each "
        "arm's effect between cohorts of first exposure, to find an effect that differs between "
        "the players who joined in different weeks (a launch, a promotion, a change in who is "
        "acquired). It does not test for novelty or adaptation: DES-003 is the rule for those. "
        "It works in blocks of 7 days, or of 14 days on a plan of 42 days or more, and the "
        "gates above are its own, applied to the plan's expected numbers. Real arrivals are "
        "less even than expected numbers, so a plan that only just passes still fails in many "
        "runs; this rule names the plans that fail even in the best case. When the check "
        "cannot run, the results review says so in a RES-007 warning and its verdict is "
        "caution, not clear. This is a forecast from the plan, not a finding about the data."
    ),
    remediation=(
        "If an effect that differs between the weeks players joined could matter for this "
        "change, plan at least 21 days (42 days or more allows blocks of 14 days, which need "
        "fewer players a week), bring in more eligible units each day or give the smaller arm "
        "a larger share, keep the arms within 9 to 1, and randomise and analyse in the same "
        "independent unit (player, user or device). The evidence gives the units a day that "
        "pass with even arrivals; allow more, because arrivals vary (design section 21.6: "
        "spiky arrivals need 1.5 to 3 times as much). Otherwise accept that the cohort check "
        "will not run: the other results checks are not affected."
    ),
    references=(),
    check=_cohort_check_unlikely,
)

DESIGN_RULES = (DES_001, DES_002, DES_003, DES_004, DES_005, DES_006, DES_007, DES_008, DES_009)
