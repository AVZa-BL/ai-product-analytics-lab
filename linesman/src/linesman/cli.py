"""The `linesman` command line.

Exit codes of `review-plan`: 0 when the review finds no blocker, 1 when it finds one, 2 when
the plan cannot be read or is not valid, and 3 when Linesman itself fails. Keeping a crash out
of 1 matters: an uncaught Python exception exits with 1, which a pipeline would read as "the
plan has a blocker".
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence

from linesman import __version__
from linesman.loader import LoadError, load_plan
from linesman.plan import PlanError
from linesman.report import plan_report, render_json, render_text
from linesman.review import review_plan

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_UNREADABLE = 2
EXIT_INTERNAL = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linesman",
        description="Deterministic review of product tracking plans. Advisory only.",
    )
    parser.add_argument("--version", action="version", version=f"linesman {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    review = commands.add_parser(
        "review-plan",
        help="review a tracking plan",
        description=(
            "Review a tracking plan before it ships. Exit status: 0 no blocker found, "
            "1 at least one blocker, 2 the plan cannot be read or is not valid, "
            "3 internal error."
        ),
    )
    review.add_argument("plan", help="path to the tracking plan (YAML)")
    review.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default: text)"
    )
    return parser


def _plan_error(path: str, error: PlanError) -> str:
    count = len(error.violations)
    noun = "violation" if count == 1 else "violations"
    lines = [f"linesman: error: {path} is not a valid tracking plan ({count} {noun}):"]
    lines += [f"  - {violation}" for violation in error.violations]
    return "\n".join(lines)


def _review_plan(path: str, output_format: str) -> int:
    try:
        plan = load_plan(path)
    except LoadError as error:
        print(f"linesman: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except PlanError as error:
        print(_plan_error(path, error), file=sys.stderr)
        return EXIT_UNREADABLE

    report = plan_report(plan, review_plan(plan))
    render = render_json if output_format == "json" else render_text
    sys.stdout.write(render(report))
    return EXIT_BLOCKED if report["blocking_rule_ids"] else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status. Never raises."""
    try:
        args = build_parser().parse_args(argv)
        return _review_plan(args.plan, args.format)
    except SystemExit as exit_request:  # argparse: usage errors, --help, --version
        return exit_request.code if isinstance(exit_request.code, int) else EXIT_UNREADABLE
    except Exception:
        traceback.print_exc()
        print("linesman: error: internal error; this is a bug in Linesman", file=sys.stderr)
        return EXIT_INTERNAL
