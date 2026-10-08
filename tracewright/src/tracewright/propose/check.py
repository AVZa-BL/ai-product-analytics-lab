"""Deterministic checks on a proposal, and the merge of a proposal into a tracking plan.

The model proposes; this module decides what is wrong with the proposal, without asking the model.
A `Problem` is one finding about the proposal itself (a clash with the existing plan, a quote that
is not in the documents). Findings about the *resulting plan* come from the ordinary rules, run on
the merged plan: the ones the proposal introduced are reported, the ones the plan already had are
not blamed on it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from tracewright.findings import Finding, PlanReview
from tracewright.plan import PLAN_VERSION, VERSION_KEY, PlanError, TrackingPlan
from tracewright.propose.documents import Document
from tracewright.propose.grounding import quote_in_document
from tracewright.propose.proposal import Evidence, Proposal, ProposedProperty
from tracewright.review import review_plan

ProblemSeverity = Literal["blocker", "warning", "info"]

# Findings the model cannot clear, because the fix is a fact only the team holds or a change to
# the existing plan: who owns an event (DOC-002), or that an event the plan lists as "planned"
# has shipped (COV-003). They are reported, never sent back.
UNREPAIRABLE_RULES = frozenset({"DOC-002", "COV-003"})


# Every problem code, with what it means. docs/propose.md lists the same codes; a test keeps the
# two in step, and Problem refuses a code that is not here.
PROBLEM_CODES: dict[str, str] = {
    "DUPLICATE": "An event name appears twice in the proposal, or in more than one list.",
    "COLLISION": "A new event has the name of an event the plan already has.",
    "UNKNOWN_EVENT": "An extended or reused event is not in the existing plan.",
    "AMBIGUOUS_EVENT": "A name matches two plan events that differ only in letter case.",
    "DUPLICATE_PROPERTY": "An extended event adds a property it already has.",
    "IDENTITY": "There is no existing plan, and identity_keys or feature.id is missing.",
    "METRIC_COLLISION": "A proposed metric has the name of a metric the plan already has.",
    "EVIDENCE_DOCUMENT": "Evidence cites a document that was not provided.",
    "EVIDENCE_QUOTE": "A quote is not found in the document it is attributed to.",
    "EVIDENCE_UNVERIFIABLE": "A quote is from a PDF, which cannot be searched.",
    "REUSE_CLAIM": "A property is marked reuses_existing, but the plan has no such property.",
    "REUSE_UNFLAGGED": "A property already exists in the plan but is not marked reuses_existing.",
    "PLAN": "The merged result is not a valid tracking plan.",
}


@dataclass(frozen=True, kw_only=True)
class Problem:
    code: str
    severity: ProblemSeverity
    subject: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in PROBLEM_CODES:
            raise ValueError(f"unknown problem code {self.code!r}")


@dataclass(frozen=True, kw_only=True)
class Grounding:
    """How the proposal's evidence fared. Counts events and extended events together."""

    quoted_found: int
    quoted_missing: int
    unverifiable: int
    inferred: int
    by_event: dict[str, str]  # event name -> found | missing | unverifiable | inferred


@dataclass(frozen=True, kw_only=True)
class CheckResult:
    problems: tuple[Problem, ...]
    grounding: Grounding
    merged_plan: TrackingPlan | None  # new events marked planned: what gets written
    review: PlanReview | None  # of the merged plan viewed as shipped
    baseline_review: PlanReview | None  # of the existing plan, when there is one
    introduced: tuple[Finding, ...]  # findings the proposal is responsible for

    @property
    def blocking(self) -> bool:
        return any(p.severity == "blocker" for p in self.problems) or any(
            f.severity == "blocker" for f in self.introduced
        )


def _key(name: str) -> str:
    return name.strip().casefold()


