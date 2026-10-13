"""The plan-review report: one plain dict, rendered as JSON or as text.

The text is made from the dict, not from the review objects, so the two outputs cannot say
different things. Nothing in the report depends on the clock, the machine or where the plan file
was kept: the same plan reviewed by the same Tracewright gives the same bytes.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from tracewright import __version__
from tracewright.findings import PlanReview
from tracewright.plan import TrackingPlan

REPORT_VERSION = 1
_SEVERITIES = ("blocker", "warning", "info")
_TEXT_WIDTH = 88


def plan_report(plan: TrackingPlan, review: PlanReview) -> dict[str, Any]:
    """The report for `review`, which must be the review of `plan`."""
    findings = review.findings
    return {
        "report_version": REPORT_VERSION,
        "kind": "plan_review",
        "tracewright_version": __version__,
        "plan": {
            "id": plan.id,
            "title": plan.title,
            "events": len(plan.events),
            "metrics": len(plan.metrics),
            "sha256": plan.sha256(),
        },
        "recommendation": review.recommendation,
        "blocking_rule_ids": list(review.blocking_rule_ids),
        "counts": {
            severity: sum(finding.severity == severity for finding in findings)
            for severity in _SEVERITIES
        },
        "findings": [
            {
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "title": finding.title,
                "evidence": finding.evidence,
                "why_it_matters": finding.why_it_matters,
                "remediation": finding.remediation,
                "references": list(finding.references),
            }
            for finding in findings
        ],
    }


def render_json(report: dict[str, Any]) -> str:
    """The report as JSON, indented, ASCII only (so any terminal can show it)."""
    return json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _paragraph(text: str, indent: str) -> list[str]:
    return textwrap.wrap(text, width=_TEXT_WIDTH, initial_indent=indent, subsequent_indent=indent)


def render_text(report: dict[str, Any]) -> str:
    """The report as plain text for a person to read."""
    plan, counts = report["plan"], report["counts"]
    lines = [
        "Tracewright tracking-plan review",
        f"Plan:      {plan['id']} - {plan['title']}",
        f"Contents:  {plan['events']} events, {plan['metrics']} metrics",
        f"Plan hash: sha256:{plan['sha256']}",
        f"Version:   Tracewright {report['tracewright_version']}",
        "",
        f"Recommendation: {report['recommendation'].upper()}",
    ]
    if report["blocking_rule_ids"]:
        lines.append("Blocking rules: " + ", ".join(report["blocking_rule_ids"]))
    if report["findings"]:
        lines.append(
            f"Findings: blockers {counts['blocker']}, warnings {counts['warning']}, "
            f"info {counts['info']}"
        )
    else:
        lines.append("Findings: none")

    for finding in report["findings"]:
        lines += ["", f"[{finding['severity'].upper()}] {finding['rule_id']}: {finding['title']}"]
        if finding["evidence"]:
            lines.append("    Evidence:")
            lines += [f"      {key}: {_value(item)}" for key, item in finding["evidence"].items()]
        lines.append("    Why it matters:")
        lines += _paragraph(finding["why_it_matters"], "      ")
        lines.append("    What to do:")
        lines += _paragraph(finding["remediation"], "      ")
        if finding["references"]:
            lines.append("    References:")
            for reference in finding["references"]:
                lines += textwrap.wrap(
                    reference,
                    width=_TEXT_WIDTH,
                    initial_indent="      - ",
                    subsequent_indent="        ",
                )

    lines += [
        "",
        "Tracewright is advisory: it recommends, and does not approve or block a release.",
    ]
    return "\n".join(lines) + "\n"
