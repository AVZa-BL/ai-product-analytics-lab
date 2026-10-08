"""What a rule is.

A rule is data plus one function. The data (ID, severity, title, when it fires, why it matters,
how to fix it, references) never changes between runs, which is what lets the rule
documentation be generated from the rules themselves. The function looks at a validated
`TrackingPlan` and returns the evidence that triggered the rule, or None when the plan is fine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from linesman.findings import Finding, Severity
from linesman.plan import TrackingPlan

Check = Callable[[TrackingPlan], dict[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class Rule:
    id: str
    severity: Severity
    title: str
    fires_when: str
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]
    check: Check

    def __post_init__(self) -> None:
        # Build a throwaway finding so a malformed rule fails when it is defined, not the
        # first time a plan happens to trigger it.
        self.finding({})
        if not isinstance(self.fires_when, str) or not self.fires_when.strip():
            raise ValueError(f"fires_when must be a non-empty string, got {self.fires_when!r}")

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

    def evaluate(self, plan: TrackingPlan) -> Finding | None:
        evidence = self.check(plan)
        return None if evidence is None else self.finding(evidence)