def check_proposal(
    proposal: Proposal,
    plan: TrackingPlan | None,
    documents: Sequence[Document],
    *,
    owner: str | None = None,
) -> CheckResult:
    """Run every deterministic check. Never calls a model."""
    problems: list[Problem] = []
    structural, sanitized = _structure(proposal, plan)
    problems += structural
    grounding, evidence_problems = _check_evidence(proposal, documents)
    problems += evidence_problems
    problems += _reuse_problems(proposal, plan)

    merged: TrackingPlan | None = None
    review: PlanReview | None = None
    baseline: PlanReview | None = review_plan(plan) if plan is not None else None
    introduced: tuple[Finding, ...] = ()
    # Without identity keys there is no plan to build at all. Any other structural problem only
    # drops the offending entries from the *review* copy, so the rules still see everything else
    # and one repair round can fix every layer of problems, not just the first.
    if not any(p.code == "IDENTITY" for p in structural):
        try:
            shipped = merge(sanitized, plan, new_status="active", owner=owner)
            if not any(p.severity == "blocker" for p in structural):
                merged = merge(sanitized, plan, new_status="planned", owner=owner)
        except PlanError as error:
            problems += [
                Problem(code="PLAN", severity="blocker", subject="merged plan", message=v)
                for v in error.violations
            ]
        else:
            review = review_plan(shipped)
            old = baseline.findings if baseline else ()
            introduced = tuple(f for f in review.findings if _is_introduced(f, old))
    return CheckResult(
        problems=tuple(problems),
        grounding=grounding,
        merged_plan=merged,
        review=review,
        baseline_review=baseline,
        introduced=introduced,
    )


def _is_introduced(finding: Finding, baseline: Sequence[Finding]) -> bool:
    """Whether the proposal is responsible for this finding of the merged plan.

    A finding the plan already had, with the same evidence, is not the proposal's doing. One
    rule needs a finer test: SCH-001 lists every event of every conflicting property, so a
    proposal that merely reuses a property the plan already has in two types would change the
    evidence without making anything worse, and the model cannot repair the plan's own
    conflict. There, only a new conflicting property, or a new type on a conflicting one, counts.
    """
    same_rule = [b for b in baseline if b.rule_id == finding.rule_id]
    if finding.rule_id == "SCH-001":
        known: dict[str, set[str]] = {}
        for b in same_rule:
            for name, types in b.evidence.get("properties", {}).items():
                known.setdefault(name, set()).update(types)
        return any(
            set(types) - known.get(name, set())
            for name, types in finding.evidence.get("properties", {}).items()
        )
    return not any(b.evidence == finding.evidence for b in same_rule)


def _resolve(name: str, names: Sequence[str]) -> tuple[str | None, list[str]]:
    """Which plan event a name means: an exact match, else the one match that differs only in
    letter case. Returns (name, []) when it is clear, (None, []) when there is none, and
    (None, candidates) when two or more events differ only in case and none matches exactly."""
    if name in names:
        return name, []
    folded = [n for n in names if _key(n) == _key(name)]
    if len(folded) == 1:
        return folded[0], []
    return None, folded


