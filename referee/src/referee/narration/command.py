"""The `narrate` command (design 24.9): a saved results report and a question in, one page out.

    status = narrate(report_path, question)    # question None is the summary, with no routing

Paths 1 and 2 of 24.3: a refusal by code or an answer by code. Nothing here starts a process,
reaches a network or reads anything but the report (a test scans the imports and another pins the
calls). The page is built as one string and written once, so a failure while building prints
nothing on standard output.

Statuses: 0 a page was printed, an answer or a refusal, whatever the verdict of the report (this
command is not a gate); 2 the report cannot be read, parsed or checked, with the problems on
standard error; 3 any exception while making or writing the page (a full disk, a closed pipe), with
its type, and no traceback or message (which could hold a word of the report), on standard error.
1 and 4 belong to the model path.
"""

from __future__ import annotations

import os
import sys

from referee.display import for_line
from referee.narration.facts import ReportError, check_report_consistency, fact_list, read_report
from referee.narration.refusals import refusal_body
from referee.narration.render import Understanding, decision_block, render_answer, render_refusal
from referee.narration.router import route

PAGE = 0
UNUSABLE = 2
FAILED = 3


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


def _page(report: dict, question: str | None) -> str:
    facts = fact_list(report)
    understanding = Understanding("answer", "summary") if question is None else route(question)
    decision = decision_block(report)
    if understanding.kind == "answer":
        return render_answer(report, facts, understanding, decision)
    body = refusal_body(report, facts, understanding)
    return render_refusal(report, understanding, decision, body)


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


def narrate(report_path: str, question: str | None) -> int:
    """Print the page for `question` about the report at `report_path`; return the status."""
    try:
        report = read_report(report_path)
        check_report_consistency(report)
    except ReportError as error:
        _complain(*_problems(report_path, error))
        return UNUSABLE
    try:
        _write(_page(report, question))
    except Exception as error:
        if isinstance(error, OSError):
            _give_up_stdout()
        _complain(
            f"referee: error: internal error ({type(error).__name__}); this is a bug in Referee"
        )
        return FAILED
    return PAGE
