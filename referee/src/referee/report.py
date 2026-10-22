"""The design-review and the results-review reports: one plain dict each, rendered as JSON or text.

The text is made from the dict, not from the review objects, so the two outputs cannot say
different things, and a JSON report saved earlier can be rendered as text later. Nothing in
the report depends on the clock, the machine or where the spec file was kept: the same spec
(and data) reviewed by the same Referee gives the same bytes.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from referee import __version__
from referee.findings import DesignReview, Finding, ResultsReview
from referee.spec import ExperimentSpec

REPORT_VERSION = 1
_SEVERITIES = ("blocker", "warning", "info")
_TEXT_WIDTH = 88


def _counts(findings: Sequence[Finding]) -> dict[str, int]:
    return {
        severity: sum(finding.severity == severity for finding in findings)
        for severity in _SEVERITIES
    }


def _finding_dicts(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    return [
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
    ]


def _instant(moment: datetime | None) -> str | None:
    """A UTC instant as ISO 8601 with a Z, or None."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def design_report(spec: ExperimentSpec, review: DesignReview) -> dict[str, Any]:
    """The report for `review`, which must be the review of `spec`."""
    return {
        "report_version": REPORT_VERSION,
        "kind": "design_review",
        "referee_version": __version__,
        "spec": {"id": spec.id, "title": spec.title, "sha256": spec.sha256()},
        "recommendation": review.recommendation,
        "blocking_rule_ids": list(review.blocking_rule_ids),
        "counts": _counts(review.findings),
        "findings": _finding_dicts(review.findings),
    }


def results_report(
    spec: ExperimentSpec,
    review: ResultsReview,
    *,
    as_of: datetime | None,
    as_of_source: str | None,
) -> dict[str, Any]:
    """The report for `review`, which must be the review of `spec` against its data.

    `as_of` is when the export was taken and `as_of_source` where that came from (`command
    line` or `manifest`); both are None when nothing says.
    """
    return {
        "report_version": REPORT_VERSION,
        "kind": "results_review",
        "referee_version": __version__,
        "spec": {"id": spec.id, "title": spec.title, "sha256": spec.sha256()},
        "experiment_id": review.experiment_id,
        "as_of": {"time": _instant(as_of), "source": as_of_source},
        "verdict": review.verdict,
        "blocking_rule_ids": list(review.blocking_rule_ids),
        "counts": _counts(review.findings),
        "rules_run": list(review.rules_run),
        "findings": _finding_dicts(review.findings),
    }


def render_json(report: dict[str, Any]) -> str:
    """The report as JSON, indented, ASCII only (so any terminal can show it)."""
    return json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _paragraph(text: str, indent: str) -> list[str]:
    return textwrap.wrap(text, width=_TEXT_WIDTH, initial_indent=indent, subsequent_indent=indent)


def _prose_lines(finding: dict[str, Any]) -> list[str]:
    """Why it matters, what to do and the references of one finding, as indented text."""
    lines = ["    Why it matters:"]
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
    return lines


def render_text(report: dict[str, Any]) -> str:
    """The design report as plain text for a person to read."""
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
        lines += _prose_lines(finding)

    lines += ["", "Referee is advisory: it recommends, and does not approve or stop an experiment."]
    return "\n".join(lines) + "\n"


def render_results_text(report: dict[str, Any]) -> str:
    """The results report as plain text for a person to read."""
    spec, counts, as_of = report["spec"], report["counts"], report["as_of"]
    taken = (
        "not known (no manifest time and no --as-of)"
        if as_of["time"] is None
        else f"{as_of['time']} ({as_of['source']})"
    )
    lines = [
        "Referee results review",
        f"Spec:       {spec['id']} - {spec['title']}",
        f"Spec hash:  sha256:{spec['sha256']}",
        f"Experiment: {report['experiment_id']}",
        f"As of:      {taken}",
        f"Referee:    {report['referee_version']}",
        "",
        f"Verdict: {report['verdict'].upper()}",
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
        lines += _prose_lines(finding)
        lines.append("    Evidence: in the JSON report (--format json).")

    lines.append("")
    lines += _paragraph(
        "Referee is advisory: a verdict of clear says the rules that ran found nothing that "
        "blocks or warns, not that the effect is real.",
        "",
    )
    return "\n".join(lines) + "\n"
