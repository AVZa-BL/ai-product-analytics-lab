"""The design-review report: one plain dict, rendered as JSON or as text.

The text is made from the dict, not from the review objects, so the two outputs cannot say
different things, and a JSON report saved earlier can be rendered as text later. Nothing in
the report depends on the clock, the machine or where the spec file was kept: the same spec
reviewed by the same Referee gives the same bytes.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any

from referee import __version__
from referee.findings import DesignReview
from referee.spec import ExperimentSpec

REPORT_VERSION = 1
_SEVERITIES = ("blocker", "warning", "info")
_TEXT_WIDTH = 88


def design_report(spec: ExperimentSpec, review: DesignReview) -> dict[str, Any]:
    """The report for `review`, which must be the review of `spec`."""
    findings = review.findings
    return {
        "report_version": REPORT_VERSION,
        "kind": "design_review",
        "referee_version": __version__,
        "spec": {"id": spec.id, "title": spec.title, "sha256": spec.sha256()},
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
    spec, counts = report["spec"], report["counts"]
    lines = [
        "Referee design review",
        f"Spec:      {spec['id']} - {spec['title']}",
        f"Spec hash: sha256:{spec['sha256']}",
        f"Referee:   {report['referee_version']}",
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
                wrapped = textwrap.wrap(
                    reference,
                    width=_TEXT_WIDTH,
                    initial_indent="      - ",
                    subsequent_indent="        ",
                )
                lines += wrapped

    lines += ["", "Referee is advisory: it recommends, and does not approve or stop an experiment."]
    return "\n".join(lines) + "\n"
