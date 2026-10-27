"""The design-review and the results-review reports: one plain dict each, rendered as JSON or text.

The text is made from the dict, not from the review objects, so the two outputs cannot say
different things, and a JSON report saved earlier can be rendered as text later. Nothing in
the report depends on the clock, the machine or where the spec file was kept: the same spec
(and data) reviewed by the same Referee on one machine gives the same bytes. Between machines
a float may differ in its last digits.
"""

from __future__ import annotations

import json
import re
import shlex
import textwrap
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from referee import __version__
from referee.display import DISPLAY_ROW_LIMIT, cap_listing, for_line
from referee.findings import DesignReview, Finding, ResultsReview
from referee.results import (
    ResultsContext,
    describe_first_seen,
    effect_table,
    first_seen_summary,
)
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
# The blockers whose remediation says to settle something before the effect is read: RES-001
# (find why the counts differ), RES-003 (the minimum duration, "say so and why before reading
# the effect") and RES-012 (find why players were exposed after they bought). RES-002 (too few
# players) says to report the interval as underpowered, and RES-004 (a harm) not to decide on
# the primary metric alone: neither makes the table unfit to read.
_EFFECT_UNTRUSTED = frozenset({"RES-001", "RES-003", "RES-012"})
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
    window that follows the last assignment (design sections 21.6 and 22.4). Without a time
    nothing is known of either: completeness was not checked. An origin so late in the calendar
    that the planned end does not exist leaves `planned_end` and `interim` null.
    """
    taken = context.exported_at
    if taken is None:
        return {"time": None, "source": None, "planned_end": None, "interim": None}
    days = context.spec.design.planned_duration_days + OUTCOME_WINDOW_DAYS
    try:
        planned_end = context.origin + timedelta(days=days)
    except OverflowError:  # an origin in the last days of the calendar has no planned end
        return {"time": _instant(taken), "source": source, "planned_end": None, "interim": None}
    return {
        "time": _instant(taken),
        "source": source,
        "planned_end": _instant(planned_end),
        "interim": taken < planned_end,
    }


def _effect(context: ResultsContext, review: ResultsReview) -> dict[str, Any]:
    """The effect table with what the blocking rules say about reading it.

    `underpowered` is RES-002 blocking because the arms are smaller than the registered n; a
    design that cannot be sized has no registered n to fall short of.
    """
    unreadable = [rule for rule in review.blocking_rule_ids if rule in _EFFECT_UNTRUSTED]
    smaller_than_registered = any(
        finding.rule_id == "RES-002"
        and finding.severity == "blocker"
        and not finding.evidence.get("unattainable")
        for finding in review.findings
    )
    return {
        **effect_table(context),
        "readable": not unreadable,
        "unreadable_because": unreadable,
        "underpowered": smaller_than_registered,
    }


def results_report(
    review: ResultsReview,
    context: ResultsContext,
    *,
    file_hashes: dict[str, str],
    as_of_source: str | None,
    sensitivity: dict[str, Any],
) -> dict[str, Any]:
    """The report for `review`, which must be the review of `context`.

    `file_hashes` are the SHA-256 of the three CSV files (`data.export_file_hashes`),
    `as_of_source` says where `context.exported_at` came from (`command line` or `manifest`; it
    is not reported when the export has no time) and `sensitivity` is
    `review.origin_sensitivity` for the same data.
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
            "kind_declared": spec.population.kind,
            "first_seen": first_seen_summary(context),
        },
        "origin_sensitivity": sensitivity,
        "verdict": review.verdict,
        "blocking_rule_ids": list(blocking),
        "blocking_groups": {
            "data_validity": [rule for rule in blocking if rule not in _HARM_RULES],
            "harm": [rule for rule in blocking if rule in _HARM_RULES],
        },
        "counts": _counts(review.findings),
        "summary_lines": _summary_lines(review, context),
        "effect": _effect(context, review),
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
    report = _inert(report)
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


def _inert(value: Any) -> Any:
    """`value` with every text in it, the keys too, written as one line that cannot act on a
    terminal. What the text report prints of a spec or an export (a title, an arm, a player,
    an experiment) goes through here first, so that none of it can make lines of its own."""
    if isinstance(value, str):
        return for_line(value)
    if isinstance(value, dict):
        return {_inert(key): _inert(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_inert(item) for item in value]
    return value


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
    return textwrap.wrap(text, width=_TEXT_WIDTH, initial_indent=pad, subsequent_indent=pad + hang)


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
                _evidence_lines(row, limit, indent + 2) if isinstance(row, dict | list) else []
            ) or [f"{pad}  {_plain(row)}"]  # a scalar, or an empty dict or list
            lines.append(f"{pad}- {rows[0][indent + 2 :]}")
            lines += rows[1:]
        if listing.notice:
            lines.append(f"{pad}({listing.notice})")
    return lines


