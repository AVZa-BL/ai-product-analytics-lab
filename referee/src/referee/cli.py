"""The `referee` command line.

Exit codes of `review-design`: 0 when the review finds no blocker, 1 when it finds one,
2 when the spec cannot be read or is not valid, and 3 when Referee itself fails. Keeping a
crash out of 1 matters: an uncaught Python exception exits with 1, which a pipeline would
read as "the design has a blocker".
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence

from referee import __version__
from referee.loader import LoadError, load_spec
from referee.report import design_report, render_json, render_text
from referee.review import review_design
from referee.spec import SpecError

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
    return parser


def _spec_error(path: str, error: SpecError) -> str:
    count = len(error.violations)
    noun = "violation" if count == 1 else "violations"
    lines = [f"referee: error: {path} is not a valid experiment spec ({count} {noun}):"]
    lines += [f"  - {violation}" for violation in error.violations]
    return "\n".join(lines)


def _review_design(path: str, output_format: str) -> int:
    try:
        spec = load_spec(path)
    except LoadError as error:
        print(f"referee: error: {error}", file=sys.stderr)
        return EXIT_UNREADABLE
    except SpecError as error:
        print(_spec_error(path, error), file=sys.stderr)
        return EXIT_UNREADABLE

    report = design_report(spec, review_design(spec))
    render = render_json if output_format == "json" else render_text
    sys.stdout.write(render(report))
    return EXIT_BLOCKED if report["blocking_rule_ids"] else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return its exit status. Never raises."""
    try:
        args = build_parser().parse_args(argv)
        return _review_design(args.spec, args.format)
    except SystemExit as exit_request:  # argparse: usage errors, --help, --version
        return exit_request.code if isinstance(exit_request.code, int) else EXIT_UNREADABLE
    except Exception:
        traceback.print_exc()
        print("referee: error: internal error; this is a bug in Referee", file=sys.stderr)
        return EXIT_INTERNAL
