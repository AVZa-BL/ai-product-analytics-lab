"""The `narrate` command (design 24.9): a saved results report and a question in, one page out.

    status = narrate(report_path, question, llm_command=None, show_request=False)
    # question None is the summary, with no routing

Paths 1 and 2 of 24.3, a refusal by code and an answer by code, read the report and nothing else:
they start no process and reach no network (a test scans the imports and another pins the calls).
Path 3 is `--llm-command`: for the summary, the next steps and the explanation of a finding, the
command is given the sheet and returns identifiers, once, and the page is the answer with what it
selected leading; for every other page it is not started. The page is built as one string and
written once, so a failure while building prints nothing on standard output.

Statuses: 0 a page was printed, an answer or a refusal, whatever the verdict of the report (this
command is not a gate), or the request of `--show-request`; 1 the output of the command failed a
check and the page is the withheld one; 2 the report cannot be read, parsed or checked, with the
problems on standard error, or `--llm-command` is unusable; 3 any exception while making or writing
the page or the sheet (a full disk, a closed pipe, the egress assertion), with its type, and no
traceback or message (which could hold a word of the report), on standard error; 4 the command
failed (`NarratorError`): one fixed line with the reason word on standard error and nothing on
standard output.
"""

from __future__ import annotations

import os
import sys

from referee.display import for_line
from referee.narration.facts import ReportError, check_report_consistency, fact_list, read_report
from referee.narration.narrator import (
    NarratorError,
    command_narrator,
    request_bytes,
    split_command,
)
from referee.narration.output import OutputError, parse_selection
from referee.narration.refusals import refusal_body
from referee.narration.render import (
    Understanding,
    decision_block,
    needs_narrator,
    render_answer,
    render_refusal,
    render_withheld,
)
from referee.narration.router import route
from referee.narration.sheet import build_request

PAGE = 0
WITHHELD = 1
UNUSABLE = 2
FAILED = 3
NARRATOR_FAILED = 4

LLM_TIMEOUT_S = 120  # for the whole exchange with the command of --llm-command (24.5)
NO_REQUEST = "no request would be made for this question"


def _complain(*lines: str) -> None:
    if sys.stderr is not None:  # with file 2 closed, print would write to standard output
        print("\n".join(for_line(line) for line in lines), file=sys.stderr)


def _problems(path: str, error: ReportError) -> list[str]:
    noun = "problem" if error.total == 1 else "problems"
    lines = [f"referee: error: {path} cannot be used as a results report ({error.total:,} {noun}):"]
    lines += [f"  - {problem}" for problem in error.problems]
    if error.total > len(error.problems):
        lines.append(f"  ... and {error.total - len(error.problems):,} more")
    return lines


def _page(
    report: dict, question: str | None, argv: list[str] | None, show_request: bool
) -> tuple[int, str]:
    """The status and the text for standard output. `argv` is the command of `--llm-command`, None
    without one. A request is made only for an answer that has a finding in scope (24.3)."""
    facts = fact_list(report)
    understanding = Understanding("answer", "summary") if question is None else route(question)
    decision = decision_block(report)
    asks = argv is not None and needs_narrator(report, understanding)
    if show_request:
        if not asks:
            return PAGE, NO_REQUEST + "\n"
        return PAGE, request_bytes(build_request(report, facts, understanding)).decode("ascii")
    if understanding.kind != "answer":
        body = refusal_body(report, facts, understanding)
        return PAGE, render_refusal(report, understanding, decision, body)
    if not asks:
        return PAGE, render_answer(report, facts, understanding, decision)
    narrator = command_narrator(argv, LLM_TIMEOUT_S, None)
    output = narrator(build_request(report, facts, understanding))
    try:
        selection = parse_selection(output, report, facts, understanding)
    except OutputError as error:
        return WITHHELD, render_withheld(report, understanding, decision, error.violations)
    return PAGE, render_answer(report, facts, understanding, decision, selection)


def _write(page: str) -> None:
    """The page on standard output in one write, a character the stream cannot encode as an
    escape instead of an error. The flush is here so that a write that fails (a full disk, a closed
    pipe) fails inside the caller's try and not in the interpreter's flush at exit."""
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        page = page.encode(encoding, errors="backslashreplace").decode(encoding)
    sys.stdout.write(page)
    sys.stdout.flush()


def _give_up_stdout() -> None:
    """A write to the real standard output failed. The stream still holds the page, and where the
    system fails the write again when the interpreter flushes at exit (macOS does), the process
    ends with a second message and status 120 instead of 3. Standard output is of no use any more,
    so it becomes a sink. Only the process's own stream: a test's or a caller's is left alone."""
    if sys.stdout is sys.__stdout__:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")


def narrate(
    report_path: str,
    question: str | None,
    llm_command: str | None = None,
    show_request: bool = False,
) -> int:
    """Print the page for `question` about the report at `report_path`; return the status.
    `llm_command` is the text of `--llm-command`, `show_request` that of `--show-request`."""
    try:
        argv = None if llm_command is None else split_command(llm_command)
    except ValueError as error:
        _complain(f"referee: error: {error}")
        return UNUSABLE
    try:
        report = read_report(report_path)
        check_report_consistency(report)
    except ReportError as error:
        _complain(*_problems(report_path, error))
        return UNUSABLE
    try:
        status, text = _page(report, question, argv, show_request)
        _write(text)
    except NarratorError as error:
        _complain(f"referee: error: --llm-command failed ({error.reason}); no page was made")
        return NARRATOR_FAILED
    except Exception as error:
        if isinstance(error, OSError):
            _give_up_stdout()
        _complain(
            f"referee: error: internal error ({type(error).__name__}); this is a bug in Referee"
        )
        return FAILED
    return status
