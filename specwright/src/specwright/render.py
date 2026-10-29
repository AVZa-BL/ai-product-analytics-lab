"""The outputs of a run: a report for people, the same for machines, and the spec itself.

Everything a document or the model wrote reaches the report through `code`, which writes control
characters as escapes and puts the text in a code span that nothing inside it can close, so a
document cannot make a heading, a list item or a link in the report.
"""

from __future__ import annotations

import json
import re
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

from specwright import __version__
from specwright.check import CheckResult
from specwright.draft import Claim
from specwright.fields import assemble
from specwright.run import Attempt, DraftResult

REPORT = "report.md"
DRAFT_JSON = "draft.json"
SPEC_FILE = "draft-spec.yaml"
PARTIAL_FILE = "partial-draft.yaml"
OUTPUT_FILES = (REPORT, DRAFT_JSON, SPEC_FILE, PARTIAL_FILE)

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁠-⁤]")

_HEADLINES = {
    "ok": "OK: a spec was built and Referee's design rules raise no blocker.",
    "needs_answers": "NEEDS ANSWERS: the documents do not give everything a spec needs. "
    "Nothing was invented to fill the gaps.",
    "infeasible": "INFEASIBLE: the numbers the documents give cannot reach the power the spec "
    "asks for.",
    "unresolved": "UNRESOLVED: a blocker is left after the repairs. Read the problems below.",
}
CAVEATS = (
    "Passing these checks proves the draft is consistent with the documents and with Referee's "
    "design rules. It does not prove the experiment is well designed.",
    "A quote that is found proves the words are in the document, not that the model read them "
    "correctly. Check each claim against its quote.",
    "A value labelled inferred comes from the model's judgement and not from a document: confirm "
    "each one. A vague phrase that the model chose not to quote cannot be detected.",
    "Sample sizes and durations are worked out by Referee's power plan from the stated numbers, "
    "never by the model.",
)


