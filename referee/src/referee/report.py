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
from datetime import UTC, datetime, timedelta
from typing import Any

from referee import __version__
from referee.display import DISPLAY_ROW_LIMIT, cap_listing
from referee.findings import DesignReview, Finding, ResultsReview
from referee.results import ResultsContext
from referee.rules.cohorts import cohort_report
from referee.rules.design import OUTCOME_WINDOW_DAYS
from referee.rules.guardrails import guardrail_report
from referee.rules.heavy_tails import heavy_tail_report
from referee.spec import ExperimentSpec

REPORT_VERSION = 1
_SEVERITIES = ("blocker", "warning", "info")
_TEXT_WIDTH = 88

# A blocker is about the data (the arms, the sample, the exposures) unless it is a harm: a valid
# experiment that makes a guardrail worse than its tolerance allows (design section 21.12).
_HARM_RULES = frozenset({"RES-004"})
# The rules whose quiet result is still printed, as a line, so that a test that did not run
# cannot read as a pass (design sections 21.5, 21.11 and 21.12). Each report holds its own line.
_ALWAYS_SUMMARISED = (
    ("RES-004", guardrail_report),
    ("RES-007", lambda context: cohort_report(context, None)),
    ("RES-008", heavy_tail_report),
)


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


def _summary_lines(review: ResultsReview, context: ResultsContext) -> list[str]:
    """The line of each always-summarised rule that ran: the finding's own, else a fresh one."""
    found = {finding.rule_id: finding for finding in review.findings}
    lines = []
    for rule_id, report in _ALWAYS_SUMMARISED:
        if rule_id in review.rules_run:
            evidence = found[rule_id].evidence if rule_id in found else report(context)
            lines.append(evidence["summary"]["line"])
    return lines


def _as_of(context: ResultsContext, source: str | None) -> dict[str, Any]:
    """When the export was taken, where that came from, and whether the run is an interim one.

    Judgement: a run is interim when the export was taken before the planned end of the
    experiment, which is the planned accrual window from the origin plus the seven-day outcome
    window that follows the last assignment (design section 21.8). Without a time nothing is
    known of either: completeness was not checked.
    """
    taken = context.exported_at
    if taken is None:
        return {"time": None, "source": None, "planned_end": None, "interim": None}
    days = context.spec.design.planned_duration_days + OUTCOME_WINDOW_DAYS
    planned_end = context.origin + timedelta(days=days)
    return {
        "time": _instant(taken),
        "source": source,
        "planned_end": _instant(planned_end),
        "interim": taken < planned_end,
    }


