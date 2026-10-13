"""The rule catalogue.

`ALL_RULES` is the list the design review runs, over a spec. `RESULTS_RULES` is the list the
results review runs, over a spec and its data. `CATALOGUE` is both, in the order the
documentation prints them.
"""

from referee.rules.base import Escalation, ReviewContext, Rule
from referee.rules.design import DESIGN_RULES
from referee.rules.hypothesis import HYPOTHESIS_RULES
from referee.rules.procedure import PROCEDURE_RULES
from referee.rules.results import RESULTS_RULES

ALL_RULES: tuple[Rule, ...] = (*HYPOTHESIS_RULES, *DESIGN_RULES, *PROCEDURE_RULES)

# Every rule, for the documentation: the design rules, then the results rules.
CATALOGUE: tuple[Rule, ...] = (*ALL_RULES, *RESULTS_RULES)

__all__ = [
    "ALL_RULES",
    "CATALOGUE",
    "Escalation",
    "DESIGN_RULES",
    "HYPOTHESIS_RULES",
    "PROCEDURE_RULES",
    "RESULTS_RULES",
    "ReviewContext",
    "Rule",
]
