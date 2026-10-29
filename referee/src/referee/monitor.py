"""The monitor: what a run of `review-results --mode monitor` says about an experiment still
running (design section 27).

A results review of an unfinished experiment is `invalid` before anything else is read, because
RES-002 (too few players) and RES-003 (too short) block until the experiment ends. The monitor
asks other questions: how far has the experiment got, is the data healthy, are the guardrails
holding, and what does the primary metric look like so far. Its status words are its own,
`on_track`, `attention` and `stop_for_cause`, and are not the verdicts of a results review.

Three rules govern it (design section 27):
- unfinished is not a fault: RES-002 and RES-003 are progress lines here, never a status;
- a declared metric is never skipped silently: the ledger lists each with its role and whether it
  was read;
- an interval read before the planned end of a fixed-horizon design is not a decision, and a
  guardrail read at an interim look is never a stop: until the looks have an error budget it is
  `attention` with its interval and its number of players.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from referee import __version__
from referee.data import ExperimentData
from referee.findings import Finding
from referee.report import REPORT_VERSION, _as_of, _counts, _finding_dicts, _inert
from referee.results import METRICS, ResultsContext, effect_table
from referee.review import review_context
from referee.rules import RESULTS_RULES
from referee.rules.guardrails import guardrail_report
from referee.spec import ExperimentSpec

STATUSES = ("on_track", "attention", "stop_for_cause")

# The rules the monitor runs. RES-002 and RES-003 are read for their numbers, never for a status.
# RES-007 (the cohort test belongs at the planned end, design section 22.3) and RES-008 (it
# describes a finished sample) are not run.
_MONITOR_RULES = frozenset(
    {"RES-001", "RES-002", "RES-003", "RES-004", "RES-011", "RES-012", "RES-013"}
)
_PROGRESS_RULES = frozenset({"RES-002", "RES-003"})
_STOPS = frozenset({"RES-001", "RES-012"})  # a blocker of these is a stop for cause
_NOT_RUN = {
    "RES-007": "the cohort test belongs at the planned end (design section 22.3)",
    "RES-008": "it describes a finished sample",
}
_P_VALUE_KEYS = ("p_value", "adjusted_p_value")
_EFFECT_LABEL = (
    "an interim reading: an interval from a design that is read once, at its planned end. "
    "It is not a decision and no p value is shown."
)
_SEQUENTIAL_LABEL = (
    " The spec declares a sequential stopping rule, which Referee cannot check: nothing here "
    "validates repeated looks."
)


def metric_ledger(spec: ExperimentSpec) -> list[dict[str, Any]]:
    """Every metric the spec declares, with its role and whether the export reader can read it.

    This is the reading by name and kind that `ResultsContext` makes (design section 21.3), so
    that a metric it would refuse is listed here with the reason instead.
    """
    declared = [("primary", spec.primary_metric)] + [("guardrail", g) for g in spec.guardrails]
    ledger = []
    for role, metric in declared:
        entry: dict[str, Any] = {"role": role, "name": metric.name, "kind": metric.kind}
        known = METRICS.get(metric.name)
        if known is None:
            entry |= {
                "evaluated": False,
                "reason": "not_in_export",
                "detail": f"the export reader holds only: {', '.join(METRICS)}",
            }
        elif metric.kind == "ratio":
            entry |= {
                "evaluated": False,
                "reason": "kind_unsupported",
                "detail": "a ratio metric needs the delta method, which is not built",
            }
        elif metric.kind != known.kind:
            entry |= {
                "evaluated": False,
                "reason": "kind_mismatch",
                "detail": f"{metric.kind} in the spec, {known.kind} in the export",
            }
        else:
            entry |= {"evaluated": True, "reason": None, "detail": None}
        ledger.append(entry)
    return ledger


def readable_spec(spec: ExperimentSpec, ledger: Sequence[dict[str, Any]]) -> ExperimentSpec:
    """The spec without the guardrails the ledger could not read."""
    unread = {e["name"] for e in ledger if e["role"] == "guardrail" and not e["evaluated"]}
    return replace(spec, guardrails=tuple(g for g in spec.guardrails if g.name not in unread))


def monitor_rules() -> list:
    return [rule for rule in RESULTS_RULES if rule.id in _MONITOR_RULES]


def _progress(
    context: ResultsContext, findings: dict[str, Finding], left_out: dict[str, int]
) -> dict[str, Any]:
    spec = context.spec
    analysed = context.count_by_arm(context.analysed)
    if context.plan is None:
        players: dict[str, Any] = {"unattainable": True, "reason": context.power_error}
    else:
        required = {arm: context.required_n(arm) for arm in context.arm_names}
        players = {
            arm: {
                "analysed": analysed[arm],
                "closed_window": analysed[arm] - left_out[arm],
                "required": required[arm],
                "missing": max(0, (required[arm] or 0) - analysed[arm]),
            }
            for arm in context.arm_names
        }
    minimum = spec.design.min_duration_days
    return {
        "players": players,
        "days": {
            "observed": context.observed_days,
            "min_duration_days": minimum,
            "planned_duration_days": spec.design.planned_duration_days,
            "min_duration_reached": context.observed_days >= minimum,
            "days_to_minimum": max(0, minimum - context.observed_days),
        },
        "blocking_in_a_review": sorted(r for r in _PROGRESS_RULES if r in findings),
    }


def _primary(context: ResultsContext, findings: dict[str, Finding]) -> dict[str, Any]:
    table = effect_table(context)
    arms = [{k: v for k, v in row.items() if k not in _P_VALUE_KEYS} for row in table["arms"]]
    unreadable = sorted(
        rule
        for rule in ("RES-001", "RES-012")
        if rule in findings and findings[rule].severity == "blocker"
    )
    label = _EFFECT_LABEL
    if context.spec.procedure.stopping_rule == "sequential":
        label += _SEQUENTIAL_LABEL
    return {
        "metric": table["metric"],
        "kind": table["kind"],
        "population": table["population"],
        "left_out": table["left_out"],
        "label": label,
        "readable": not unreadable,
        "unreadable_because": unreadable,
        "arms": arms,
    }


def _guardrails(context: ResultsContext) -> list[dict[str, Any]]:
    """Each arm against control on each guardrail, with the stricter reference's tier. A breach,
    shown or possible, is `attention` here and never a stop (design section 27)."""
    rows = []
    for test in guardrail_report(context)["tests"]:
        decided = [
            ref
            for ref in test["references"].values()
            if ref["evaluated"] and ref["tier"] == test["tier"]
        ]
        harm = decided[0] if decided else None
        rows.append(
            {
                "arm": test["arm"],
                "guardrail": test["guardrail"],
                "tolerance": test["tolerance"],
                "n": test["n"],
                "tier": test["tier"],
                "status": "attention"
                if test["tier"] in ("shown", "possible")
                else ("not_evaluated" if test["tier"] is None else "within"),
                "harm": harm["harm"] if harm else None,
                "reasons": [
                    ref["reason"] for ref in test["references"].values() if not ref["evaluated"]
                ],
            }
        )
    return rows


def _unevaluated_in_run(
    ledger: list[dict[str, Any]], primary: dict[str, Any], guardrails: list
) -> None:
    """Mark in the ledger the metrics that the export reader holds but the data did not allow:
    `window_not_matured` when every analysed player's outcome window is still open, else
    `no_estimate` with the reasons the statistics gave."""
    estimated = [row for row in primary["arms"] if "error" not in row]
    nobody_matured = sum(primary["left_out"].values()) > 0 and all(
        row.get("n_treatment", 0) == 0 for row in primary["arms"]
    )

    def unread(entry: dict[str, Any], detail: str) -> None:
        if nobody_matured:
            entry |= {
                "evaluated": False,
                "reason": "window_not_matured",
                "detail": "every analysed player's seven-day outcome window is still open",
            }
        else:
            entry |= {"evaluated": False, "reason": "no_estimate", "detail": detail}

    for entry in ledger:
        if entry["role"] == "primary" and entry["evaluated"] and not estimated:
            errors = sorted({row["error"] for row in primary["arms"] if "error" in row})
            unread(entry, "; ".join(errors))
        if entry["role"] == "guardrail" and entry["evaluated"]:
            rows = [r for r in guardrails if r["guardrail"] == entry["name"]]
            if rows and all(r["tier"] is None for r in rows):
                reasons = sorted({reason for r in rows for reason in r["reasons"] if reason})
                unread(entry, "; ".join(reasons))


def monitor_report(
    spec: ExperimentSpec,
    data: ExperimentData,
    *,
    file_hashes: dict[str, str],
    as_of_source: str | None,
) -> dict[str, Any]:
    """The monitor's report for `spec` and `data`, or `ResultsError` if the data cannot be read
    against the spec. The primary metric must be one the export reader holds: `metric_ledger`
    says whether it is, and the command refuses before this is called if it is not."""
    ledger = metric_ledger(spec)
    context = ResultsContext.of(readable_spec(spec, ledger), data)
    review = review_context(context, rules=monitor_rules())
    found = {finding.rule_id: finding for finding in review.findings}
    primary = _primary(context, found)
    guardrails = _guardrails(context)
    _unevaluated_in_run(ledger, primary, guardrails)

    reasons: list[dict[str, str]] = []
    stop = False
    for rule_id in ("RES-001", "RES-011", "RES-012", "RES-013"):
        finding = found.get(rule_id)
        if finding is None:
            continue
        stops = rule_id in _STOPS and finding.severity == "blocker"
        stop = stop or stops
        reasons.append(
            {
                "rule_id": rule_id,
                "status": "stop_for_cause" if stops else "attention",
                "text": finding.title,
            }
        )
    for row in guardrails:
        if row["status"] == "attention":
            reasons.append(
                {
                    "rule_id": "RES-004",
                    "status": "attention",
                    "text": (
                        f"guardrail {row['guardrail']} in {row['arm']} is {row['tier']} "
                        "beyond its tolerance"
                    ),
                }
            )
    for entry in ledger:
        if not entry["evaluated"]:
            reasons.append(
                {
                    "rule_id": "ledger",
                    "status": "attention",
                    "text": (
                        f"{entry['role']} metric {entry['name']} was not read ({entry['reason']})"
                    ),
                }
            )
    status = "stop_for_cause" if stop else ("attention" if reasons else "on_track")
    shown = [f for f in review.findings if f.rule_id not in _PROGRESS_RULES]
    return {
        "report_version": REPORT_VERSION,
        "kind": "monitor",
        "referee_version": __version__,
        "spec": {"id": spec.id, "title": spec.title, "sha256": spec.sha256()},
        "experiment_id": review.experiment_id,
        "data": {"files": {name: {"sha256": digest} for name, digest in file_hashes.items()}},
        "as_of": _as_of(context, as_of_source),
        "status": status,
        "reasons": reasons,
        "progress": _progress(context, found, primary["left_out"]),
        "ledger": ledger,
        "primary_metric": primary,
        "guardrails": guardrails,
        "rules_run": list(review.rules_run),
        "rules_not_run": dict(_NOT_RUN),
        "counts": _counts(shown),
        "findings": _finding_dicts(shown),
        "note": (
            "The status words are the monitor's own and are not the verdicts of review-results. "
            "RES-002 and RES-003 are progress here, not a status."
        ),
    }


def render_monitor_text(report: dict[str, Any]) -> str:
    """The monitor report as plain text for a person to read."""
    report = _inert(report)
    spec, progress, as_of = report["spec"], report["progress"], report["as_of"]
    lines = [
        "Referee monitor",
        f"Spec:       {spec['id']} - {spec['title']}",
        f"Experiment: {report['experiment_id']}",
        f"Referee:    {report['referee_version']}",
        "",
        f"Status: {report['status'].upper()}",
    ]
    lines += [f"  {r['status']}: {r['rule_id']}: {r['text']}" for r in report["reasons"]]
    taken = "not known" if as_of["time"] is None else f"{as_of['time']} ({as_of['source']})"
    lines += ["", f"Export taken: {taken}."]
    if as_of["interim"]:
        lines.append(f"Interim: the planned end of the experiment is {as_of['planned_end']}.")
    days = progress["days"]
    lines += [
        "",
        "Progress",
        f"  days observed {days['observed']} of a registered minimum of {days['min_duration_days']}"
        f" (planned {days['planned_duration_days']}); "
        + (
            "minimum reached."
            if days["min_duration_reached"]
            else f"{days['days_to_minimum']} to go."
        ),
    ]
    players = progress["players"]
    if players.get("unattainable"):
        lines.append(f"  players: the design cannot be sized ({players['reason']}).")
    else:
        for arm, row in players.items():
            lines.append(
                f"  {arm}: {row['analysed']} analysed ({row['closed_window']} with a closed "
                f"outcome window) of {row['required']} registered ({row['missing']} missing)"
            )
    lines += ["", "Metrics declared (role, name, read)"]
    for entry in report["ledger"]:
        said = "read" if entry["evaluated"] else f"NOT read: {entry['reason']} - {entry['detail']}"
        lines.append(f"  {entry['role']:9} {entry['name']}: {said}")
    primary = report["primary_metric"]
    lines += ["", f"Primary metric {primary['metric']} (so far, {primary['population']})"]
    lines.append("  " + primary["label"])
    if not primary["readable"]:
        lines.append("  NOT TO BE READ: " + ", ".join(primary["unreadable_because"]) + " blocks.")
    for row in primary["arms"]:
        if "error" in row:
            lines.append(f"  {row['arm']}: no estimate ({row['error']})")
        else:
            lines.append(
                f"  {row['arm']}: n {row['n_treatment']} vs {row['n_control']}, difference "
                f"{row['difference']} [{row['ci_low']}, {row['ci_high']}]"
            )
    lines += ["", "Guardrails"]
    if not report["guardrails"]:
        lines.append("  none read")
    for row in report["guardrails"]:
        harm = row["harm"]
        interval = (
            ""
            if harm is None
            else (
                f", harm {harm['point']} [{harm['low']}, {harm['high']}] "
                f"against a tolerance of {row['tolerance']}"
            )
        )
        lines.append(
            f"  {row['guardrail']} in {row['arm']}: {row['status']} ({row['tier']}), "
            f"n {row['n']['arm']} vs {row['n']['control']}{interval}"
        )
    lines += ["", "Rules run: " + ", ".join(report["rules_run"])]
    lines += [f"Not run: {rule}: {why}" for rule, why in report["rules_not_run"].items()]
    lines += ["", report["note"]]
    return "\n".join(lines) + "\n"
