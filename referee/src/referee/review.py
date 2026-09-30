"""Run the design-review rules over a spec."""

from __future__ import annotations

from collections.abc import Sequence

from referee.findings import DesignReview
from referee.rules import ALL_RULES, ReviewContext, Rule
from referee.spec import ExperimentSpec


def review_design(spec: ExperimentSpec, *, rules: Sequence[Rule] = ALL_RULES) -> DesignReview:
    """Review a valid spec's design. Same spec in, same review out."""
    context = ReviewContext(spec=spec)
    findings = [f for rule in rules if (f := rule.evaluate(context)) is not None]
    return DesignReview(spec_id=spec.id, findings=tuple(findings))