def _structure(proposal: Proposal, plan: TrackingPlan | None) -> tuple[list[Problem], Proposal]:
    """Structural problems, and the proposal with the offending entries removed for review."""
    problems: list[Problem] = []
    events_by_name = {e.name: e for e in plan.events} if plan else {}
    plan_names = list(events_by_name)
    plan_keys = {_key(n) for n in plan_names}

    def blocker(code: str, subject: str, message: str) -> None:
        problems.append(Problem(code=code, severity="blocker", subject=subject, message=message))

    seen: dict[str, str] = {}
    keep_new, keep_extended, keep_reused = [], [], []
    for label, items, keep in (
        ("new_events", proposal.new_events, keep_new),
        ("extended_events", proposal.extended_events, keep_extended),
        ("reused_events", proposal.reused_events, keep_reused),
    ):
        for item in items:
            key = _key(item.name)
            if key in seen:
                blocker(
                    "DUPLICATE",
                    item.name,
                    f"{item.name!r} appears in {seen[key]} and in {label}; "
                    "an event belongs in exactly one list, once",
                )
                continue
            seen[key] = label
            if label == "new_events" and key in plan_keys:
                blocker(
                    "COLLISION",
                    item.name,
                    f"new event {item.name!r} already exists in the plan; use extended_events "
                    "to add properties or reused_events to rely on it",
                )
                continue
            target: str | None = None
            if label != "new_events":
                target, candidates = _resolve(item.name, plan_names)
                if candidates:
                    blocker(
                        "AMBIGUOUS_EVENT",
                        item.name,
                        f"{label} names {item.name!r}, which matches {candidates} in the plan, "
                        "events that differ only in letter case; use the exact name of one",
                    )
                    continue
                if target is None:
                    blocker(
                        "UNKNOWN_EVENT",
                        item.name,
                        f"{label} names {item.name!r}, which is not in the existing plan; "
                        "check the spelling or propose it as a new event",
                    )
                    continue
            if label == "extended_events":
                assert target is not None
                have = {_key(p.name) for p in events_by_name[target].properties}
                fresh = []
                for prop in item.add_properties:
                    if _key(prop.name) in have:
                        blocker(
                            "DUPLICATE_PROPERTY",
                            f"{item.name}.{prop.name}",
                            f"{item.name!r} already has a property {prop.name!r}",
                        )
                    else:
                        fresh.append(prop)
                        have.add(_key(prop.name))
                if not fresh:
                    continue
                item = replace(item, add_properties=tuple(fresh))
            keep.append(item)

    if plan is None and not proposal.identity_keys:
        blocker(
            "IDENTITY",
            "identity_keys",
            "no existing plan was given, so the proposal must name identity_keys "
            "(the properties that tie an event to a user or device)",
        )
    if plan is None and not proposal.feature.id:
        blocker(
            "IDENTITY",
            "feature.id",
            "no existing plan was given, so feature.id (snake_case) names the new plan",
        )
    existing_metrics = {_key(m.name) for m in plan.metrics} if plan else set()
    keep_metrics = []
    for metric in proposal.metrics:
        if _key(metric.name) in existing_metrics:
            blocker(
                "METRIC_COLLISION",
                metric.name,
                f"metric {metric.name!r} already exists in the plan; choose a new name",
            )
        else:
            keep_metrics.append(metric)
    sanitized = replace(
        proposal,
        new_events=tuple(keep_new),
        extended_events=tuple(keep_extended),
        reused_events=tuple(keep_reused),
        metrics=tuple(keep_metrics),
    )
    return problems, sanitized


def _check_evidence(
    proposal: Proposal, documents: Sequence[Document]
) -> tuple[Grounding, list[Problem]]:
    by_name = {document.name: document for document in documents}
    found = missing = unverifiable = inferred = 0
    status: dict[str, str] = {}
    problems: list[Problem] = []
    items: list[tuple[str, Evidence]] = [(e.name, e.evidence) for e in proposal.new_events]
    items += [(e.name, e.evidence) for e in proposal.extended_events]
    for subject, evidence in items:
        if evidence.kind == "inferred":
            inferred += 1
            status[subject] = "inferred"
            continue
        document = by_name.get(evidence.document)
        if document is None:
            missing += 1
            status[subject] = "missing"
            problems.append(
                Problem(
                    code="EVIDENCE_DOCUMENT",
                    severity="blocker",
                    subject=subject,
                    message=f"evidence cites document {evidence.document!r}, which was not "
                    f"provided (provided: {sorted(by_name)})",
                )
            )
            continue
        verdict = quote_in_document(evidence.quote, document)
        if verdict is None:
            unverifiable += 1
            status[subject] = "unverifiable"
            problems.append(
                Problem(
                    code="EVIDENCE_UNVERIFIABLE",
                    severity="info",
                    subject=subject,
                    message=f"the quote is from {document.name}, a PDF, which cannot be searched; "
                    "check it by eye",
                )
            )
        elif verdict:
            found += 1
            status[subject] = "found"
        else:
            missing += 1
            status[subject] = "missing"
            problems.append(
                Problem(
                    code="EVIDENCE_QUOTE",
                    severity="blocker",
                    subject=subject,
                    message=f"the quote {evidence.quote!r} was not found in {document.name}; "
                    "quote the document verbatim, or use kind 'inferred' if it is your judgement",
                )
            )
    return (
        Grounding(
            quoted_found=found,
            quoted_missing=missing,
            unverifiable=unverifiable,
            inferred=inferred,
            by_event=status,
        ),
        problems,
    )


