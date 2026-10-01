"""Helpers shared by the rule test modules."""

import copy
import functools

from referee.findings import Finding
from referee.rules import ReviewContext, Rule
from referee.spec import ExperimentSpec


def _set(raw: dict, dotted: str, value: object) -> None:
    *parents, leaf = dotted.split(".")
    node = functools.reduce(lambda part, key: part.setdefault(key, {}), parents, raw)
    node[leaf] = value


def evaluate(rule: Rule, raw: dict, **changes: object) -> Finding | None:
    """Apply `changes` to a copy of `raw`, then run one rule on the resulting spec.

    A change is `section__field=value`; a double underscore stands for the dot.
    """
    raw = copy.deepcopy(raw)
    for dotted, value in changes.items():
        _set(raw, dotted.replace("__", "."), value)
    return rule.evaluate(ReviewContext.of(ExperimentSpec.from_dict(raw)))
