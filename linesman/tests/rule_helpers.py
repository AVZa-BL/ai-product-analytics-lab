"""Helpers shared by the rule tests."""

import copy

from linesman.findings import Finding
from linesman.plan import TrackingPlan
from linesman.rules import ALL_RULES


def run(rule_id: str, raw: dict, edit=None) -> Finding | None:
    """Apply `edit` to a copy of `raw`, then run one rule on the resulting plan."""
    raw = copy.deepcopy(raw)
    if edit is not None:
        edit(raw)
    rule = next(rule for rule in ALL_RULES if rule.id == rule_id)
    return rule.evaluate(TrackingPlan.from_dict(raw))
