"""The `referee` command line.

Exit codes of `review-design` and `review-results`: 0 when the review finds no blocker, 1 when
it finds one, 2 when the spec or the data cannot be read, is not valid or cannot be reviewed
together (an unknown experiment, a metric the export does not hold, a time that is not a UTC
instant), and 3 when Referee itself fails. Keeping a crash out of 1 matters: an uncaught Python
exception exits with 1, which a pipeline would read as "the design has a blocker". A warning
never changes the exit status; the results verdict `caution` exits 0 and says so in the report.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from referee import __version__
from referee.data import (
    DataError,
    export_file_hashes,
    list_experiment_ids,
    load_export,
    parse_utc,
)
from referee.display import cap_listing, for_line
from referee.loader import LoadError, load_spec
from referee.monitor import monitor_report, render_monitor_text
from referee.report import (
    design_report,
    render_json,
    render_results_memo,
    render_results_text,
    render_text,
    results_report,
)
from referee.results import ResultsContext, ResultsError
from referee.review import origin_sensitivity, review_context, review_design
from referee.spec import ExperimentSpec, SpecError

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_UNREADABLE = 2
EXIT_INTERNAL = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="referee",
        description="Deterministic review of A/B/n experiment designs. Advisory only.",
    )
    parser.add_argument("--version", action="version", version=f"referee {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    review = commands.add_parser(
        "review-design",
        help="review the design of an experiment spec",
        description=(
            "Review an experiment spec before launch. Exit status: 0 no blocker found, "
            "1 at least one blocker, 2 the spec cannot be read or is not valid, "
            "3 internal error."
        ),
    )
    review.add_argument("spec", help="path to the experiment spec (YAML)")
    review.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default: text)"
    )

    results = commands.add_parser(
        "review-results",
        help="review an experiment's exported data against its spec",
        description=(
            "Review the data of an experiment against its spec. Exit status: 0 no blocker "
            "found (the verdict may still be caution), 1 at least one blocker (verdict invalid), "
            "2 the spec or the data cannot be read or reviewed, 3 internal error."
        ),
    )
    results.add_argument("spec", help="path to the experiment spec (YAML)")
    results.add_argument(
        "data",
        help=(
            "folder with experiment_assignments.csv, experiment_exposures.csv and "
            "experiment_outcomes.csv, and optionally manifest.json"
        ),
    )
    results.add_argument(
        "--experiment-id",
        help="the experiment to review (when it is left out, the ones in the export are listed)",
    )
    results.add_argument(
        "--as-of",
        metavar="TIME",
        help=(
            "when the export was taken, as an ISO 8601 time in UTC (for example "
            "2026-06-30T00:00:00Z); it replaces the time in manifest.json"
        ),
    )
    results.add_argument(
        "--mode",
        choices=("review", "monitor"),
        default="review",
        help=(
            "review (default) judges the experiment as finished; monitor reads one that is still "
            "running and says on_track, attention or stop_for_cause (no memo; exit status 1 only "
            "for stop_for_cause)"
        ),
    )
    results.add_argument(
        "--format",
        choices=("text", "json", "memo"),
        default="text",
        help=(
            "output format (default: text); memo is a decision memo in markdown, in the "
            "analytics lab's template"
        ),
    )
    return parser


def _complain(*lines: str) -> None:
    """Say on stderr why the input cannot be used, one line for each argument. What a file or a
    command line puts into a line is written as an escape where it could act on the terminal,
    and a newline in it cannot start a line of its own."""
    print("\n".join(for_line(line) for line in lines), file=sys.stderr)


def _spec_error(path: str, error: SpecError) -> list[str]:
    count = len(error.violations)
    noun = "violation" if count == 1 else "violations"
    lines = [f"referee: error: {path} is not a valid experiment spec ({count} {noun}):"]
    lines += [f"  - {violation}" for violation in error.violations]
    return lines


def _read_spec(path: str) -> ExperimentSpec | None:
    """The spec at `path`, or None after saying on stderr why it cannot be used."""
    try:
        return load_spec(path)
    except LoadError as error:
        _complain(f"referee: error: {error}")
    except SpecError as error:
        _complain(*_spec_error(path, error))
    return None


def _data_error(error: DataError) -> list[str]:
    """Every problem of an export that cannot be read, as many as a person can read."""
    noun = "problem" if error.total == 1 else "problems"
    listing = cap_listing(error.problems)
    lines = [f"referee: error: the experiment export has {error.total:,} {noun}:"]
    lines += [f"  - {problem}" for problem in listing.shown]
    if error.total > len(listing.shown):
        lines.append(f"  ... and {error.total - len(listing.shown):,} more")
    return lines


def _review_design(path: str, output_format: str) -> int:
    spec = _read_spec(path)
    if spec is None:
        return EXIT_UNREADABLE

    report = design_report(spec, review_design(spec))
    render = render_json if output_format == "json" else render_text
    sys.stdout.write(render(report))
    return EXIT_BLOCKED if report["blocking_rule_ids"] else EXIT_OK


def _review_results(args: argparse.Namespace) -> int:
    spec = _read_spec(args.spec)
    if spec is None:
        return EXIT_UNREADABLE
    if args.mode == "monitor":
        return _monitor_results(args, spec)
    as_of: datetime | None = None
    if args.as_of is not None:
        try:
            as_of = parse_utc(args.as_of)
        except ValueError as problem:
            _complain(f"referee: error: --as-of {problem}")
            return EXIT_UNREADABLE

    try:
        if args.experiment_id is None:
            ids = ", ".join(list_experiment_ids(args.data)) or "none"
            _complain(f"referee: error: --experiment-id is required; the export holds: {ids}")
            return EXIT_UNREADABLE
        data = load_export(args.data, args.experiment_id)
        hashes = export_file_hashes(args.data)  # of the files just read, before the long part
        if as_of is not None:
            data = replace(data, exported_at=as_of)
        context = ResultsContext.of(spec, data)
        review = review_context(context)
        sensitivity = origin_sensitivity(spec, data, review)
        if context.secondary:
            listed = ", ".join(
                for_line(m.name) + ("" if m.metric is not None else f" (not read: {m.reason})")
                for m in context.secondary
            )
            _complain(
                f"referee: note: the secondary metrics ({listed}) are not analysed in a "
                "results review; --mode monitor reads them"
            )
    except DataError as error:
        _complain(*_data_error(error))
        return EXIT_UNREADABLE
    except ResultsError as error:
        _complain(
            f"referee: error: {error.header}", *(f"  - {problem}" for problem in error.problems)
        )
        return EXIT_UNREADABLE
    except OSError as error:  # a file that vanished or cannot be read after the checks
        _complain(f"referee: error: {error}")
        return EXIT_UNREADABLE

    source = "command line" if as_of is not None else "manifest"
    report = results_report(
        review,
        context,
        file_hashes=hashes,
        as_of_source=source,
        sensitivity=sensitivity,
    )
    renderers = {"json": render_json, "memo": render_results_memo, "text": render_results_text}
    sys.stdout.write(renderers[args.format](report))
    return EXIT_BLOCKED if report["blocking_rule_ids"] else EXIT_OK


def _monitor_results(args: argparse.Namespace, spec: ExperimentSpec) -> int:
    """`review-results --mode monitor` (design section 27)."""
    if args.format == "memo":
        _complain(
            "referee: error: --format memo is a review format; use text or json with --mode monitor"
        )
        return EXIT_UNREADABLE
    as_of: datetime | None = None
    if args.as_of is not None:
        try:
            as_of = parse_utc(args.as_of)
        except ValueError as problem:
            _complain(f"referee: error: --as-of {problem}")
            return EXIT_UNREADABLE
    try:
        if args.experiment_id is None:
            ids = ", ".join(list_experiment_ids(args.data)) or "none"
            _complain(f"referee: error: --experiment-id is required; the export holds: {ids}")
            return EXIT_UNREADABLE
        data = load_export(args.data, args.experiment_id)
        hashes = export_file_hashes(args.data)
        if as_of is not None:
            data = replace(data, exported_at=as_of)
        report = monitor_report(
            spec,
            data,
            file_hashes=hashes,
            as_of_source="command line" if as_of is not None else "manifest",
        )
    except DataError as error:
        _complain(*_data_error(error))
        return EXIT_UNREADABLE
    except ResultsError as error:
        _complain(
            f"referee: error: {error.header}", *(f"  - {problem}" for problem in error.problems)
        )
        return EXIT_UNREADABLE
    except OSError as error:
        _complain(f"referee: error: {error}")
        return EXIT_UNREADABLE
    renderers = {"json": render_json, "text": render_monitor_text}
    sys.stdout.write(renderers[args.format](report))
    return EXIT_BLOCKED if report["status"] == "stop_for_cause" else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status. Never raises."""
    try:
        args = build_parser().parse_args(argv)
        if args.command == "review-results":
            return _review_results(args)
        return _review_design(args.spec, args.format)
    except SystemExit as exit_request:  # argparse: usage errors, --help, --version
        return exit_request.code if isinstance(exit_request.code, int) else EXIT_UNREADABLE
    except Exception:
        traceback.print_exc()
        print("referee: error: internal error; this is a bug in Referee", file=sys.stderr)
        return EXIT_INTERNAL
