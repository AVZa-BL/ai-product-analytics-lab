"""Run the rules over a plan."""

from __future__ import annotations

from collections.abc import Sequence

from tracewright.findings import PlanReview
from tracewright.plan import TrackingPlan
from tracewright.rules import ALL_RULES, Rule


def review_plan(plan: TrackingPlan, *, rules: Sequence[Rule] = ALL_RULES) -> PlanReview:
    """Review a valid plan. Same plan in, same review out."""
    findings = [f for rule in rules if (f := rule.evaluate(plan)) is not None]
    return PlanReview(plan_id=plan.id, findings=tuple(findings))
