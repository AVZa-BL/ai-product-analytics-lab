"""Rules about how the experiment is sized and laid out (DES)."""

from __future__ import annotations

import math
from typing import Any

from referee.cohorts import FALLBACK_BLOCK_DAYS, FALLBACK_MIN_PLAN_DAYS, MIN_COHORTS
from referee.rules.base import ReviewContext, Rule
from referee.rules.references import DENG_ET_AL_2013, DUNNETT_1955, KOHAVI_TANG_XU_2020
from referee.spec import ALLOCATION_TOLERANCE

DAYS_PER_WEEK = 7
MIN_DURATION_DAYS = 14
OUTCOME_WINDOW_DAYS = 7  # each player's outcome totals cover the seven days after assignment
WEEKLY_COHORTS_FOR_NEW_USERS = 4  # the cohorts the note on new users counts on (section 21.8)
# Players a block is expected to hold in the smallest arm, below which the cohort check (RES-007)
# will probably not find three blocks of 30. Judgement (section 21.9): half as many again as the
# floor of 30, so that most blocks reach it.
EXPECTED_PLAYERS_PER_BLOCK = 45
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
    needed = WEEKLY_COHORTS_FOR_NEW_USERS * DAYS_PER_WEEK
    return (
        "population.kind is new_users: design.planned_duration_days is the accrual window, the "
        "days in which new players are assigned. Each player's outcome window of "
        f"{OUTCOME_WINDOW_DAYS} days follows that player's assignment, so the last outcomes "
        f"arrive {OUTCOME_WINDOW_DAYS} days after accrual ends, and the accrual window and the "
        "outcome window must both fit in the time available. "
        f"{WEEKLY_COHORTS_FOR_NEW_USERS} weekly cohorts of new players, which the cohort check "
        f"(RES-007) compares, need {needed} days of accrual."
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


def _cohort_check_unlikely(context: ReviewContext) -> dict[str, Any] | None:
    """The plan holds too few weekly blocks, or the smallest arm too few players in a block, for
    the cohort check (RES-007) to find three blocks of 30 (design section 21.8)."""
    spec = context.spec
    days = spec.design.planned_duration_days
    daily = spec.population.daily_eligible_units
    smallest = min(spec.arms, key=lambda arm: arm.allocation)
    # RES-007 falls back to 14-day blocks on a plan of 42 days or more (section 21.5).
    block_days = FALLBACK_BLOCK_DAYS if days >= FALLBACK_MIN_PLAN_DAYS else DAYS_PER_WEEK
    expected = block_days * daily * smallest.allocation
    weekly_blocks = days // DAYS_PER_WEEK
    reasons = []
    if weekly_blocks < MIN_COHORTS:
        reasons.append("window_holds_fewer_than_3_blocks")
    if expected < EXPECTED_PLAYERS_PER_BLOCK:
        reasons.append("too_few_players_in_a_block")
    if not reasons:
        return None
    evidence: dict[str, Any] = {
        "reasons": reasons,
        "planned_duration_days": days,
        "whole_weekly_blocks": weekly_blocks,
        "minimum_weekly_blocks": MIN_COHORTS,
        "block_days": block_days,
        "daily_eligible_units": daily,
        "smallest_arm": smallest.name,
        "smallest_allocation": smallest.allocation,
        "expected_players_per_block": round(expected, _EFFECT_DIGITS),
        "minimum_expected_players": EXPECTED_PLAYERS_PER_BLOCK,
    }
    if "window_holds_fewer_than_3_blocks" in reasons:
        evidence["minimum_planned_days"] = MIN_COHORTS * DAYS_PER_WEEK
    if "too_few_players_in_a_block" in reasons:
        evidence["daily_eligible_units_needed"] = math.ceil(
            EXPECTED_PLAYERS_PER_BLOCK / (block_days * smallest.allocation)
        )
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
        "the estimate."
    ),
    remediation=(
        "Declare design.pre_period_covariate, for example the primary metric measured for each "
        "unit before exposure."
    ),
    references=(DENG_ET_AL_2013,),
    check=_no_covariate,
)

DES_009 = Rule(
    id="DES-009",
    severity="info",
    title="The cohort check of the results review will probably not run",
    fires_when=(
        "The planned window holds fewer than 3 whole weekly blocks (design.planned_duration_days "
        "is 20 or less), or the smallest arm is expected to get fewer than 45 players in a block: "
        "7 times population.daily_eligible_units times the smallest allocation for a plan "
        "shorter than 42 days, 14 times that for a plan of 42 days or more, where the cohort "
        "check can use blocks of 14 days. The evidence gives the reasons, the expected players "
        "and what would be enough."
    ),
    why_it_matters=(
        "After the experiment, the cohort check of the results review (RES-007) compares an "
        "arm's effect between cohorts of first exposure, to find an effect that changes with "
        "the time players joined (a launch, a promotion, a change in who is acquired). It "
        "works in blocks of 7 days, or of 14 days on a plan of 42 days or more, and needs 3 "
        "blocks in which both arms reach 30 players, with a usable block in each half of the "
        "window. A plan with fewer than 3 whole weekly blocks cannot form them, and an arm "
        "expected to hold fewer than 45 players in a block seldom fills 3 to 30. The check "
        "will then probably report that it could not run, and an effect that changes over time "
        "would go unseen. This is a forecast from the plan, not a finding about the data."
    ),
    remediation=(
        "If the effect over time matters for this change, plan at least 21 days (42 days or more "
        "allows blocks of 14 days, which need fewer players a week), bring in more "
        "eligible units each day, or give the smallest arm a larger share; the evidence says what "
        "would be enough. Otherwise accept that the cohort check will probably "
        "not run. The other results checks are not affected."
    ),
    references=(),
    check=_cohort_check_unlikely,
)

DESIGN_RULES = (DES_001, DES_002, DES_003, DES_004, DES_005, DES_006, DES_007, DES_008, DES_009)
