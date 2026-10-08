"""Run the rules over a plan."""

from __future__ import annotations

from collections.abc import Sequence

from linesman.findings import PlanReview
from linesman.plan import TrackingPlan
from linesman.rules import ALL_RULES, Rule


def review_plan(plan: TrackingPlan, *, rules: Sequence[Rule] = ALL_RULES) -> PlanReview:
    """Review a valid plan. Same plan in, same review out."""
    findings = [f for rule in rules if (f := rule.evaluate(plan)) is not None]
    return PlanReview(plan_id=plan.id, findings=tuple(findings))
