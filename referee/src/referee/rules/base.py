"""What a rule is, and what it is given to look at.

A rule is data plus one function. The data (ID, severity, title, when it fires, why it matters,
how to fix it, references) never changes between runs, which is what lets the rule
documentation be generated from the rules themselves. The function looks at a `ReviewContext`
and returns the evidence that triggered the rule, or None when the spec is fine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from referee.findings import Finding, Severity
from referee.power import PowerError, PowerPlan, plan_power, power_alpha_adjustment
from referee.spec import ExperimentSpec


@dataclass(frozen=True, kw_only=True)
class ReviewContext:
    """Everything a rule may read. Rules never modify it.

    The power plan is worked out once, here, because several rules read it. If the design
    cannot be sized at all (a target effect that cannot exist), `plan` is None and
    `power_error` says why; exactly one of the two is set.
    """

    spec: ExperimentSpec
    plan: PowerPlan | None
    power_error: str | None

    @classmethod
    def of(cls, spec: ExperimentSpec) -> ReviewContext:
        try:
            plan = plan_power(spec, alpha_adjustment=power_alpha_adjustment(spec))
        except PowerError as error:
            return cls(spec=spec, plan=None, power_error=str(error))
        return cls(spec=spec, plan=plan, power_error=None)


type Check[Context] = Callable[[Context], dict[str, Any] | None]


@dataclass(frozen=True, kw_only=True)
class Rule[Context]:
    """A rule over some context: a `ReviewContext` for the design review, a `ResultsContext`
    (see `referee.results`) for the results review."""

    id: str
    severity: Severity
    title: str
    fires_when: str
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]
    check: Check[Context]

    def __post_init__(self) -> None:
        # Build a throwaway finding so a malformed rule fails when it is defined, not the
        # first time a spec happens to trigger it.
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

    def evaluate(self, context: Context) -> Finding | None:
        evidence = self.check(context)
        return None if evidence is None else self.finding(evidence)