def _is_effect_evidence(evidence: dict[str, Any]) -> bool:
    """The evidence of an effect rule: tables (`tests`) and the sentences (`notes`) that say
    what they show. The sentences are printed; the tables stay in the JSON report."""
    return isinstance(evidence.get("notes"), list) and "tests" in evidence


_TABLES_IN_JSON = (
    "The tests, plans and settings behind these sentences are in the JSON report (--format json)."
)


def _results_evidence_lines(evidence: dict[str, Any], limit: int) -> list[str]:
    """What a person reads of a finding's evidence.

    The three effect rules hold `tests`, `plans` and `settings` too large to read as text and
    sentences (`notes`) that say what they show: the sentences are printed and the tables stay
    in the JSON report. Any other rule's evidence is printed in full, lists cut at `limit`.
    """
    if not evidence:
        return []
    if _is_effect_evidence(evidence):
        lines = ["    Evidence:"]
        for note in evidence["notes"]:
            lines += textwrap.wrap(
                note, width=_TEXT_WIDTH, initial_indent="      - ", subsequent_indent="        "
            )
        lines += _wrapped(_TABLES_IN_JSON, "      ", "")
        return lines
    return ["    Evidence:", *_evidence_lines(evidence, limit, 6)]


def _sensitivity_sentences(sensitivity: dict[str, Any]) -> list[str]:
    """What the origin sensitivity found: a headline, then one sentence for each origin that
    changed the findings."""
    if not sensitivity["ran"]:
        return [f"Origin sensitivity: not run; {sensitivity['reason']}."]
    shifts = sensitivity["shifts"]
    changed = [shift for shift in shifts if not shift["same"]]
    if not changed:
        last = shifts[-1]["days_earlier"]
        return [
            f"Origin sensitivity: the same rules fire at the same severity for origins 1 to "
            f"{last} days earlier."
        ]
    sentences = ["Origin sensitivity: the rules that fire change with the origin."]
    for shift in changed:
        said = [f"verdict {shift['verdict']}"]
        for label in ("appear", "disappear"):
            if shift[label]:
                said.append(f"{label} {', '.join(shift[label])}")
        days = shift["days_earlier"]
        noun = "day" if days == 1 else "days"
        sentences.append(f"{days} {noun} earlier: {'; '.join(said)}")
    return sentences


def _sensitivity_lines(sensitivity: dict[str, Any]) -> list[str]:
    """The sentence on whether the findings hold for origins 1 to 6 days earlier."""
    headline, *shifts = _sensitivity_sentences(sensitivity)
    lines = _wrapped(headline, "", "  ")
    for sentence in shifts:
        lines += _wrapped(sentence, "  ", "    ")
    return lines


def _adjustment_text(effect: dict[str, Any]) -> str:
    comparisons = effect["comparisons"]
    if effect["adjustment"] != "bonferroni":
        return "not adjusted for the number of arms (the spec registers none)"
    return (
        f"adjusted for {comparisons} {'comparison' if comparisons == 1 else 'comparisons'} "
        f"(the arms against control) by Bonferroni, and for nothing else: not for guardrails, "
        f"other metrics or repeated looks"
    )


def _effect_sentences(effect: dict[str, Any], show: Callable[[str], str] = str) -> list[str]:
    """The sentences above the effect table: what it holds, who was left out, how to read it.
    `show` writes the name of an arm: as it is in the text, as a code span in the memo."""
    sentences = [
        f"Effect on {effect['metric']}, each arm against control, among the "
        f"{effect['population']}: two-sided tests and 95% intervals. The p values are "
        f"{_adjustment_text(effect)}."
    ]
    left_out = {arm: n for arm, n in effect["left_out"].items() if n}
    if left_out:
        said = ", ".join(f"{show(arm)} {n:,}" for arm, n in left_out.items())
        sentences.append(
            f"Left out, because their seven-day window had not closed at the export time: {said}."
        )
    if not effect["readable"]:
        sentences.append(
            f"NOT TO BE READ: blocked by {', '.join(effect['unreadable_because'])}, whose "
            f"remediation says to settle this before the effect is read. These numbers describe "
            f"the sample and not the effect."
        )
    if effect["underpowered"]:
        advice = (
            "Read the intervals; a small difference is not evidence of no effect."
            if effect["readable"]
            else "Do not read the intervals yet: once the effect can be read, a small "
            "difference is still not evidence of no effect."
        )
        sentences.append(
            f"UNDERPOWERED: RES-002 blocks this review, the arms are smaller than registered. "
            f"{advice}"
        )
    return sentences


