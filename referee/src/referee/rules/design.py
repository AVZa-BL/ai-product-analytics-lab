"""Rules about how the experiment is sized and laid out (DES)."""

from __future__ import annotations

import math
from typing import Any

from referee.rules.base import ReviewContext, Rule
from referee.rules.references import DENG_ET_AL_2013, DUNNETT_1955, KOHAVI_TANG_XU_2020
from referee.spec import ALLOCATION_TOLERANCE

DAYS_PER_WEEK = 7
MIN_DURATION_DAYS = 14
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


def _too_short(context: ReviewContext) -> dict[str, Any] | None:
    days = context.spec.design.planned_duration_days
    if days >= MIN_DURATION_DAYS:
        return None
    return {"planned_duration_days": days, "recommended_minimum_days": MIN_DURATION_DAYS}


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

DESIGN_RULES = (DES_001, DES_002, DES_003, DES_004, DES_005, DES_006, DES_007, DES_008)