def code(value: object) -> str:
    """`value` as one line in a code span that its own text cannot close."""
    text = _CONTROL.sub(lambda m: f"\\u{ord(m.group()):04x}", str(value))
    fence = "`" * (max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    pad = (
        " " if text.startswith("`") or text.endswith("`") or (text[:1] == text[-1:] == " ") else ""
    )
    return f"{fence}{pad}{text}{pad}{fence}"


def _claim_line(claim: Claim) -> str:
    e = claim.evidence
    source = f"quoted from {code(e.document)}: {code(e.quote)}" if e.kind == "document" else e.kind
    note = f" (note: {code(e.note)})" if e.note else ""
    return f"- {code(claim.path)} = {code(claim.value)} - {source}{note}"


def _plan_lines(check: CheckResult) -> list[str]:
    if check.plan is None:
        return (
            [f"- Referee could not size the design: {code(check.plan_error)}"]
            if check.plan_error
            else []
        )
    plan = check.plan
    lines = [
        f"- needs {plan.required_total:,} players in total "
        f"({', '.join(f'{code(n)} {u:,}' for n, u in plan.required_per_arm)}), "
        f"{plan.required_days:,} days at the daily traffic stated "
        f"({plan.required_days_whole_weeks:,} days to whole weeks)",
        f"- the planned duration delivers {plan.achievable_total:,} players",
    ]
    if plan.achievable_mde_relative is not None:
        lines.append(
            f"- the smallest relative effect that duration can power: "
            f"{plan.achievable_mde_relative:.1%}"
        )
    lines.append(f"- powered: {'yes' if plan.is_powered else 'no'}")
    return lines


def _why_infeasible(check: CheckResult) -> str:
    """The numbers behind a DES-001 blocker, from Referee's power plan."""
    if check.plan is None or check.spec is None:
        return code(check.plan_error or "Referee could not size the design")
    plan, spec = check.plan, check.spec
    reach = plan.achievable_mde_relative
    effect = (
        ""
        if reach is None
        else f"; that duration can only power a relative effect of {reach:.1%} "
        f"(the draft asks for {spec.design.mde_relative:.1%})"
    )
    return (
        f"the design needs {plan.required_total:,} players, and "
        f"{spec.design.planned_duration_days} days at {spec.population.daily_eligible_units:,} "
        f"players a day deliver {plan.achievable_total:,}{effect}. Run for "
        f"{plan.required_days:,} days, bring in more eligible players, or accept a larger "
        "effect. The numbers are the documents' own, and none was changed to make the design pass"
    )


def _attempt_lines(attempt: Attempt) -> list[str]:
    lines = [f"### Attempt {attempt.number} ({code(attempt.response.model or 'unknown model')})"]
    if attempt.parse_problems:
        lines += ["", "Not a valid draft:", *[f"- {code(p)}" for p in attempt.parse_problems]]
    elif attempt.check is not None:
        shown = [p for p in attempt.check.problems if p.severity != "info"]
        lines += [
            "",
            f"{len(attempt.check.blockers)} blocker(s), "
            f"{sum(p.severity == 'warning' for p in attempt.check.problems)} warning(s), "
            f"{len(attempt.check.questions)} question(s).",
            *[f"- {p.severity}: {code(p.line())}" for p in shown],
        ]
    lines.append("")
    lines.append(
        f"Sent back to the model: {len(attempt.feedback_sent)} problem(s)."
        if attempt.feedback_sent
        else "Nothing sent back."
    )
    return lines


def render_report(result: DraftResult) -> str:
    final = result.final
    check, status = final.check, result.status
    lines = [f"# Specwright draft: {status.replace('_', ' ')}", "", _HEADLINES[status], ""]
    lines += [f"> {c}" for c in CAVEATS[:2]] + [""]
    documents = ", ".join(code(d.name) for d in result.request.documents)
    lines += [
        f"Documents: {documents}. Attempts: {len(result.attempts)} "
        f"({result.repairs} repair round(s)).",
    ]
    if final.parse_problems or check is None:
        lines += ["", "## Problems left", *[f"- {code(p)}" for p in final.parse_problems]]
    else:
        questions = list(check.questions)
        if questions or final.draft and final.draft.open_questions:
            lines += ["", "## Questions for the analyst", ""]
            lines += [f"- {code(q.path)} ({q.kind}): {code(q.note)}" for q in questions]
            lines += [f"- {code(q)}" for q in (final.draft.open_questions if final.draft else ())]
        if status == "infeasible":
            lines += ["", "## Why it is infeasible", "", f"- {_why_infeasible(check)}"]
        if check.plan is not None or check.plan_error:
            lines += ["", "## Computed by Referee (the power plan)", "", *_plan_lines(check)]
        if final.draft is not None:
            lines += ["", "## What the draft states", ""]
            lines += [_claim_line(c) for c in final.draft.claims if c.stated]
            if check.inferred:
                lines += ["", "## Inferred values to confirm", ""]
                lines += [f"- {code(c.path)} = {code(c.value)}" for c in check.inferred]
            if final.draft.assumptions:
                lines += ["", "## Assumptions the model listed", ""]
                lines += [f"- {code(a)}" for a in final.draft.assumptions]
        if check.review is not None:
            lines += ["", "## Design review (Referee's HYP, DES and PRO rules)", ""]
            lines += [
                f"- {f.severity}: {code(f.rule_id)} {code(f.title)}. What to do: "
                f"{code(f.remediation)}"
                for f in check.review.findings
            ] or ["- no finding"]
        left = [p for p in check.problems if p.severity == "blocker" and p.code != "RULE:DES-001"]
        if left:
            lines += ["", "## Problems left", *[f"- {code(p.line())}" for p in left]]
        stated = [p for p in check.problems if p.code == "SIZE_DIFFERS"]
        if stated:
            lines += ["", "## A stated size differs from Referee's", ""]
            lines += [f"- {code(p.line())}" for p in stated]
    lines += ["", "## Attempts", ""]
    for attempt in result.attempts:
        lines += [*_attempt_lines(attempt), ""]
    lines += ["## What this does not tell you", "", *[f"- {c}" for c in CAVEATS], ""]
    lines += ["## Provenance", ""]
    lines += [
        f"- {code(d.name)}: sha256 {d.sha256}, {d.size:,} bytes" for d in result.request.documents
    ]
    lines += [f"- Specwright {__version__}, Referee {version('referee')}"]
    if check is not None and check.spec is not None:
        lines.append(f"- spec fingerprint: sha256:{check.spec.sha256()}")
    return "\n".join(lines) + "\n"


def draft_json(result: DraftResult) -> dict[str, Any]:
    final, check = result.final, result.final.check
    return {
        "report_version": 1,
        "specwright_version": __version__,
        "referee_version": version("referee"),
        "status": result.status,
        "documents": [
            {"name": d.name, "sha256": d.sha256, "bytes": d.size} for d in result.request.documents
        ],
        "attempts": [
            {
                "number": a.number,
                "model": a.response.model,
                "usage": a.response.usage,
                "parse_problems": list(a.parse_problems),
                "problems": []
                if a.check is None
                else [
                    {"code": p.code, "severity": p.severity, "path": p.path, "message": p.message}
                    for p in a.check.problems
                ],
                "feedback_sent": list(a.feedback_sent),
            }
            for a in result.attempts
        ],
        "claims": []
        if final.draft is None
        else [
            {
                "path": c.path,
                "value": c.value,
                "evidence": {
                    "kind": c.evidence.kind,
                    "document": c.evidence.document,
                    "quote": c.evidence.quote,
                    "note": c.evidence.note,
                },
            }
            for c in final.draft.claims
        ],
        "questions": []
        if check is None
        else [{"path": q.path, "kind": q.kind, "note": q.note} for q in check.questions],
        "plan": None
        if check is None or check.plan is None
        else {
            "required_total": check.plan.required_total,
            "required_per_arm": [list(x) for x in check.plan.required_per_arm],
            "required_days": check.plan.required_days,
            "required_days_whole_weeks": check.plan.required_days_whole_weeks,
            "achievable_total": check.plan.achievable_total,
            "achievable_mde_relative": check.plan.achievable_mde_relative,
            "is_powered": check.plan.is_powered,
        },
        "review": None
        if check is None or check.review is None
        else [
            {"rule_id": f.rule_id, "severity": f.severity, "title": f.title}
            for f in check.review.findings
        ],
        "spec": None if check is None else check.spec_dict,
        "spec_sha256": None if check is None or check.spec is None else check.spec.sha256(),
    }


def _yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def write_outputs(result: DraftResult, out: Path, *, force: bool) -> list[str]:
    """Write the run's files into `out`; return their names. Stale files of an earlier run in the
    same folder are removed (`force`), so the folder always matches the latest run."""
    out.mkdir(parents=True, exist_ok=True)
    if not force and any((out / name).exists() for name in OUTPUT_FILES):
        raise FileExistsError(f"{out} already holds results; use --force to replace them")
    for name in OUTPUT_FILES:
        (out / name).unlink(missing_ok=True)
    written = [REPORT, DRAFT_JSON]
    (out / REPORT).write_text(render_report(result), encoding="utf-8")
    (out / DRAFT_JSON).write_text(
        json.dumps(draft_json(result), indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    check = result.final.check
    if check is not None and check.spec is not None and result.status in ("ok", "infeasible"):
        header = (
            "# A draft. Every value is the model's reading of the documents: check each one\n"
            "# against report.md, and confirm the values it lists as inferred, before "
            "registering this.\n"
        )
        (out / SPEC_FILE).write_text(header + _yaml(check.spec_dict or {}), encoding="utf-8")
        written.append(SPEC_FILE)
    elif check is not None:
        notes = "".join(
            f"# QUESTION {q.path}: {_CONTROL.sub(' ', q.note)}\n" for q in check.questions
        )
        header = "# Not a valid spec: the stated fields so far, and what is still to be answered.\n"
        (out / PARTIAL_FILE).write_text(
            header + notes + _yaml(assemble(check.values)), encoding="utf-8"
        )
        written.append(PARTIAL_FILE)
    return written
