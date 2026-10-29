"""`python -m specwright draft`: draft an experiment spec from a brief or a design document."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tracewright.propose.documents import DocumentError, load_documents

from specwright import __version__
from specwright.proposers import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    EFFORTS,
    AnthropicProposer,
    ReplayProposer,
)
from specwright.render import OUTPUT_FILES, write_outputs
from specwright.request import DraftRequest, ProposerError
from specwright.run import MAX_REPAIRS_LIMIT, Attempt, run_draft

EXIT_OK = 0
EXIT_UNRESOLVED = 1
EXIT_BAD_INPUT = 2
EXIT_INTERNAL = 3
EXIT_MODEL = 4
EXIT_NEEDS_ANSWERS = 5
EXIT_INFEASIBLE = 6
_EXIT = {
    "ok": EXIT_OK,
    "unresolved": EXIT_UNRESOLVED,
    "needs_answers": EXIT_NEEDS_ANSWERS,
    "infeasible": EXIT_INFEASIBLE,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specwright",
        description="Drafts an experiment spec from a brief or a design document. Advisory only.",
    )
    parser.add_argument("--version", action="version", version=f"specwright {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    draft = commands.add_parser(
        "draft",
        help="draft an experiment spec from documents",
        description=(
            "Exit status: 0 a spec was drafted and Referee's design rules raise no blocker, 1 a "
            "blocker is left after the repairs, 2 an input cannot be used, 3 an internal error, "
            "4 the model could not be reached, 5 the documents do not give everything a spec "
            "needs (the questions are in the report), 6 the numbers the documents give cannot "
            "reach the power the spec asks for."
        ),
    )
    draft.add_argument("--doc", action="append", required=True, metavar="PATH", help="repeatable")
    draft.add_argument("--out", required=True, metavar="DIR", help="where the results are written")
    draft.add_argument("--replay", metavar="FILE", help="work from saved responses; no model")
    draft.add_argument("--model", default=DEFAULT_MODEL)
    draft.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORTS)
    draft.add_argument("--max-repairs", type=int, default=2, metavar=f"0..{MAX_REPAIRS_LIMIT}")
    draft.add_argument("--owner", help="the experiment's owner, for the spec")
    draft.add_argument("--force", action="store_true", help="replace results already in --out")
    return parser


def _complain(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def _progress(attempt: Attempt) -> None:
    if attempt.check is None:
        found = f"{len(attempt.parse_problems)} schema problem(s)"
    else:
        found = (
            f"{len(attempt.feedback_sent)} problem(s) to repair, "
            f"{len(attempt.check.questions)} question(s)"
        )
    spent = attempt.response.usage
    tokens = (
        ""
        if not spent
        else f" ({spent.get('input_tokens', '?')} in, {spent.get('output_tokens', '?')} out)"
    )
    print(f"attempt {attempt.number}: {found}{tokens}", file=sys.stderr)


def _draft(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if not 0 <= args.max_repairs <= MAX_REPAIRS_LIMIT:
        _complain(f"specwright: error: --max-repairs must be between 0 and {MAX_REPAIRS_LIMIT}")
        return EXIT_BAD_INPUT
    if out.exists() and not out.is_dir():
        _complain(f"specwright: error: {out} exists and is not a folder")
        return EXIT_BAD_INPUT
    if not args.force and any((out / name).exists() for name in OUTPUT_FILES):
        _complain(f"specwright: error: {out} already holds results; use --force to replace them")
        return EXIT_BAD_INPUT
    try:
        documents = load_documents(args.doc)
    except DocumentError as error:
        _complain(f"specwright: error: {error}")
        return EXIT_BAD_INPUT
    try:
        proposer = (
            ReplayProposer.from_file(args.replay)
            if args.replay
            else AnthropicProposer(model=args.model, effort=args.effort)
        )
        request = DraftRequest(documents=documents, owner=args.owner)
        result = run_draft(request, proposer, max_repairs=args.max_repairs, on_attempt=_progress)
    except ProposerError as error:
        _complain(f"specwright: error: {error}")
        return EXIT_MODEL
    written = write_outputs(result, out, force=args.force)
    print(f"status: {result.status}; wrote {', '.join(written)} to {out}", file=sys.stderr)
    return _EXIT[result.status]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _draft(args)
    except Exception as error:  # a bug in Specwright: say so, and do not look like a bad input
        _complain(f"specwright: internal error: {type(error).__name__}: {error}")
        return EXIT_INTERNAL
