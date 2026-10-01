"""The rule catalogue. `ALL_RULES` is the single list the review runs."""

from referee.rules.base import ReviewContext, Rule
from referee.rules.design import DESIGN_RULES
from referee.rules.hypothesis import HYPOTHESIS_RULES
from referee.rules.procedure import PROCEDURE_RULES

ALL_RULES: tuple[Rule, ...] = (*HYPOTHESIS_RULES, *DESIGN_RULES, *PROCEDURE_RULES)

__all__ = [
    "ALL_RULES",
    "DESIGN_RULES",
    "HYPOTHESIS_RULES",
    "PROCEDURE_RULES",
    "ReviewContext",
    "Rule",
]