def _reuse_problems(proposal: Proposal, plan: TrackingPlan | None) -> list[Problem]:
    if plan is None:
        return []  # nothing exists to reuse, so a claim can be neither right nor wrong
    existing_props: dict[str, set[str]] = {}
    if plan is not None:
        for event in plan.events:
            for prop in event.properties:
                existing_props.setdefault(_key(prop.name), set()).add(prop.type)
    problems: list[Problem] = []
    for subject, props in _proposed_properties(proposal):
        known_types = existing_props.get(_key(props.name))
        if props.reuses_existing and known_types is None:
            problems.append(
                Problem(
                    code="REUSE_CLAIM",
                    severity="warning",
                    subject=f"{subject}.{props.name}",
                    message="marked reuses_existing, but the plan has no property of that name",
                )
            )
        elif not props.reuses_existing and known_types is not None:
            problems.append(
                Problem(
                    code="REUSE_UNFLAGGED",
                    severity="info",
                    subject=f"{subject}.{props.name}",
                    message="a property of this name already exists in the plan; "
                    "mark reuses_existing and keep its type",
                )
            )
    return problems


def _proposed_properties(proposal: Proposal) -> list[tuple[str, ProposedProperty]]:
    pairs = [(e.name, p) for e in proposal.new_events for p in e.properties]
    pairs += [(e.name, p) for e in proposal.extended_events for p in e.add_properties]
    return pairs


# --- Merging ------------------------------------------------------------------------------


def _property_dict(prop: ProposedProperty) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": prop.name,
        "type": prop.type,
        "required": prop.required,
        "description": prop.description,
        "pii": prop.pii,
    }
    if prop.allowed_values:
        data["allowed_values"] = list(prop.allowed_values)
    return data


def merge(
    proposal: Proposal,
    plan: TrackingPlan | None,
    *,
    new_status: Literal["planned", "active"],
    owner: str | None = None,
) -> TrackingPlan:
    """The plan with the proposal applied. Raises PlanError if the result is not a valid plan.

    New events get `new_status`: "planned" for what is written (the feature has not shipped) and
    "active" for the review, which asks whether the plan is sound once the feature is out.
    """
    if plan is not None:
        raw = plan.to_dict()
    else:
        raw = {
            VERSION_KEY: PLAN_VERSION,
            "id": proposal.feature.id,
            "title": proposal.feature.name,
            "identity_keys": list(proposal.identity_keys),
            "events": [],
        }
        if owner:
            raw["owner"] = owner
    events: list[dict[str, Any]] = raw["events"]
    for item in proposal.extended_events:
        target, _ = _resolve(item.name, [e["name"] for e in events])
        for event in events:
            if event["name"] == target:
                event.setdefault("properties", []).extend(
                    _property_dict(p) for p in item.add_properties
                )
    for new in proposal.new_events:
        event: dict[str, Any] = {
            "name": new.name,
            "status": new_status,
            "description": new.description,
            "trigger": new.trigger,
            "properties": [_property_dict(p) for p in new.properties],
        }
        if owner:
            event["owner"] = owner
        events.append(event)
    if proposal.metrics:
        raw.setdefault("metrics", []).extend(
            {"name": m.name, "events": list(m.events)} for m in proposal.metrics
        )
    return TrackingPlan.from_dict(raw)


def repair_feedback(result: CheckResult) -> list[str]:
    """What the model is told to fix: blocking problems, and introduced findings it can fix."""
    lines = [
        f"[{p.code}] {p.subject}: {p.message}"
        for p in result.problems
        if p.severity in ("blocker", "warning")
    ]
    lines += [
        f"[{f.rule_id}] {f.title}. Evidence: {_compact(f.evidence)}. Fix: {f.remediation}"
        for f in result.introduced
        if f.severity in ("blocker", "warning") and f.rule_id not in UNREPAIRABLE_RULES
    ]
    return lines


def needs_repair(result: CheckResult) -> bool:
    return bool(repair_feedback(result))


def _compact(evidence: dict[str, Any]) -> str:
    import json

    text = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    return text if len(text) <= 600 else text[:597] + "..."
