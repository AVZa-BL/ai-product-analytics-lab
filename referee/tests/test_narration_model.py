"""The model path of `referee narrate` (design 24.3 path 3, 24.7, 24.9 and the N7b line of 24.16).

`--llm-command` and `--show-request`, through the command line, with the stub of `narration_stubs`
as the user's command (a Python script run with `sys.executable`) and with fake narrators where no
process is needed. No test here, or anywhere, runs a model. Every call that starts a stub is
required to return within a margin of its deadline, and none asserts how long it took. What the
page of an answer holds is tested in test_narration_render.py and test_narration_whole_page.py, the
narrator's own behaviour in test_narration_narrator.py, the sheet in test_narration_sheet.py.
"""

import contextlib
import json
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from narration_fakes import SCHEMA, Ask, FakeNarrator, fixed_text
from narration_pages import canonical_page
from narration_reports import report
from narration_stubs import MARKER, VALID, gone, recorded, returns_within, stub_argv

from referee import cli
from referee.narration import command, narrator, sheet
from referee.narration.facts import fact_list
from referee.narration.narrator import request_bytes
from referee.narration.output import OutputError, parse_selection
from referee.narration.render import (
    Understanding,
    decision_block,
    needs_narrator,
    render_answer,
    render_withheld,
)
from referee.narration.router import route
from referee.narration.sheet import build_request
from referee.report import render_json

DEADLINE = 1  # seconds, for a stub that is meant to run into it
MARGIN = 5  # seconds after the deadline within which a call is required to return
DEVELOPMENT = json.loads(
    (
        Path(__file__).parent / "data" / "narration_eval" / "development" / "questions.json"
    ).read_text(encoding="utf-8")
)
SUMMARY = "What did the review find?"
NEXT_STEPS = "What should we fix next?"
EXPLANATION = "Why does RES-001 block the review?"


def run(capfd: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """The command line, with both streams taken at the file descriptors, so that what a child
    process writes to an inherited stream is seen too."""
    code = cli.main(list(argv))
    captured = capfd.readouterr()
    return code, captured.out, captured.err


def save(directory: Path, rep: dict, name: str = "report") -> str:
    path = directory / f"{name}.json"
    path.write_text(render_json(rep), encoding="utf-8")
    return str(path)


@contextlib.contextmanager
def no_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def started(*args: object, **kwargs: object) -> None:
        raise AssertionError("a process was started")

    with monkeypatch.context() as patched:
        patched.setattr(subprocess, "Popen", started)
        yield


def stub(directory: Path, mode: str, *arguments: str) -> str:
    return shlex.join(stub_argv(directory, mode, *arguments))


# --- Statuses 4, 1 and 2 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "reason", "padded"),
    [
        ("start", "start", False),  # a command that is not there
        ("directory", "start", False),  # one that cannot be executed
        ("exit", "exit", False),  # exits at once, without reading its input
        ("exit", "exit", True),  # the same, with a request that is still being written
        ("sleep", "timeout", False),
        ("sleep hold", "timeout", True),  # never reads, and a grandchild holds its output
        ("empty", "empty", False),
        ("size 40000", "size", False),
        ("encoding", "encoding", False),
        ("tty", "exit", False),
        (f"emit {VALID.encode().hex()} kill", "exit", False),  # valid output, then killed
        ("emit - 3", "exit", False),  # no output
        ("emit ff 3", "exit", False),  # output that is not UTF-8
    ],
    ids=[
        "start",
        "not executable",
        "early exit",
        "early exit, request padded",
        "timeout",
        "sleeping grandchild, never reads",
        "empty",
        "size",
        "encoding",
        "/dev/tty",
        "killed after valid output",
        "exit with no output",
        "exit with output that is not UTF-8",
    ],
)
def test_a_command_that_fails_gives_status_4_with_its_reason_and_no_marker_on_any_stream(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    mode: str,
    reason: str,
    padded: bool,
) -> None:
    if mode == "tty" and not Path("/dev/tty").exists():
        pytest.skip("this system has no /dev/tty")
    # only a stub that waits is meant to run into the deadline; the others end by themselves
    waits = reason == "timeout"
    monkeypatch.setattr(command, "LLM_TIMEOUT_S", DEADLINE if waits else DEADLINE + MARGIN)
    if padded:  # a request of 2 MB, past any pipe buffer: the instructions are padded
        monkeypatch.setattr(sheet, "SYSTEM", "x" * 2_000_000)
        monkeypatch.setattr(narrator, "MAX_REQUEST_BYTES", 10_000_000)
    path = save(tmp_path, report("golden", raw_spec))
    # a command that cannot be started still has the marker among its arguments
    unstartable = {"start": tmp_path / "missing", "directory": tmp_path}
    given = (
        shlex.join([str(unstartable[mode]), MARKER])
        if mode in unstartable
        else stub(tmp_path, *mode.split())
    )

    with returns_within(DEADLINE + MARGIN):
        result = run(capfd, "narrate", path, "--llm-command", given)

    # the whole of both streams: the marker is on neither, and nothing else is on standard output
    assert result == (4, "", f"referee: error: --llm-command failed ({reason}); no page was made\n")
    if mode == "tty":  # a new session has no controlling terminal to write to
        assert (tmp_path / "tty.txt").read_text() == "no"
    if mode == "sleep hold":  # and nothing of the command is left running
        assert gone(*recorded(tmp_path))