def _effect_rows(
    effect: dict[str, Any],
) -> tuple[list[tuple[str, ...]], list[tuple[str, str, str]]]:
    """The table's rows, one an arm, and (arm, players, reason) for each arm with no estimate."""
    rows, failed = [], []
    for arm in effect["arms"]:
        players = f"{arm['n_treatment']:,} vs {arm['n_control']:,}"
        if "error" in arm:
            failed.append((arm["arm"], players, arm["error"]))
            continue
        relative = arm["relative_difference"]
        rows.append(
            (
                arm["arm"],
                players,
                f"{arm['difference']:+.4g}",
                f"{arm['ci_low']:.4g} to {arm['ci_high']:.4g}",
                "n/a" if relative is None else f"{relative:+.1%}",
                f"{arm['p_value']:.3g}",
                f"{arm['adjusted_p_value']:.3g}",
            )
        )
    return rows, failed


_EFFECT_COLUMNS = ("arm", "players", "difference", "95% interval", "relative", "p", "adjusted p")


def _effect_lines(effect: dict[str, Any]) -> list[str]:
    """The effect table as text: one row an arm, columns aligned, the reading rules above it."""
    lines = [line for text in _effect_sentences(effect) for line in _wrapped(text, "", "  ")]
    rows, failed = _effect_rows(effect)
    if rows:
        table = [_EFFECT_COLUMNS]
        widths = [max(len(row[i]) for row in [*table, *rows]) for i in range(7)]
        lines += [
            "  "
            + "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
            for row in [*table, *rows]
        ]
    for arm, players, error in failed:
        lines += _wrapped(f"{arm} ({players}): not estimated; {error}", "  ", "  ")
    return lines


def _blocking_text(groups: dict[str, list[str]]) -> str:
    names = (("data_validity", "data validity"), ("harm", "harm"))
    return "; ".join(f"{label} {', '.join(groups[key])}" for key, label in names if groups[key])


