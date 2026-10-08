"""The `tracewright` command line.

`review-plan` exit codes: 0 no blocker, 1 at least one blocker, 2 the plan cannot be read or is not
valid, 3 an internal error. `propose` adds 4 (the model could not be reached or declined) and uses
1 for a proposal that still has a blocking problem after repair. Keeping a crash out of 1 matters:
an uncaught Python exception exits with 1, which a pipeline would read as "the plan has a blocker".
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from tracewright import __version__
from tracewright.importer import CsvImportError, import_plan_csv
from tracewright.loader import LoadError, load_plan, render_plan_yaml
from tracewright.plan import PlanError
from tracewright.report import plan_report, render_json, render_text
from tracewright.review import review_plan

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_UNREADABLE = 2
EXIT_INTERNAL = 3
EXIT_MODEL = 4

OUTPUT_FILES = ("proposal.md", "proposal.json", "merged-plan.yaml", "plan.diff")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracewright",
        description="Propose and review product tracking. Advisory only.",
    )
    parser.add_argument("--version", action="version", version=f"tracewright {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    review = commands.add_parser(
        "review-plan",
        help="review a tracking plan against the rule catalogue",
        description=(
            "Review a tracking plan. Exit status: 0 no blocker found, 1 at least one blocker, "
            "2 the plan cannot be read or is not valid, 3 internal error."
        ),
    )
    review.add_argument("plan", help="path to the tracking plan (YAML)")
    review.add_argument("--format", choices=("text", "json"), default="text")

    propose = commands.add_parser(
        "propose",
        help="propose the tracking for a new feature from its documents",
        description=(
            "Read documents about a feature (a game design document, a spec) and, optionally, "
            "the existing tracking plan, and propose the events, properties, types and reasons. "
            "The proposal is checked by deterministic rules and sent back for repair if it fails. "
            "Needs ANTHROPIC_API_KEY (or `ant auth login`) unless --replay is used. "
            "Exit status: 0 no blocking problem, 1 a blocking problem remains, 2 an input cannot "
            "be read, 3 internal error, 4 the model could not be reached or declined."
        ),
    )
    propose.add_argument(
        "--doc", action="append", required=True, metavar="PATH",
        help="a document about the feature (.md .txt .pdf ...); repeat for several",
    )
    propose.add_argument("--plan", metavar="PATH", help="the existing tracking plan (YAML)")
    propose.add_argument("--out", required=True, metavar="DIR", help="where to write the results")
    propose.add_argument("--owner", help="owner to record on the proposed events")
    propose.add_argument("--model", default=None, help="model id (default: claude-opus-5-5)")
    propose.add_argument(
        "--effort", default=None, choices=("low", "medium", "high", "xhigh", "max"),
        help="how hard the model thinks (default: high)",
    )
    propose.add_argument(
        "--max-repairs", type=int, default=2, metavar="N",
        help="how many times a failing proposal is sent back (default: 2)",
    )
    propose.add_argument(
        "--replay", metavar="FILE",
        help="use saved responses from this JSON file instead of calling a model",
    )
    propose.add_argument(
        "--force", action="store_true", help="overwrite files that already exist in --out"
    )

    imp = commands.add_parser(
        "import-plan",
        help="turn a CSV of your current tracking into a plan file",
        description="Read a CSV of events and properties and write a tracking plan as YAML.",
    )
    imp.add_argument("csv", help="path to the CSV (see docs/import-csv.md for the columns)")
    imp.add_argument("--id", required=True, dest="plan_id", help="plan id (a-z, 0-9, _)")
    imp.add_argument("--title", required=True)
    imp.add_argument(
        "--identity-key", action="append", required=True, dest="identity_keys", metavar="NAME",
        help="a property that identifies the user or device; repeat for several",
    )
    imp.add_argument("--owner", help="default owner for every event")
    imp.add_argument("--out", metavar="FILE", help="write here instead of standard output")
    return parser


def _plan_error(path: str, error: PlanError) -> str:
    count = len(error.violations)
    noun = "violation" if count == 1 else "violations"
    lines = [f"tracewright: error: {path} is not a valid tracking plan ({count} {noun}):"]
    lines += [f"  - {violation}" for violation in error.violations]
    return "\n".join(lines)


def _load(path: str):
    """Load a plan, or return (None, exit status) after printing why not."""
    try:
        return load_plan(path), EXIT_OK
    except LoadError as error:
        print(f"tracewright: error: {error}", file=sys.stderr)
    except PlanError as error:
        print(_plan_error(path, error), file=sys.stderr)
    return None, EXIT_UNREADABLE


def _review_plan(args: argparse.Namespace) -> int:
    plan, status = _load(args.plan)
    if plan is None:
        return status
    report = plan_report(plan, review_plan(plan))
    render = render_json if args.format == "json" else render_text
    sys.stdout.write(render(report))
    return EXIT_BLOCKED if report["blocking_rule_ids"] else EXIT_OK


def _import_plan(args: argparse.Namespace) -> int:
    try:
        plan = import_plan_csv(
            args.csv,
            plan_id=args.plan_id,
            title=args.title,
            identity_keys=args.identity_keys,
            owner=args.owner,
        )
    except CsvImportError as error:
        print(f"tracewright: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except PlanError as error:
        print(_plan_error(args.csv, error), file=sys.stderr)
        return EXIT_UNREADABLE
    text = render_plan_yaml(plan)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as error:
            print(f"tracewright: error: {args.out}: {error.strerror or error}", file=sys.stderr)
            return EXIT_UNREADABLE
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _propose(args: argparse.Namespace) -> int:
    # Imported here so `review-plan` works without the optional model dependency.
    from tracewright.propose.documents import DocumentError, load_documents
    from tracewright.propose.proposers import (
        DEFAULT_EFFORT,
        DEFAULT_MODEL,
        AnthropicProposer,
        ReplayProposer,
    )
    from tracewright.propose.render import (
        merged_plan_yaml,
        plan_diff,
        render_markdown,
    )
    from tracewright.propose.render import (
        render_json as render_proposal_json,
    )
    from tracewright.propose.request import ProposalRequest, ProposerError
    from tracewright.propose.run import run_proposal

    if args.max_repairs < 0 or args.max_repairs > 5:
        print("tracewright: error: --max-repairs must be between 0 and 5", file=sys.stderr)
        return EXIT_UNREADABLE
    out = Path(args.out)
    if out.exists() and not out.is_dir():
        print(f"tracewright: error: --out {out} exists and is not a directory", file=sys.stderr)
        return EXIT_UNREADABLE
    clashes = [name for name in OUTPUT_FILES if (out / name).exists()]
    if clashes and not args.force:
        print(
            f"tracewright: error: {out} already holds {clashes}; use --force to overwrite, "
            "or choose another --out",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE
    try:
        documents = load_documents(args.doc)
    except DocumentError as error:
        print(f"tracewright: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    plan = None
    if args.plan:
        plan, status = _load(args.plan)
        if plan is None:
            return status

    try:
        proposer = (
            ReplayProposer.from_file(args.replay)
            if args.replay
            else AnthropicProposer(
                model=args.model or DEFAULT_MODEL, effort=args.effort or DEFAULT_EFFORT
            )
        )
        result = run_proposal(
            ProposalRequest(documents=documents, plan=plan),
            proposer,
            max_repairs=args.max_repairs,
            owner=args.owner,
        )
    except ProposerError as error:
        print(f"tracewright: error: {error}", file=sys.stderr)
        return EXIT_MODEL

    try:
        out.mkdir(parents=True, exist_ok=True)
        files = {
            "proposal.md": render_markdown(result),
            "proposal.json": render_proposal_json(result),
            "merged-plan.yaml": merged_plan_yaml(result),
            "plan.diff": plan_diff(result),
        }
        written = []
        for name, content in files.items():
            if content is not None:
                (out / name).write_text(content, encoding="utf-8")
                written.append(name)
    except OSError as error:
        print(f"tracewright: error: cannot write to {out}: {error.strerror or error}",
              file=sys.stderr)
        return EXIT_UNREADABLE

    for attempt in result.attempts:
        usage = attempt.response.usage
        extra = f" ({usage['input_tokens']:,} in, {usage['output_tokens']:,} out)" if usage else ""
        print(f"attempt {attempt.number}: {len(attempt.feedback_sent)} problem(s){extra}",
              file=sys.stderr)
    print(f"status: {result.status}; wrote {', '.join(written)} to {out}")
    return EXIT_OK if result.status == "ok" else EXIT_BLOCKED


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status. Never raises."""
    try:
        args = build_parser().parse_args(argv)
        if args.command == "review-plan":
            return _review_plan(args)
        if args.command == "import-plan":
            return _import_plan(args)
        return _propose(args)
    except SystemExit as exit_request:  # argparse: usage errors, --help, --version
        return exit_request.code if isinstance(exit_request.code, int) else EXIT_UNREADABLE
    except Exception:
        traceback.print_exc()
        print("tracewright: error: internal error; this is a bug in Tracewright", file=sys.stderr)
        return EXIT_INTERNAL