@pytest.mark.parametrize(
    ("text", "error"),
    [
        (f"cat '{MARKER}", "--llm-command has a quote or a backslash that is not closed"),
        (f"{MARKER} \\", "--llm-command has a quote or a backslash that is not closed"),
        ("", "--llm-command is empty"),
        ("  ", "--llm-command is empty"),
    ],
)
def test_a_command_line_that_is_not_one_is_status_2_with_a_fixed_line_and_starts_nothing(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    text: str,
    error: str,
) -> None:
    path = save(tmp_path, report("golden", raw_spec))

    with no_process(monkeypatch):
        result = run(capfd, "narrate", path, "--llm-command", text)

    assert result == (2, "", f"referee: error: {error}\n")


def test_an_output_that_fails_the_checks_is_status_1_and_the_withheld_page(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
) -> None:
    monkeypatch.setattr(command, "LLM_TIMEOUT_S", DEADLINE + MARGIN)
    rep = report("golden", raw_spec)
    # well formed, and for a rule that is not a finding of the report
    output = {"schema": SCHEMA, "findings": [{"id": "RES-005", "facts": [], "sentences": []}]}
    chosen = tmp_path / "selection.json"
    chosen.write_text(json.dumps(output), encoding="utf-8")
    understanding, facts = route(SUMMARY), fact_list(rep)
    with pytest.raises(OutputError) as wrong:
        parse_selection(chosen.read_text(), rep, facts, understanding)

    given = stub(tmp_path, "cat", str(chosen))
    with returns_within(DEADLINE + MARGIN):
        code, out, err = run(
            capfd, "narrate", save(tmp_path, rep), "--question", SUMMARY, "--llm-command", given
        )

    assert (code, err) == (1, "")
    assert out == render_withheld(rep, understanding, decision_block(rep), wrong.value.violations)
    assert out.split("\n")[3].startswith(
        "Narration withheld: the output of --llm-command failed these checks: "
        "scope -, coverage RES-001,"
    )


# --- The page and the request -----------------------------------------------------------


@pytest.mark.parametrize("question", [SUMMARY, NEXT_STEPS, EXPLANATION])
def test_the_page_of_a_command_is_the_page_of_its_selection_and_the_command_got_what_is_shown(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    question: str,
) -> None:
    """The stub selects, from the sheet it is sent, all that the intent offers: the selection that
    N7a's fake returns, so the page is the one `render_answer` makes from it."""
    monkeypatch.setattr(command, "LLM_TIMEOUT_S", DEADLINE + MARGIN)
    rep = report("golden", raw_spec)
    path, understanding, facts = save(tmp_path, rep), route(question), fact_list(rep)
    selection = parse_selection(
        FakeNarrator(fixed_text(Ask("golden", rep, facts, understanding)))(None),
        rep,
        facts,
        understanding,
    )
    expected = render_answer(rep, facts, understanding, decision_block(rep), selection)

    asked = ["narrate", path, "--question", question, "--llm-command"]
    with no_process(monkeypatch):  # --show-request starts nothing, the command is not run
        shown = run(capfd, *asked, "x", "--show-request")
    with returns_within(DEADLINE + MARGIN):
        result = run(capfd, *asked, stub(tmp_path, "select"))

    assert result == (0, expected, "")
    assert shown[0] == 0 and shown[2] == ""
    assert (tmp_path / "request.bin").read_bytes() == shown[1].encode("ascii")  # what it got


