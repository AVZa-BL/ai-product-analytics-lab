"""What a review says: a `Finding` per problem, and a review that orders them.

Referee is advisory. A review never decides anything; it lists what a rule found, which of
those findings block, and a conclusion that follows mechanically from them. A `DesignReview`
of a spec recommends `revise` if any finding blocks and `proceed` otherwise. A `ResultsReview`
of a spec and its data gives the verdict `invalid`, `caution` or `clear`. The same input always
yields the same review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Severity = Literal["blocker", "warning", "info"]
Recommendation = Literal["revise", "proceed"]
Verdict = Literal["invalid", "caution", "clear"]

# Most serious first, so sorting by rank puts blockers at the top of a report.
_SEVERITY_RANK: dict[str, int] = {"blocker": 0, "warning": 1, "info": 2}
_RULE_ID = re.compile(r"[A-Z]{3}-[0-9]{3}")


def is_more_serious(severity: str, than: str) -> bool:
    """Whether `severity` is more serious than `than` (a blocker over a warning over info)."""
    for name in (severity, than):
        if name not in _SEVERITY_RANK:
            raise ValueError(f"severity must be one of {sorted(_SEVERITY_RANK)}, got {name!r}")
    return _SEVERITY_RANK[severity] < _SEVERITY_RANK[than]


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


@dataclass(frozen=True, kw_only=True)
class Finding:
    """One thing a rule found wrong with a spec.

    `evidence` holds the numbers that triggered the rule. It is excluded from hashing because
    a dict cannot be hashed; it still takes part in equality.
    """

    rule_id: str
    severity: Severity
    title: str
    evidence: dict[str, Any] = field(hash=False)
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        # Rules are written by us, so a malformed finding is a bug to surface at once.
        if not isinstance(self.rule_id, str) or not _RULE_ID.fullmatch(self.rule_id):
            raise ValueError(f"rule_id must look like 'DES-001', got {self.rule_id!r}")
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


def _in_report_order(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Findings sorted by severity, then rule ID; a rule may appear once."""
    ordered = tuple(sorted(findings, key=lambda f: (_SEVERITY_RANK[f.severity], f.rule_id)))
    ids = [finding.rule_id for finding in ordered]
    repeated = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
    if repeated:
        raise ValueError(f"a rule may raise one finding at most; repeated: {repeated}")
    return ordered


@dataclass(frozen=True, kw_only=True)
class DesignReview:
    """The outcome of reviewing one spec's design.

    Findings are stored sorted by severity, then rule ID, whatever order they arrive in, so a
    report never depends on the order rules ran. A rule contributes at most one finding.
    """

    spec_id: str
    findings: tuple[Finding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", _in_report_order(self.findings))

    @property
    def blocking_rule_ids(self) -> tuple[str, ...]:
        return tuple(f.rule_id for f in self.findings if f.severity == "blocker")

    @property
    def recommendation(self) -> Recommendation:
        return "revise" if self.blocking_rule_ids else "proceed"


@dataclass(frozen=True, kw_only=True)
class ResultsReview:
    """The outcome of reviewing one experiment's data against its spec.

    The verdict follows mechanically from the findings: `invalid` if any finding blocks,
    `caution` if any is a warning, `clear` otherwise. The words differ from the design
    review's on purpose: `clear` says that the rules which ran found nothing, not that the
    effect is real. `rules_run` lists those rules, so that a verdict can always be read
    together with what was checked; a finding from a rule that did not run is a bug.

    `origin` is the instant weeks were counted from (`design.start_utc`, else the first
    assignment) and `ignored_before_start` the players assigned before it, who are in no
    count: a verdict is read together with how many players it left out.
    """

    spec_id: str
    experiment_id: str
    rules_run: tuple[str, ...]
    findings: tuple[Finding, ...]
    origin: datetime | None = None
    ignored_before_start: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        repeated = sorted({r for r in self.rules_run if self.rules_run.count(r) > 1})
        if repeated:
            raise ValueError(f"a rule may run once at most; repeated: {repeated}")
        stray = sorted({f.rule_id for f in self.findings} - set(self.rules_run))
        if stray:
            raise ValueError(f"findings from rules that did not run: {stray}")
        object.__setattr__(self, "rules_run", tuple(sorted(self.rules_run)))
        object.__setattr__(self, "findings", _in_report_order(self.findings))

    @property
    def blocking_rule_ids(self) -> tuple[str, ...]:
        return tuple(f.rule_id for f in self.findings if f.severity == "blocker")

    @property
    def verdict(self) -> Verdict:
        severities = {f.severity for f in self.findings}
        if "blocker" in severities:
            return "invalid"
        return "caution" if "warning" in severities else "clear"
