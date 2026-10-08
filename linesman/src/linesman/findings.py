"""What a review says: a `Finding` per problem, and a `PlanReview` that orders them.

Linesman is advisory. A review never blocks a release by itself; it lists what a rule found,
which of those findings block, and a recommendation that follows mechanically: `revise` if any
finding blocks, `proceed` otherwise. The same plan always yields the same review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["blocker", "warning", "info"]
Recommendation = Literal["revise", "proceed"]

_SEVERITY_RANK: dict[str, int] = {"blocker": 0, "warning": 1, "info": 2}
_RULE_ID = re.compile(r"[A-Z]{3}-[0-9]{3}")


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


@dataclass(frozen=True, kw_only=True)
class Finding:
    """One thing a rule found wrong with a plan. `evidence` holds what triggered the rule."""

    rule_id: str
    severity: Severity
    title: str
    evidence: dict[str, Any] = field(hash=False)
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID.fullmatch(self.rule_id):
            raise ValueError(f"rule_id must look like 'SCH-001', got {self.rule_id!r}")
        if self.severity not in _SEVERITY_RANK:
            raise ValueError(
                f"severity must be one of {sorted(_SEVERITY_RANK)}, got {self.severity!r}"
            )
        _require_text("title", self.title)
        _require_text("why_it_matters", self.why_it_matters)
        _require_text("remediation", self.remediation)
        if not isinstance(self.references, tuple) or not all(
            isinstance(reference, str) for reference in self.references
        ):
            raise ValueError(f"references must be a tuple of strings, got {self.references!r}")


@dataclass(frozen=True, kw_only=True)
class PlanReview:
    """The outcome of reviewing one plan. Findings are sorted by severity, then rule ID."""

    plan_id: str
    findings: tuple[Finding, ...]

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(self.findings, key=lambda f: (_SEVERITY_RANK[f.severity], f.rule_id))
        )
        ids = [finding.rule_id for finding in ordered]
        repeated = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if repeated:
            raise ValueError(f"a rule may raise one finding at most; repeated: {repeated}")
        object.__setattr__(self, "findings", ordered)

    @property
    def blocking_rule_ids(self) -> tuple[str, ...]:
        return tuple(f.rule_id for f in self.findings if f.severity == "blocker")

    @property
    def recommendation(self) -> Recommendation:
        return "revise" if self.blocking_rule_ids else "proceed"