def render_results_text(report: dict[str, Any], *, limit: int = DISPLAY_ROW_LIMIT) -> str:
    """The results report as plain text for a person to read.

    A list of more than `limit` rows is cut to its first `limit` and says so. The cut is made
    here, on the finished report, so it can change what is shown and nothing the report holds.
    """
    report = _inert(report)
    spec, counts, as_of = report["spec"], report["counts"], report["as_of"]
    population = report["population"]
    if as_of["time"] is None:
        taken = "not known (no manifest time and no --as-of); completeness was not checked"
    else:
        taken = f"{as_of['time']} ({as_of['source']})"
    lines = [
        "Referee results review",
        *_wrapped(f"Spec:       {spec['id']} - {spec['title']}", "", " " * 12),
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
    lines += _sensitivity_lines(report["origin_sensitivity"])
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
    lines += ["", *_effect_lines(report["effect"])]

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


# --- The memo --------------------------------------------------------------------------

# The sections of the analytics lab's decision-memo template, in its order (design section 5):
# what is decided, what was seen, what it rests on, what is wrong with the data, how to redo it.
MEMO_HEADINGS = (
    "Decision",
    "Observed facts",
    "Assumptions and uncertainty",
    "Data-quality qualification",
    "Reproducibility",
)


def _md_code(value: object) -> str:
    """A value from a spec or an export as a markdown code span, so that it is shown as it is
    and can open no heading, list, quote, fence or inline construct. The span is fenced with
    one more backtick than the longest run inside the value, and padded with a space when the
    value starts or ends with a backtick or has a space at both ends, as CommonMark asks."""
    text = str(value)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    # a span that starts or ends with a backtick, or has a space at both ends, loses a character
    # when it is read back, unless it is padded
    framed = text.startswith("`") or text.endswith("`") or (text[:1] == text[-1:] == " ")
    pad = " " if framed and text.strip(" ") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


_MD_MARKS = re.compile(r"[\\`*\[\]<>|&~]|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")


def _md_text(value: object) -> str:
    """A value from a spec or an export written into a table cell or a sentence: each mark that
    starts an inline construct (a link, an image, a tag, emphasis, a code span, a cell edge)
    has a backslash before it, so that the value is shown as it is. An underscore is marked
    only at the edge of a word, where it can open emphasis; `variant_b` stays as it is."""
    return _MD_MARKS.sub(lambda mark: "\\" + mark.group(0), str(value))


def _md_table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    # a cell is escaped, not put in a code span: a pipe inside a code span still ends the cell
    lines = ["| " + " | ".join(_md_text(cell) for cell in header) + " |"]
    lines.append("|" + " --- |" * len(header))
    lines += ["| " + " | ".join(_md_text(cell) for cell in row) + " |" for row in rows]
    return lines


def _paragraphs(*texts: str) -> list[str]:
    """Each text as one markdown paragraph on a line of its own, a blank line between them.

    The memo is not wrapped, and a value from a spec or an export never starts a line: a line
    that began with a value could open a heading, a list or a fence.
    """
    lines: list[str] = []
    for text in texts:
        if lines:
            lines.append("")
        lines.append(text)
    return lines


def _items(texts: Sequence[str]) -> list[str]:
    return [f"- {text}" for text in texts]


def _decision_sentences(report: dict[str, Any]) -> list[str]:
    """What the blocking rules advise, in the words of the effect table's labels (design section
    22.3); then what is and is not decided here. Judgement: the memo adds no verdict of its
    own, so a blocker it has no words for is a bug in Referee, not a sentence."""
    verdict, effect, groups = report["verdict"], report["effect"], report["blocking_groups"]
    said: list[str] = []
    if verdict == "invalid":
        if effect["unreadable_because"]:
            rules = effect["unreadable_because"]
            one = len(rules) == 1
            said.append(
                f"Do not read the effect. {', '.join(rules)} {'blocks' if one else 'block'} "
                f"this review, and {'its' if one else 'their'} remediation says to settle what "
                f"{'it' if one else 'they'} found before the effect is read."
            )
        if groups["harm"]:
            said.append(
                f"Do not decide on the primary metric alone: {', '.join(groups['harm'])} found "
                "a guardrail worse than its tolerance allows."
            )
        if effect["underpowered"] and effect["unreadable_because"]:
            # the effect is not to be read yet, so neither are its intervals
            said.append(
                "RES-002 also blocks: the arms are smaller than the registered sample size. "
                "Once the effect can be read, and if the arms are still smaller, report the "
                "result as underpowered: a small difference is not evidence of no effect."
            )
        elif effect["underpowered"]:
            said.append(
                "Report the result as underpowered: the arms are smaller than the registered "
                "sample size (RES-002). Read the intervals; a small difference is not evidence "
                "of no effect."
            )
        if any(
            f["rule_id"] == "RES-002"
            and f["severity"] == "blocker"
            and f["evidence"].get("unattainable")
            for f in report["findings"]
        ):
            said.append(
                "The design cannot be sized (RES-002): correct the spec's baseline and target "
                "effect and register the experiment again. More data will not clear this."
            )
        if not said:
            raise ValueError(
                f"the memo has no advice for the blocking rules {report['blocking_rule_ids']}"
            )
    elif verdict == "caution":
        warnings = [f["rule_id"] for f in report["findings"] if f["severity"] == "warning"]
        noun = "warning" if len(warnings) == 1 else "warnings"
        said.append(
            f"The rules that ran found no blocker and {len(warnings)} {noun} "
            f"({', '.join(warnings)}). Read the effect with them in view; each is qualified "
            "under Data-quality qualification."
        )
    else:
        said.append(
            "The rules that ran found nothing that blocks or warns. That does not say the "
            "effect is real: it says that none of the checks Referee makes objected."
        )
    said.append(
        "Decided here: whether the rules object to reading this experiment's result as it "
        "stands. Not decided here: whether to ship, stop or continue the experiment. Referee is "
        "advisory, and that decision rests with the experiment's owner."
    )
    return said


def _observed_lines(report: dict[str, Any], limit: int) -> list[str]:
    """The verdict, the population, the time of the export, the always-checked lines and the
    effect table, every number copied from the report."""
    population, as_of, effect = report["population"], report["as_of"], report["effect"]
    counts = report["counts"]
    verdict = f"Verdict: {report['verdict'].upper()}."
    if report["blocking_rule_ids"]:
        verdict += f" Blocking rules: {_blocking_text(report['blocking_groups'])}."
    if report["findings"]:
        found = (
            f"Findings: blockers {counts['blocker']}, warnings {counts['warning']}, "
            f"info {counts['info']}."
        )
    else:
        found = "Findings: none."
    lines = _paragraphs(
        f"{verdict} {found}",
        f"Assigned from {population['first_assignment']} to {population['last_assignment']}; "
        f"weeks are counted from {population['origin']} ({population['origin_source']}).",
    )
    lines += [
        "",
        *_md_table(
            ("arm", "assigned", "analysed", "left out of the effect table"),
            [
                (arm, f"{n:,}", f"{population['analysed'][arm]:,}", f"{effect['left_out'][arm]:,}")
                for arm, n in population["assigned"].items()
            ],
        ),
    ]
    ignored = population["ignored_before_start"]
    if ignored:
        listing = cap_listing(ignored, limit=limit)
        shown = ", ".join(_md_code(player) for player in listing.shown)
        more = f"; {listing.notice}" if listing.notice else ""
        lines += [
            "",
            f"Ignored, assigned before design.start_utc and in no count: {len(ignored):,} "
            f"({shown}{more}).",
        ]
    if as_of["time"] is None:
        taken = (
            "not known (no manifest time and no --as-of); completeness of the outcome windows "
            "was not checked"
        )
    else:
        taken = f"{as_of['time']} ({as_of['source']})"
    interim = (
        f" INTERIM RUN: before the planned end of the experiment ({as_of['planned_end']})."
        if as_of["interim"]
        else ""
    )
    lines += ["", f"Export taken: {taken}.{interim}"]
    lines += ["", "Always checked (a quiet result is not a pass):", ""]
    lines += _items(report["summary_lines"])
    lines += ["", *_paragraphs(*_effect_sentences(effect, show=_md_code))]
    rows, failed = _effect_rows(effect)
    if rows:
        lines += ["", *_md_table(_EFFECT_COLUMNS, rows)]
    for arm, players, error in failed:
        lines += ["", f"Arm {_md_code(arm)} ({players}): not estimated; {error}"]
    return lines


def _assumption_sentences(report: dict[str, Any]) -> list[str]:
    """What the numbers rest on: the registered values, the tests and their adjustment, the
    time of the export, the origin, the kind of players, and what the verdict words mean."""
    effect, as_of, population = report["effect"], report["as_of"], report["population"]
    said = [
        "The allocation and the baselines are the spec's registered values, not the data's: "
        "the sample-ratio check is read against the registered allocation, and the sample size "
        "against the registered baseline and target effect.",
        f"The effect table is two-sided at 95% whatever design.sided and design.alpha say, and "
        f"its p values are {_adjustment_text(effect)}. The relative difference is a point "
        "estimate with no interval of its own. The table describes the sample; the verdict and "
        "its label say whether it can be read.",
    ]
    if as_of["time"] is None:
        said.append(
            "No time of the export is known, so no outcome window was checked: the effect "
            "table reads every analysed player, a window still open included, and whether this "
            "is an interim run cannot be said."
        )
    elif as_of["interim"]:
        said.append(
            f"INTERIM RUN: the export was taken before the planned end of the experiment "
            f"({as_of['planned_end']}). The cohort test of RES-007 belongs at the planned end; "
            "run repeatedly on accumulating data it flags 11% to 13% of experiments with no "
            "change (design section 21.6)."
        )
    elif as_of["planned_end"] is None:
        said.append(
            "The planned end of the experiment falls outside the calendar, so whether this is "
            "an interim run cannot be said."
        )
    else:
        said.append(
            f"The export was taken at or after the planned end of the experiment "
            f"({as_of['planned_end']})."
        )
    headline, *shifts = _sensitivity_sentences(report["origin_sensitivity"])
    said.append(" ".join([headline, *(f"{sentence}." for sentence in shifts)]))
    said.append(describe_first_seen(population["first_seen"], population["kind_declared"]))
    said.append(
        "The verdict words: clear says that the rules which ran found nothing that blocks or "
        "warns, caution that at least one warned, invalid that at least one blocked. A verdict "
        "is read together with the rules that ran, listed under Data-quality qualification: a "
        "rule that did not run found nothing because it did not look."
    )
    return said


def _quality_lines(report: dict[str, Any], limit: int) -> list[str]:
    """Every finding with its evidence (the effect rules' sentences; the other rules' values,
    as an indented code block that nothing in them can close), then the rules that ran."""
    lines: list[str] = []
    if not report["findings"]:
        lines += _paragraphs("No finding: the rules that ran found nothing that blocks or warns.")
    for finding in report["findings"]:
        if lines:
            lines.append("")
        heading = f"[{finding['severity'].upper()}] {finding['rule_id']}: {finding['title']}"
        lines.append(f"**{heading}**")
        lines += ["", f"Why it matters: {finding['why_it_matters']}"]
        lines += ["", f"What to do: {finding['remediation']}"]
        evidence = finding["evidence"]
        if evidence:
            lines += ["", "Evidence:", ""]
            if _is_effect_evidence(evidence):
                lines += _items([_md_text(note) for note in evidence["notes"]])
                lines += ["", _TABLES_IN_JSON]
            else:
                lines += _evidence_lines(evidence, limit, 4)
        if finding["references"]:
            lines += ["", "References:", "", *_items(finding["references"])]
    lines += ["", f"Rules run: {', '.join(report['rules_run'])}."]
    return lines


def _reproducibility_lines(report: dict[str, Any], experiment_id: str) -> list[str]:
    """What identifies the inputs and the reviewer, and the command that gives this memo again.

    `experiment_id` is the id as the export holds it: the report's own has its control
    characters written as escapes, and a command that names it would name another experiment.
    """
    spec, as_of = report["spec"], report["as_of"]
    lines = [
        f"- Spec: {_md_code(spec['id'])} - {_md_code(spec['title'])}",
        f"- Spec fingerprint: sha256:{spec['sha256']}",
        f"- Experiment: {_md_code(report['experiment_id'])}",
        "- Data files (SHA-256 of the bytes):",
    ]
    lines += [f"  - {name}: {file['sha256']}" for name, file in report["data"]["files"].items()]
    taken = "not known" if as_of["time"] is None else f"{as_of['time']} ({as_of['source']})"
    lines += [
        f"- Export taken: {taken}",
        f"- Referee: {report['referee_version']}, report version {report['report_version']}",
    ]
    flag = f" --as-of {as_of['time']}" if as_of["source"] == "command line" else ""
    # one word, quoted for a shell: an id with a space or a ";" would be several, and one that
    # starts with a dash would be read as an option
    holds_controls = for_line(experiment_id) != experiment_id
    typed = "ID" if holds_controls else experiment_id
    command = (
        "python -m referee review-results SPEC DATA "
        f"--experiment-id={shlex.quote(typed)}{flag} --format memo"
    )
    escaped = (
        " ID is the experiment above, whose name holds control characters (shown there as "
        "escapes): pass it exactly as the export holds it."
        if holds_controls
        else ""
    )
    manifest = (
        " The export time above comes from the manifest.json in DATA (exported_at_utc), which "
        "is not among the hashed files."
        if as_of["source"] == "manifest"
        else ""
    )
    lines += [
        "",
        f"Reproduce it from the referee/ folder with {_md_code(command)}, SPEC being the spec "
        f"with the fingerprint above and DATA the folder whose files carry these hashes.{escaped}"
        f"{manifest} The memo holds no timestamp, host or path: the same spec and data reviewed "
        "by the same Referee on one machine give the same bytes, and between machines a float "
        "may differ in its last digits.",
    ]
    return lines


def render_results_memo(report: dict[str, Any], *, limit: int = DISPLAY_ROW_LIMIT) -> str:
    """The results report as a decision memo in the analytics lab's template (design section 5).

    Its five sections, in the template's order, are filled from the report dict and from
    nothing else, so the memo cannot say what the JSON does not. It is advisory like the
    report, holds no timestamp, and cuts a list of more than `limit` rows when shown. It is
    markdown, and nothing a spec or an export holds can make a heading, a row, a line, a link,
    an image or a tag: a title, an experiment, a player and the name of an arm in a sentence are
    code spans and never start a line, and the name of an arm in a table cell or in a note of
    a rule has each of its marks escaped.
    """
    experiment_id = report["experiment_id"]
    report = _inert(report)
    spec = report["spec"]
    lines = [
        f"# Decision memo: {_md_code(spec['title'])}",
        "",
        f"A Referee results review of experiment {_md_code(report['experiment_id'])} against "
        f"spec {_md_code(spec['id'])}. Referee is advisory: it recommends, and does not approve "
        "or stop an experiment.",
    ]
    sections = (
        _paragraphs(*_decision_sentences(report)),
        _observed_lines(report, limit),
        _paragraphs(*_assumption_sentences(report)),
        _quality_lines(report, limit),
        _reproducibility_lines(report, experiment_id),
    )
    for heading, body in zip(MEMO_HEADINGS, sections, strict=True):
        lines += ["", f"## {heading}", "", *body]
    return "\n".join(lines) + "\n"