def test_the_narrator_gets_the_intent_and_the_target_and_never_the_question(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
) -> None:
    """The request of every development question that needs a narrator is the request built from
    what the router made of it, the question not an argument; so no run of it is in the request
    that the question itself did not put in the understanding. `--show-request` prints the same."""
    asked = 0
    for name in sorted({question["fixture"] for question in DEVELOPMENT}):
        rep, facts = report(name, raw_spec), fact_list(report(name, raw_spec))
        path = save(tmp_path, rep, name)
        for item in (q for q in DEVELOPMENT if q["fixture"] == name):
            understanding = route(item["text"])
            if not needs_narrator(rep, understanding):
                continue
            fake = FakeNarrator(fixed_text(Ask(name, rep, facts, understanding)))
            expected = build_request(rep, facts, understanding)
            asked_for = ["narrate", path, "--question", item["text"], "--llm-command", "x"]
            with monkeypatch.context() as patched:
                patched.setattr(command, "command_narrator", lambda *args, fake=fake: fake)
                code, _, err = run(capfd, *asked_for)
            shown = run(capfd, *asked_for, "--show-request")
            assert (code, err, fake.requests) == (0, "", [expected]), item["id"]
            assert shown == (0, request_bytes(expected).decode("ascii"), ""), item["id"]
            asked += 1
    assert asked >= 15  # not vacuous: 18 of the development questions need a narrator


@pytest.mark.parametrize(
    ("name", "question"),
    [
        ("golden", "Why does RES-003 say that?"),
        ("golden", "Why does RES-005 say that?"),
        ("golden", "Why does ZZZ-123 matter?"),
        ("golden", "Which checks did this review run?"),
        ("golden", "can we call it on day 3?"),
        ("golden", ""),
        ("clear", None),
    ],
    ids=[
        "a quiet rule",
        "a rule that is not built",
        "a string shaped like an ID",
        "what was checked",
        "a refusal",
        "an unreadable question",
        "a report with no finding",
    ],
)
def test_a_page_of_code_alone_starts_no_narrator_even_with_a_command(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    name: str,
    question: str | None,
) -> None:
    rep = report(name, raw_spec)
    path, ask = save(tmp_path, rep), [] if question is None else ["--question", question]
    understanding = Understanding("answer", "summary") if question is None else route(question)
    fake = FakeNarrator(VALID)
    monkeypatch.setattr(command, "command_narrator", lambda *args: fake)

    with no_process(monkeypatch):
        page = run(capfd, "narrate", path, *ask, "--llm-command", "x")
        shown = run(capfd, "narrate", path, *ask, "--llm-command", "x", "--show-request")

    assert page == (0, canonical_page(rep, understanding), "") and fake.requests == []
    assert shown == (0, "no request would be made for this question\n", "")


def test_without_a_command_there_is_no_request_for_any_question(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
) -> None:
    path = save(tmp_path, report("golden", raw_spec))

    with no_process(monkeypatch):
        shown = run(capfd, "narrate", path, "--question", SUMMARY, "--show-request")

    assert shown == (0, "no request would be made for this question\n", "")


def test_the_command_is_run_as_it_was_typed_for_120_seconds_in_our_environment(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
) -> None:
    rep, calls = report("golden", raw_spec), []
    understanding = Understanding("answer", "summary")
    fake = FakeNarrator(fixed_text(Ask("golden", rep, fact_list(rep), understanding)))
    monkeypatch.setattr(command, "command_narrator", lambda *args: calls.append(args) or fake)

    code, _, _ = run(
        capfd, "narrate", save(tmp_path, rep), "--llm-command", "python -c 'a b'  \"c d\" e\\ f"
    )

    assert (code, calls) == (0, [(["python", "-c", "a b", "c d", "e f"], 120, None)])


# --- Statuses 3 -------------------------------------------------------------------------


@pytest.mark.parametrize("show", [False, True], ids=["a command", "--show-request"])
@pytest.mark.parametrize("fault", ["EgressError", "RequestTooLarge"])
def test_a_fault_in_making_the_request_is_status_3_with_its_type_and_starts_nothing(
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    fault: str,
    show: bool,
) -> None:
    if fault == "EgressError":  # a sheet with a word of the report that code did not write
        monkeypatch.setattr(sheet, "sheet", lambda rep, *args: {"leak": rep["experiment_id"]})
    else:
        monkeypatch.setattr(narrator, "MAX_REQUEST_BYTES", 1_000)
    path = save(tmp_path, report("golden", raw_spec))

    with no_process(monkeypatch):
        result = run(capfd, "narrate", path, "--llm-command", "x", *(["--show-request"] * show))

    assert result == (
        3,
        "",
        f"referee: error: internal error ({fault}); this is a bug in Referee\n",
    )
