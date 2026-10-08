"""The `tracewright` command line.

`review-plan` exit codes: 0 no blocker, 1 at least one blocker, 2 the plan cannot be read or is not
valid, 3 an internal error. `propose` adds 4 (the model could not be reached or declined) and uses
1 for a proposal that still has a blocking problem after repair. Keeping a crash out of 1 matters:
an uncaught Python exception exits with 1, which a pipeline would read as "the plan has a blocker".
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import get_args

from tracewright import __version__
from tracewright.importer import import_plan_tables, read_csv_file
from tracewright.loader import LoadError, load_plan, render_plan_yaml
from tracewright.plan import EventStatus, PlanError, PropertyType
from tracewright.report import plan_report, render_json, render_text
from tracewright.review import review_plan
from tracewright.sheets.google import is_sheet_source, read_google_sheet
from tracewright.sheets.layout import parse_overrides
from tracewright.sheets.table import Table, TableError

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
        help="how many times a failing proposal is sent back, 0 to 5 (default: 2)",
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
        help="turn your current tracking (a CSV file or a Google Sheet) into a plan file",
        description=(
            "Read the tracking you already have, from CSV files or Google Sheets addresses, and "
            "write a tracking plan as YAML. Column headers are recognised by their common "
            "spellings; use --map for the rest, and --dry-run to see how every column was read "
            "before anything is written. A Google Sheet shared by link needs no setup; a private "
            "one is read with an access token in the environment variable "
            "GOOGLE_SHEETS_ACCESS_TOKEN. See docs/google-sheets.md."
        ),
    )
    imp.add_argument(
        "sources", nargs="+", metavar="SOURCE",
        help="a CSV file or a https://docs.google.com/spreadsheets/d/... address; several merge",
    )
    imp.add_argument("--id", required=True, dest="plan_id", help="plan id (a-z, 0-9, _)")
    imp.add_argument("--title", required=True)
    imp.add_argument(
        "--identity-key", action="append", required=True, dest="identity_keys", metavar="NAME",
        help="a property that identifies the user or device; repeat for several",
    )
    imp.add_argument("--owner", help="default owner for every event")
    imp.add_argument(
        "--map", action="append", default=[], metavar="NAME=HEADER",
        help="read the column with this header (or column letter, @E) as NAME (event, property, "
        "type, required, pii, allowed_values, description, event_description, trigger, owner, "
        "status); repeatable",
    )
    imp.add_argument(
        "--ignore-other-columns", action="store_true",
        help="set aside columns that fit no meaning instead of refusing them",
    )
    imp.add_argument(
        "--ignore-column", action="append", default=[], metavar="HEADER|@LETTER",
        help="set this column aside even if its header is recognised; repeatable",
    )
    imp.add_argument(
        "--header-row", type=int, default=1, metavar="N",
        help="the row that holds the headers (default 1)",
    )
    imp.add_argument(
        "--fill-down", action="store_true",
        help="an empty event cell means the event of the row above (merged-cell layouts)",
    )
    imp.add_argument(
        "--tab", action="append", default=[], metavar="NAME",
        help="Google Sheets with a token only: read this tab; repeatable",
    )
    imp.add_argument(
        "--all-tabs", action="store_true", help="Google Sheets with a token only: read every tab"
    )
    imp.add_argument(
        "--type-map", action="append", default=[], metavar="WORD=TYPE",
        help="read the word WORD in a type cell as TYPE (string, integer, number, boolean, "
        "timestamp, enum); repeatable",
    )
    imp.add_argument(
        "--status-map", action="append", default=[], metavar="WORD=STATUS",
        help="read the word WORD in a status cell as active, planned or deprecated; repeatable",
    )
    imp.add_argument(
        "--dry-run", action="store_true",
        help="show how the columns were read and what would be imported; write nothing",
    )
    imp.add_argument("--out", metavar="FILE", help="write here instead of standard output")
    imp.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    return parser


def _out_problem(out: Path) -> str | None:
    """Why --out cannot be written, found before any paid model call; None when it can."""
    probe = out
    while not probe.exists() and not probe.is_symlink():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    if not probe.is_dir():
        return f"{probe} is not a directory"
    if not os.access(probe, os.W_OK | os.X_OK):
        return f"{probe} is not writable"
    return None


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


def _word_map(pairs: list[str], flag: str, allowed: tuple[str, ...]) -> dict[str, str]:
    """`--type-map Word=string` pairs as a dict. Raises TableError for a bad one."""
    out: dict[str, str] = {}
    for pair in pairs:
        word, sep, value = pair.partition("=")
        word, value = word.strip(), value.strip()
        if not sep or not word or value not in allowed:
            raise TableError(
                f"{flag} {pair!r}: write it as WORD=VALUE, with VALUE one of {list(allowed)}"
            )
        out[word] = value
    return out


def _read_sources(args: argparse.Namespace) -> tuple[list[Table], list[str]]:
    tables: list[Table] = []
    notes: list[str] = []
    for source in args.sources:
        if is_sheet_source(source):
            found, more = read_google_sheet(
                source, tabs=args.tab, all_tabs=args.all_tabs, header_row=args.header_row
            )
            tables.extend(found)
            notes.extend(more)
        else:
            if args.tab or args.all_tabs:
                raise TableError(f"--tab and --all-tabs are for Google Sheets, not for {source}")
            tables.append(read_csv_file(source, args.header_row))
    return tables, notes


def _import_plan(args: argparse.Namespace) -> int:
    try:
        overrides = parse_overrides(args.map)
        type_map = _word_map(args.type_map, "--type-map", get_args(PropertyType))
        status_map = _word_map(args.status_map, "--status-map", get_args(EventStatus))
        tables, notes = _read_sources(args)
        result = import_plan_tables(
            tables,
            plan_id=args.plan_id,
            title=args.title,
            identity_keys=args.identity_keys,
            owner=args.owner,
            overrides=overrides,
            ignore_other_columns=args.ignore_other_columns,
            ignore_columns=args.ignore_column,
            fill_down=args.fill_down,
            type_map=type_map,
            status_map=status_map,
        )
    except TableError as error:  # CSV, column mapping and Google Sheets problems alike
        print(f"tracewright: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except PlanError as error:
        print(_plan_error(", ".join(args.sources), error), file=sys.stderr)
        return EXIT_UNREADABLE
    for line in (*result.mapping, *notes, *result.notes):
        print(line if line.startswith(" ") else f"tracewright: {line}", file=sys.stderr)
    plan = result.plan
    properties = sum(len(e.properties) for e in plan.events)
    events = f"{len(plan.events)} event{'' if len(plan.events) == 1 else 's'}"
    summary = f"{events}, {properties} propert{'y' if properties == 1 else 'ies'}"
    if args.dry_run:
        print("how the cells were read (name:type, * required, ! personal data):")
        print("\n".join(result.preview))
        print(f"dry run: would import {summary}; nothing written")
        return EXIT_OK
    print(f"tracewright: read {summary}", file=sys.stderr)
    text = render_plan_yaml(plan)
    if args.out:
        target = Path(args.out)
        if (target.exists() or target.is_symlink()) and not args.force:
            print(
                f"tracewright: error: {target} already exists; use --force to overwrite it, "
                "or choose another --out",
                file=sys.stderr,
            )
            return EXIT_UNREADABLE
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
    problem = _out_problem(out)
    if problem:
        print(f"tracewright: error: cannot write to {out}: {problem}", file=sys.stderr)
        return EXIT_UNREADABLE
    clashes = [
        name for name in OUTPUT_FILES if (out / name).exists() or (out / name).is_symlink()
    ]
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
    except ProposerError as error:
        # A replay file that cannot be read, like any other unreadable input, is a usage error.
        print(f"tracewright: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE

    def report_attempt(attempt) -> None:
        usage = attempt.response.usage
        extra = f" ({usage['input_tokens']:,} in, {usage['output_tokens']:,} out)" if usage else ""
        print(f"attempt {attempt.number}: {len(attempt.feedback_sent)} problem(s){extra}",
              file=sys.stderr)

    try:
        result = run_proposal(
            ProposalRequest(documents=documents, plan=plan),
            proposer,
            max_repairs=args.max_repairs,
            owner=args.owner,
            on_attempt=report_attempt,
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
        written, removed = [], []
        for name, content in files.items():
            if content is not None:
                (out / name).write_text(content, encoding="utf-8")
                written.append(name)
        # With --force the directory may hold files of an earlier run. The ones this run did not
        # produce would sit next to a report that says they were not written, so they go.
        for name in files:
            if name not in written and ((out / name).exists() or (out / name).is_symlink()):
                (out / name).unlink()
                removed.append(name)
    except OSError as error:
        print(f"tracewright: error: cannot write to {out}: {error.strerror or error}",
              file=sys.stderr)
        return EXIT_UNREADABLE

    if removed:
        print(f"removed {', '.join(removed)} left over from an earlier run", file=sys.stderr)
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
