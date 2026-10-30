"""Score Specwright on a set of cases: what a model drafts against what the documents say.

    python -m specwright.evaluate --out DIR                  # self-test: the references as replays
    python -m specwright.evaluate --out DIR --live           # a real model; needs ANTHROPIC_API_KEY

A case is one or more documents and, when someone has written it down, a reference: the draft a
careful reader would make. With a reference the score says how many stated values agree, whether
the gaps the documents leave (a missing or approximate figure) were left as gaps, and whether the
model invented a value for one. Without a reference (a real plan nobody has hand-read) only the
scores that need none are computed: the status, the quotes that were not found, the repairs used.

The references in `examples/` are written by an agent, as are the briefs: a score against them
measures agreement with an agent's reading, not accuracy against real plans. Run offline, with
each reference as the replay, the score is perfect by construction, which tests the scorer and
nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tracewright.propose.documents import load_documents

from specwright import __version__
from specwright.draft import Claim, Draft
from specwright.fields import is_numeric
from specwright.proposers import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    EFFORTS,
    AnthropicProposer,
    ReplayProposer,
)
from specwright.request import DraftRequest, ProposerError
from specwright.run import DraftResult, run_draft

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
DEFAULT_CASES = EXAMPLES / "evaluation-cases.json"
DEFAULT_TOKEN_BUDGET = 400_000


def _checked_kinds(claim: Claim) -> bool:
    """Values compared exactly: numbers, enumerations and booleans. Free text is not compared."""
    return claim.field.kind != "text"


def _same(expected: Any, got: Any) -> bool:
    if is_number(expected) and is_number(got):
        return abs(expected - got) <= 1e-9 * max(1.0, abs(expected))
    return expected == got


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def score_case(
    result: DraftResult, expected_status: str, reference: Draft | None
) -> dict[str, Any]:
    """The scores of one run. `reference` is None for a case nobody has hand-read."""
    final = result.final
    check = final.check
    spent = {"input_tokens": 0, "output_tokens": 0}
    for attempt in result.attempts:
        for key in spent:
            spent[key] += (attempt.response.usage or {}).get(key, 0)
    row: dict[str, Any] = {
        "status": result.status,
        "expected_status": expected_status,
        "status_matches": result.status == expected_status,
        "attempts": len(result.attempts),
        "repairs": result.repairs,
        "tokens": spent,
        "quotes_not_found_left": 0
        if check is None
        else sum(p.code == "QUOTE_NOT_FOUND" for p in check.blockers),
        "blockers_left": None if check is None else [p.code for p in check.blockers],
        "inferred_numbers": 0
        if check is None
        else sum(is_numeric(c.field) for c in check.inferred),
        "reference": reference is not None,
    }
    if reference is None or final.draft is None:
        return row
    live = final.draft.by_path()
    compared, agreed, mismatches = 0, 0, []
    gaps, gaps_kept, invented = 0, 0, []
    for claim in reference.claims:
        got = live.get(claim.path)
        if claim.stated and _checked_kinds(claim):
            compared += 1
            if got is not None and got.stated and _same(claim.value, got.value):
                agreed += 1
            else:
                mismatches.append(
                    {
                        "path": claim.path,
                        "expected": claim.value,
                        "got": None if got is None else got.value,
                        "got_kind": None if got is None else got.evidence.kind,
                    }
                )
        elif not claim.stated:
            gaps += 1
            if got is not None and not got.stated:
                gaps_kept += 1
            elif got is not None and got.stated:
                invented.append(
                    {"path": claim.path, "reference": claim.evidence.kind, "value": got.value}
                )
    row |= {
        "values_compared": compared,
        "values_agreed": agreed,
        "mismatches": mismatches,
        "gaps": gaps,
        "gaps_kept": gaps_kept,
        "invented": invented,
    }
    return row


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keyed = [r for r in rows if r["reference"]]
    total = lambda key: sum(r.get(key, 0) for r in keyed)  # noqa: E731
    return {
        "cases": len(rows),
        "cases_with_a_reference": len(keyed),
        "status_matches": sum(r["status_matches"] for r in rows),
        "quotes_not_found_left": sum(r["quotes_not_found_left"] for r in rows),
        "repairs": sum(r["repairs"] for r in rows),
        "input_tokens": sum(r["tokens"]["input_tokens"] for r in rows),
        "output_tokens": sum(r["tokens"]["output_tokens"] for r in rows),
        "values_agreed": total("values_agreed"),
        "values_compared": total("values_compared"),
        "gaps_kept": total("gaps_kept"),
        "gaps": total("gaps"),
        "values_invented_for_a_gap": sum(len(r.get("invented", [])) for r in keyed),
    }


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{**case, "_base": path.parent} for case in data["cases"]]


def run_cases(
    cases: list[dict[str, Any]], make_proposer, *, max_repairs: int, token_budget: int | None
) -> tuple[list[dict[str, Any]], bool]:
    """Run each case; stop starting new ones when the tokens spent pass `token_budget`."""
    rows, spent, stopped = [], 0, False
    for case in cases:
        if token_budget is not None and spent >= token_budget:
            stopped = True
            break
        base = case["_base"]
        documents = load_documents([str(base / p) for p in case["documents"]])
        reference = (
            Draft.from_json((base / case["reference"]).read_text(encoding="utf-8"))
            if case.get("reference")
            else None
        )
        try:
            result = run_draft(
                DraftRequest(documents=documents), make_proposer(case), max_repairs=max_repairs
            )
        except ProposerError as error:
            rows.append(
                {
                    "id": case["id"],
                    "error": str(error),
                    "reference": reference is not None,
                    "status_matches": False,
                    "quotes_not_found_left": 0,
                    "repairs": 0,
                    "tokens": {"input_tokens": 0, "output_tokens": 0},
                }
            )
            continue
        row = {"id": case["id"], **score_case(result, case["expected_status"], reference)}
        spent += row["tokens"]["input_tokens"] + row["tokens"]["output_tokens"]
        rows.append(row)
        print(
            f"{case['id']}: {row['status']} (expected {case['expected_status']}), "
            f"{row['repairs']} repair(s), {row['tokens']}",
            file=sys.stderr,
        )
    return rows, stopped


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Specwright evaluation ({report['mode']})",
        "",
        f"Specwright {__version__}; model {report['model']}. The references are written by an "
        "agent: agreement with them is not accuracy on real plans.",
        "",
        f"- cases: {s['cases']} ({s['cases_with_a_reference']} with a reference)",
        f"- status as expected: {s['status_matches']} of {s['cases']}",
        f"- quotes not found after the repairs: {s['quotes_not_found_left']}",
        f"- values agreeing with the reference: {s['values_agreed']} of {s['values_compared']}",
        f"- gaps left as gaps: {s['gaps_kept']} of {s['gaps']}; values invented for a gap: "
        f"{s['values_invented_for_a_gap']}",
        f"- repairs used: {s['repairs']}; tokens: {s['input_tokens']:,} in, "
        f"{s['output_tokens']:,} out",
    ]
    if report["stopped_at_budget"]:
        lines.append("- STOPPED: the token budget was reached before every case was run")
    lines += [
        "",
        "| case | status | repairs | agreed | gaps kept | invented |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["cases"]:
        if "error" in r:
            lines.append(f"| {r['id']} | ERROR: {r['error']} | | | | |")
            continue
        agreed = (
            f"{r['values_agreed']}/{r['values_compared']}" if r["reference"] else "no reference"
        )
        gaps = f"{r['gaps_kept']}/{r['gaps']}" if r["reference"] else ""
        invented = len(r.get("invented", [])) if r["reference"] else ""
        status = f"{r['status']} (expected {r['expected_status']})"
        lines.append(f"| {r['id']} | {status} | {r['repairs']} | {agreed} | {gaps} | {invented} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--only", action="append", metavar="ID", help="run only these cases")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="call a model (ANTHROPIC_API_KEY)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORTS)
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    args = parser.parse_args(argv)
    cases = [c for c in load_cases(args.cases) if not args.only or c["id"] in args.only]
    if args.live:
        proposer = AnthropicProposer(model=args.model, effort=args.effort)
        make = lambda case: proposer  # noqa: E731
        budget: int | None = args.token_budget
    else:
        make = lambda case: ReplayProposer.from_file(case["_base"] / case["reference"])  # noqa: E731
        budget = None
    rows, stopped = run_cases(cases, make, max_repairs=args.max_repairs, token_budget=budget)
    report = {
        "mode": "live" if args.live else "self-test: references as replays",
        "model": args.model if args.live else "replay",
        "stopped_at_budget": stopped,
        "summary": summarise(rows),
        "cases": rows,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evaluation.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    (args.out / "evaluation.md").write_text(markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
