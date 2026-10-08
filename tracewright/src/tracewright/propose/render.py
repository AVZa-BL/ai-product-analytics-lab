"""Turn a `ProposalResult` into the files a person works with.

Nothing here depends on the clock or the machine: the same result renders to the same bytes. Text
that came from the model is escaped for Markdown (table pipes, line breaks, code spans, a leading
`<`) so a proposal cannot break the layout of the report that describes it.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable
from typing import Any

from tracewright import __version__
from tracewright.findings import Finding
from tracewright.loader import render_plan_yaml
from tracewright.propose.check import Problem
from tracewright.propose.proposal import (
    ExtendedEvent,
    NewEvent,
    Proposal,
    ProposedProperty,
)
from tracewright.propose.run import ProposalResult

REPORT_VERSION = 1
_PRIORITY_ORDER = {"must": 0, "should": 1, "could": 2}
_SEVERITIES = ("blocker", "warning", "info")
_EVIDENCE_LABEL = {
    "found": "quote found in the document",
    "missing": "QUOTE NOT FOUND",
    "unverifiable": "from a PDF; not machine-checked",
    "inferred": "analyst's judgement, not from the documents",
}


# --- Escaping -----------------------------------------------------------------------------


def _line(text: str) -> str:
    """One line of model text, safe in running Markdown.

    Line breaks and runs of spaces become one space, `<` is written as an entity (no raw HTML),
    and square brackets are escaped, which is what turns `[text](url)` and `![alt](url)` into
    plain text instead of a live link or an image that a viewer would fetch.
    """
    flat = re.sub(r"\s+", " ", text).strip()
    return flat.replace("<", "&lt;").replace("[", "\\[").replace("]", "\\]")


def _cell(text: str) -> str:
    return _line(text).replace("|", "\\|")


def _code(text: str) -> str:
    return "`" + re.sub(r"\s+", " ", text).replace("`", "'").strip() + "`"


def _code_cell(text: str) -> str:
    return _code(text).replace("|", "\\|")


def _quote(text: str) -> str:
    return "> " + _line(text)


# --- JSON ---------------------------------------------------------------------------------


def _finding(finding: Finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "title": finding.title,
        "evidence": finding.evidence,
        "remediation": finding.remediation,
    }


def _problem(problem: Problem) -> dict[str, str]:
    return {
        "code": problem.code,
        "severity": problem.severity,
        "subject": problem.subject,
        "message": problem.message,
    }


def result_dict(result: ProposalResult) -> dict[str, Any]:
    final = result.final
    check = final.check
    plan = result.request.plan
    out: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "kind": "tracking_proposal",
        "tracewright_version": __version__,
        "status": result.status,
        "repairs": result.repairs,
        "inputs": {
            "documents": [
                {"name": d.name, "kind": d.kind, "sha256": d.sha256, "bytes": d.size}
                for d in result.request.documents
            ],
            "plan": None if plan is None else {"id": plan.id, "sha256": plan.sha256()},
        },
        "attempts": [
            {
                "number": a.number,
                "model": a.response.model,
                **({"usage": a.response.usage} if a.response.usage else {}),
                "problems_found": list(a.feedback_sent),
            }
            for a in result.attempts
        ],
        "proposal": None if final.proposal is None else final.proposal.to_dict(),
        "schema_violations": list(final.parse_problems),
    }
    if check is not None:
        out["grounding"] = {
            "quoted_found": check.grounding.quoted_found,
            "quoted_missing": check.grounding.quoted_missing,
            "unverifiable": check.grounding.unverifiable,
            "inferred": check.grounding.inferred,
            "by_event": check.grounding.by_event,
        }
        out["problems"] = [_problem(p) for p in check.problems]
        out["introduced_findings"] = [_finding(f) for f in check.introduced]
        out["merged_plan_sha256"] = (
            check.merged_plan.sha256() if check.merged_plan is not None else None
        )
        if check.review is not None:
            out["review_of_merged_plan"] = {
                "recommendation": check.review.recommendation,
                "blocking_rule_ids": list(check.review.blocking_rule_ids),
            }
        if check.baseline_review is not None:
            out["review_of_existing_plan"] = {
                "recommendation": check.baseline_review.recommendation,
                "findings": len(check.baseline_review.findings),
            }
    return out


def render_json(result: ProposalResult) -> str:
    return json.dumps(result_dict(result), indent=2, ensure_ascii=True, allow_nan=False) + "\n"


# --- Plan files ---------------------------------------------------------------------------


def merged_plan_yaml(result: ProposalResult) -> str | None:
    """The merged plan, only for a proposal with no blocking problem: an unresolved one is never
    written out as a plan that could be adopted by mistake."""
    check = result.final.check
    if result.status != "ok" or check is None or check.merged_plan is None:
        return None
    return render_plan_yaml(check.merged_plan)


def plan_diff(result: ProposalResult) -> str | None:
    """Unified diff from the existing plan to the merged plan, both written the same way."""
    existing, merged = result.request.plan, merged_plan_yaml(result)
    if existing is None or merged is None:
        return None
    return "".join(
        difflib.unified_diff(
            render_plan_yaml(existing).splitlines(keepends=True),
            merged.splitlines(keepends=True),
            fromfile="existing-plan.yaml",
            tofile="merged-plan.yaml",
        )
    )


# --- Markdown -----------------------------------------------------------------------------


def _property_table(properties: Iterable[ProposedProperty]) -> list[str]:
    lines = [
        "| Property | Type | Required | PII | Existing | Why it is needed |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in properties:
        kind = p.type
        if p.type == "enum" and p.allowed_values:
            kind = "enum: " + ", ".join(p.allowed_values)
        lines.append(
            f"| {_code_cell(p.name)} | {_cell(kind)} | {'yes' if p.required else 'no'} "
            f"| {'yes' if p.pii else 'no'} | {'reused' if p.reuses_existing else 'new'} "
            f"| {_cell(p.description + ' ' + p.rationale)} |"
        )
    return lines


def _evidence_lines(event: NewEvent | ExtendedEvent, status: dict[str, str]) -> list[str]:
    state = status.get(event.name, "inferred")
    label = _EVIDENCE_LABEL[state]
    if event.evidence.kind == "document":
        return [
            f"- **Evidence** ({_line(event.evidence.document)}; {label}):",
            "",
            _quote(event.evidence.quote),
        ]
    return [f"- **Evidence:** {label}."]


def render_markdown(result: ProposalResult) -> str:
    final = result.final
    proposal = final.proposal
    check = final.check
    plan = result.request.plan
    lines: list[str] = []
    if proposal is None:
        lines += [
            "# Tracking proposal: no valid proposal",
            "",
            "**Status: UNRESOLVED.** The model's last response could not be read as a proposal:",
            "",
        ]
        lines += [f"- {_line(v)}" for v in final.parse_problems]
        lines += _provenance(result)
        return "\n".join(lines) + "\n"

    lines += [f"# Tracking proposal: {_line(proposal.feature.name)}", ""]
    if result.status == "ok":
        note = "no blocking problem remains" + (
            f" (after {result.repairs} repair round{'s' if result.repairs != 1 else ''})"
            if result.repairs
            else ""
        )
        lines.append(f"**Status: OK**, {note}. Tracewright advises; a person decides.")
    else:
        lines.append(
            "**Status: UNRESOLVED.** Blocking problems remain after "
            f"{result.repairs} repair round{'s' if result.repairs != 1 else ''}; they are listed "
            "under *Automatic checks*. Do not adopt this proposal as it stands."
        )
    lines += ["", _line(proposal.feature.summary), ""]
    lines += _at_a_glance(result, proposal)

    status = check.grounding.by_event if check else {}
    if proposal.new_events:
        lines += ["## New events", ""]
        # Stable: within a priority the model's own order (usually the funnel order) is kept.
        ordered = sorted(proposal.new_events, key=lambda e: _PRIORITY_ORDER[e.priority])
        for event in ordered:
            lines += [f"### {_code(event.name)} ({event.priority})", ""]
            lines += [
                f"- **What it is:** {_line(event.description)}",
                f"- **Sent when:** {_line(event.trigger)}",
                f"- **Why:** {_line(event.rationale)}",
            ]
            lines += _evidence_lines(event, status)
            lines += ["", *_property_table(event.properties), ""]
    if proposal.extended_events:
        lines += ["## Existing events to extend", ""]
        for item in proposal.extended_events:
            lines += [f"### {_code(item.name)}", "", f"- **Why:** {_line(item.rationale)}"]
            lines += _evidence_lines(item, status)
            lines += ["", *_property_table(item.add_properties), ""]
    if proposal.reused_events:
        lines += ["## Existing events that already cover part of the feature", ""]
        lines += [f"- {_code(e.name)}: {_line(e.rationale)}" for e in proposal.reused_events]
        lines.append("")
    if proposal.metrics:
        lines += ["## Metrics this tracking makes possible", ""]
        for m in proposal.metrics:
            events = ", ".join(_code(e) for e in m.events)
            lines += [
                f"- **{_line(m.name)}**: {_line(m.definition)} Needs: {events}. "
                f"Why: {_line(m.rationale)}"
            ]
        lines.append("")
    if proposal.not_tracked:
        lines += ["## Deliberately not tracked", ""]
        lines += [f"- {_line(x.what)}: {_line(x.why)}" for x in proposal.not_tracked]
        lines.append("")
    if proposal.assumptions:
        lines += ["## Assumptions the proposal makes", ""]
        lines += [f"- {_line(a)}" for a in proposal.assumptions] + [""]
    if proposal.open_questions:
        lines += ["## Questions the documents do not answer", ""]
        lines += [f"- {_line(q)}" for q in proposal.open_questions] + [""]

    lines += _checks(result, plan is not None)
    lines += _provenance(result)
    return "\n".join(lines).rstrip("\n") + "\n"


def _at_a_glance(result: ProposalResult, proposal: Proposal) -> list[str]:
    check = result.final.check
    lines = [
        "| New events | Extended | Reused | Metrics | Open questions |",
        "| --- | --- | --- | --- | --- |",
        f"| {len(proposal.new_events)} | {len(proposal.extended_events)} "
        f"| {len(proposal.reused_events)} | {len(proposal.metrics)} "
        f"| {len(proposal.open_questions)} |",
        "",
    ]
    if check is not None:
        g = check.grounding
        total = g.quoted_found + g.quoted_missing + g.unverifiable + g.inferred
        if total:
            lines += [
                f"Evidence for {total} event(s): {g.quoted_found} quoted from the documents and "
                f"found, {g.quoted_missing} quoted but not found, {g.unverifiable} from a PDF "
                f"(not machine-checked), {g.inferred} the analyst's judgement. A found quote "
                "shows the words are in the document, not that the event is the right one.",
                "",
            ]
    return lines


def _checks(result: ProposalResult, had_plan: bool) -> list[str]:
    check = result.final.check
    if check is None:
        return []
    lines = ["## Automatic checks", ""]
    if not check.problems and not check.introduced:
        lines += ["No problems found in the proposal.", ""]
    for problem in check.problems:
        if problem.severity == "info" and problem.code == "EVIDENCE_UNVERIFIABLE":
            continue
        lines.append(
            f"- **{problem.severity.upper()}** [{problem.code}] {_code(problem.subject)}: "
            f"{_line(problem.message)}"
        )
    for finding in check.introduced:
        lines.append(
            f"- **{finding.severity.upper()}** [{finding.rule_id}] {finding.title}. "
            f"Evidence: {_code(json.dumps(finding.evidence, sort_keys=True))}. "
            f"What to do: {_line(finding.remediation)}"
        )
    baseline = check.baseline_review
    if lines[-1] != "":
        lines.append("")
    if baseline is not None:
        counts = {s: sum(f.severity == s for f in baseline.findings) for s in _SEVERITIES}
        lines += [
            f"The existing plan already has {len(baseline.findings)} finding(s) from "
            f"`tracewright review-plan` ({counts['blocker']} blocker, {counts['warning']} "
            f"warning, {counts['info']} info). They are not counted against this proposal, "
            "unless the proposal changes a finding, in which case that finding is shown whole. "
            "The merged plan was reviewed as if the feature had shipped.",
        ]
        if baseline.recommendation == "revise":
            lines += [
                "",
                "**The existing plan has a blocker of its own, so `review-plan` on the merged "
                f"plan will still recommend REVISE** (blocking: "
                f"{', '.join(baseline.blocking_rule_ids)}). Fixing it is outside this proposal.",
            ]
    elif not had_plan:
        lines += ["There was no existing plan; the proposal was reviewed as a new plan."]
    lines.append("")
    return lines


def _provenance(result: ProposalResult) -> list[str]:
    lines = ["## Provenance", ""]
    for d in result.request.documents:
        lines.append(f"- Document {_code(d.name)}: {d.kind}, {d.size:,} bytes, sha256 `{d.sha256}`")
    plan = result.request.plan
    if plan is not None:
        lines.append(f"- Existing plan {_code(plan.id)}: sha256 `{plan.sha256()}`")
    else:
        lines.append("- No existing plan was given.")
    models = sorted({a.response.model for a in result.attempts if a.response.model})
    lines.append(
        f"- Attempts: {len(result.attempts)} (repairs: {result.repairs}); "
        f"model: {', '.join(models) if models else 'unknown'}; Tracewright {__version__}"
    )
    if "replay" in models:
        lines.append(
            "- **This proposal was replayed from a saved file. No model produced it in this run.**"
        )
    lines.append(
        "- A model wrote this proposal, so it can be wrong in ways the automatic checks cannot "
        "see. Read the reasoning, not only the event list."
    )
    return lines
