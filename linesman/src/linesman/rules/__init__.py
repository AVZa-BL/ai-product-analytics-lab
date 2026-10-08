"""The rule catalogue. `ALL_RULES` is the single list the review runs."""

from linesman.rules.base import Rule
from linesman.rules.catalogue import ALL_RULES

__all__ = ["ALL_RULES", "Rule"]