def results_report(
    review: ResultsReview,
    context: ResultsContext,
    *,
    file_hashes: dict[str, str],
    as_of_source: str | None,
) -> dict[str, Any]:
    """The report for `review`, which must be the review of `context`.

    `file_hashes` are the SHA-256 of the three CSV files (`data.export_file_hashes`) and
    `as_of_source` says where `context.exported_at` came from (`command line` or `manifest`).
    """
    spec = context.spec
    assigned = [player.assigned_at for player in context.players]
    blocking = review.blocking_rule_ids
    return {
        "report_version": REPORT_VERSION,
        "kind": "results_review",
        "referee_version": __version__,
        "spec": {"id": spec.id, "title": spec.title, "sha256": spec.sha256()},
        "experiment_id": review.experiment_id,
        "data": {"files": {name: {"sha256": digest} for name, digest in file_hashes.items()}},
        "as_of": _as_of(context, as_of_source),
        "population": {
            "origin": _instant(context.origin),
            "origin_source": "design.start_utc" if spec.design.start_utc else "first assignment",
            "first_assignment": _instant(min(assigned)),
            "last_assignment": _instant(max(assigned)),
            "assigned": context.count_by_arm(context.players),
            "analysed": context.count_by_arm(context.analysed),
            "ignored_before_start": list(context.ignored_before_start),
        },
        "verdict": review.verdict,
        "blocking_rule_ids": list(blocking),
        "blocking_groups": {
            "data_validity": [rule for rule in blocking if rule not in _HARM_RULES],
            "harm": [rule for rule in blocking if rule in _HARM_RULES],
        },
        "counts": _counts(review.findings),
        "summary_lines": _summary_lines(review, context),
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


def _plain(value: object) -> str:
    """A value as a person reads it: whole numbers with separators, six significant digits."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _wrapped(text: str, pad: str, hang: str = "  ") -> list[str]:
    return textwrap.wrap(
        text, width=_TEXT_WIDTH, initial_indent=pad, subsequent_indent=pad + hang
    ) or [pad.rstrip()]


def _evidence_lines(value: Any, limit: int, indent: int) -> list[str]:
    """Evidence as indented lines. A list is cut at `limit` rows and says so; the report is not.

    A dict is one `key: value` line per key (a nested one under its key), a list of scalars one
    wrapped line, and a list of dicts or lists one `- ` item per row.
    """
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                isinstance(item, list)
                and item
                and not any(isinstance(x, dict | list) for x in item)
            ):
                listing = cap_listing(item, limit=limit)
                text = ", ".join(_plain(x) for x in listing.shown)
                if listing.notice:
                    text += f" ({listing.notice})"
                lines += _wrapped(f"{key}: {text}", pad)
            elif isinstance(item, dict | list) and item:
                lines.append(f"{pad}{key}:")
                lines += _evidence_lines(item, limit, indent + 2)
            else:
                lines += _wrapped(f"{key}: {_plain(item)}", pad)
    else:
        listing = cap_listing(value, limit=limit)
        for row in listing.shown:
            rows = (
                _evidence_lines(row, limit, indent + 2)
                if isinstance(row, dict | list)
                else ([f"{pad}  {_plain(row)}"])
            )
            lines.append(f"{pad}- {rows[0][indent + 2 :]}")
            lines += rows[1:]
        if listing.notice:
            lines.append(f"{pad}({listing.notice})")
    return lines


def _results_evidence_lines(evidence: dict[str, Any], limit: int) -> list[str]:
    """What a person reads of a finding's evidence.

    The three effect rules hold `tests`, `plans` and `settings` too large to read as text and
    sentences (`notes`) that say what they show: the sentences are printed and the tables stay
    in the JSON report. Any other rule's evidence is printed in full, lists cut at `limit`.
    """
    if not evidence:
        return []
    if isinstance(evidence.get("notes"), list) and "tests" in evidence:
        lines = ["    Evidence:"]
        for note in evidence["notes"]:
            lines += textwrap.wrap(
                note, width=_TEXT_WIDTH, initial_indent="      - ", subsequent_indent="        "
            )
        lines += _wrapped(
            "The tests, plans and settings behind these sentences are in the JSON report "
            "(--format json).",
            "      ",
            "",
        )
        return lines
    return ["    Evidence:", *_evidence_lines(evidence, limit, 6)]


def _blocking_text(groups: dict[str, list[str]]) -> str:
    names = (("data_validity", "data validity"), ("harm", "harm"))
    return "; ".join(f"{label} {', '.join(groups[key])}" for key, label in names if groups[key])


def render_results_text(report: dict[str, Any], *, limit: int = DISPLAY_ROW_LIMIT) -> str:
    """The results report as plain text for a person to read.

    A list of more than `limit` rows is cut to its first `limit` and says so. The cut is made
    here, on the finished report, so it can change what is shown and nothing the report holds.
    """
    spec, counts, as_of = report["spec"], report["counts"], report["as_of"]
    population = report["population"]
    if as_of["time"] is None:
        taken = "not known (no manifest time and no --as-of); completeness was not checked"
    else:
        taken = f"{as_of['time']} ({as_of['source']})"
    lines = [
        "Referee results review",
        f"Spec:       {spec['id']} - {spec['title']}",
        f"Spec hash:  sha256:{spec['sha256']}",
        f"Experiment: {report['experiment_id']}",
        "Data files (SHA-256 of the bytes):",
    ]
    lines += [f"  {name}  {file['sha256']}" for name, file in report["data"]["files"].items()]
    lines.append(f"As of:      {taken}")
    if as_of["interim"]:
        lines += _paragraph(
            f"INTERIM RUN: the export was taken before the planned end of the experiment "
            f"({as_of['planned_end']}). The cohort test of RES-007 belongs at the planned end.",
            "            ",
        )
    lines += [
        f"Origin:     {population['origin']} ({population['origin_source']})",
        f"Assigned:   from {population['first_assignment']} to {population['last_assignment']}",
    ]
    for arm, assigned in population["assigned"].items():
        lines.append(f"  {arm}: {assigned:,} assigned, {population['analysed'][arm]:,} analysed")
    ignored = population["ignored_before_start"]
    if ignored:
        lines.append(f"Ignored:    {len(ignored):,} assigned before design.start_utc, in no count")
        lines += _evidence_lines({"players": ignored}, limit, 4)
    lines += [
        f"Referee:    {report['referee_version']}",
        "",
        f"Verdict: {report['verdict'].upper()}",
    ]
    if report["blocking_rule_ids"]:
        lines.append("Blocking rules: " + _blocking_text(report["blocking_groups"]))
    if report["findings"]:
        lines.append(
            f"Findings: blockers {counts['blocker']}, warnings {counts['warning']}, "
            f"info {counts['info']}"
        )
    else:
        lines.append("Findings: none")
    lines += ["", "Always checked (a quiet result is not a pass):"]
    for line in report["summary_lines"]:
        lines += _paragraph(line, "  ")

    for finding in report["findings"]:
        heading = f"[{finding['severity'].upper()}] {finding['rule_id']}: {finding['title']}"
        lines += ["", *_wrapped(heading, "", "    ")]
        lines += _prose_lines(finding)
        lines += _results_evidence_lines(finding["evidence"], limit)

    lines.append("")
    lines += _paragraph(
        "Referee is advisory: a verdict of clear says the rules that ran found nothing that "
        "blocks or warns, not that the effect is real.",
        "",
    )
    return "\n".join(lines) + "\n"
