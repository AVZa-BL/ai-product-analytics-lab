"""What a rule is, and what it is given to look at.

A rule is data plus one function. The data (ID, severity, title, why it matters, how to fix
it, references) never changes between runs, which is what lets the rule documentation be
generated from the rules themselves. The function looks at a `ReviewContext` and returns the
evidence that triggered the rule, or None when the spec is fine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from referee.findings import Finding, Severity
from referee.spec import ExperimentSpec


@dataclass(frozen=True, kw_only=True)
class ReviewContext:
    """Everything a rule may read. Rules never modify it."""

    spec: ExperimentSpec


Check = Callable[[ReviewContext], dict[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class Rule:
    id: str
    severity: Severity
    title: str
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]
    check: Check

    def __post_init__(self) -> None:
        # Build a throwaway finding so a malformed rule fails when it is defined, not the
        # first time a spec happens to trigger it.
        self.finding({})

    def finding(self, evidence: dict[str, Any]) -> Finding:
        return Finding(
            rule_id=self.id,
            severity=self.severity,
            title=self.title,
            evidence=evidence,
            why_it_matters=self.why_it_matters,
            remediation=self.remediation,
            references=self.references,
        )

    def evaluate(self, context: ReviewContext) -> Finding | None:
        evidence = self.check(context)
        return None if evidence is None else self.finding(evidence)
