"""The narrator of the model path (design 24.5 and the N7b line of 24.16).

The request as the command receives it, the closed reasons, and the process: the command is run
with `narration_stubs`, a Python script run with `sys.executable`, and each call is required to
return within a margin of its deadline (never to take a certain time). A killed process is looked
for in the table of processes until it is gone, which is a wait for a fact, not an assertion about
time. Status 4 with its fixed line, for each way a command can fail, is test_narration_model.py's.
"""

import errno
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from narration_stubs import (
    MARKER,
    VALID,
    alive,
    gone,
    recorded,
    returns_within,
    sigint_raises,
    stub_argv,
)

from referee.narration import narrator
from referee.narration.narrator import (
    REASONS,
    ModelRequest,
    NarratorError,
    RequestTooLarge,
    command_narrator,
    request_bytes,
)

REQUEST = ModelRequest("system", "user", 7)
DEADLINE = 1  # seconds, for a stub that is meant to run into it
MARGIN = 5  # seconds after the deadline within which a call is required to return
KIB = 1024


def valid_file(directory: Path) -> str:
    path = directory / "valid.txt"
    path.write_text(VALID, encoding="utf-8")
    return str(path)


def without_waitid(monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """The system cannot look at an exit without collecting it: it has no `os.waitid`, or the call
    fails (as a call that a system does not support does)."""

    def fails(*args: object) -> None:
        raise OSError(errno.EINVAL, "not supported")

    if how == "missing":
        monkeypatch.delattr(os, "waitid", raising=False)
    elif how == "fails":
        monkeypatch.setattr(os, "waitid", fails)


WAITID = pytest.mark.parametrize("how", ["waitid", "missing", "fails"])


def recording(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen]:
    """The processes started from now on, so that a test can look at them afterwards."""
    started: list[subprocess.Popen] = []

    class Recorded(subprocess.Popen):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(subprocess, "Popen", Recorded)
    return started


def padded(monkeypatch: pytest.MonkeyPatch) -> ModelRequest:
    """A request of 2 MB, past any pipe buffer: the limit of the request is lifted for it."""
    monkeypatch.setattr(narrator, "MAX_REQUEST_BYTES", 10_000_000)
    return ModelRequest("system", "x" * 2_000_000, 1)


def test_the_request_is_canonical_json_on_one_ascii_line_of_at_most_32_kib() -> None:
    assert request_bytes(ModelRequest("s", "é\n", 7)) == (
        b'{"max_tokens":7,"schema":"referee-narration-request/1","system":"s",'
        b'"user":"\\u00e9\\n"}\n'
    )
    bare = len(request_bytes(ModelRequest("", "", 1)))
    assert len(request_bytes(ModelRequest("", "x" * (32 * KIB - bare), 1))) == 32 * KIB
    with pytest.raises(RequestTooLarge):
        request_bytes(ModelRequest("", "x" * (32 * KIB - bare + 1), 1))


def test_a_narrator_error_holds_one_of_the_six_reasons_and_nothing_else() -> None:
    assert REASONS == ("start", "exit", "timeout", "empty", "size", "encoding")
    assert [str(NarratorError(reason)) for reason in REASONS] == list(REASONS)
    with pytest.raises(ValueError):
        NarratorError(f"{MARKER} could not be started")


@pytest.mark.parametrize("size", [30 * KIB, 2_000_000], ids=["at the limit", "past any pipe"])
def test_the_command_gets_the_request_whole_and_the_end_of_its_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, size: int
) -> None:
    monkeypatch.setattr(narrator, "MAX_REQUEST_BYTES", 10_000_000)  # lifted for the larger
    request = ModelRequest("system", "y" * size, 7)  # several writes where a pipe holds 16 KiB

    with returns_within(DEADLINE + MARGIN):
        text = command_narrator(stub_argv(tmp_path, "hash"), DEADLINE + MARGIN)(request)

    assert text == hashlib.sha256(request_bytes(request)).hexdigest()  # read to its end


@pytest.mark.parametrize(
    ("given", "seen"),
    [({"REFEREE_STUB": "given"}, "given"), (None, "inherited")],
    ids=["an environment that is given", "none: the one of the process"],
)
def test_the_command_runs_in_the_environment_it_is_given_or_in_ours(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, given: dict[str, str] | None, seen: str
) -> None:
    monkeypatch.setenv("REFEREE_STUB", "inherited")

    with returns_within(DEADLINE + MARGIN):
        text = command_narrator(
            stub_argv(tmp_path, "env", "REFEREE_STUB"), DEADLINE + MARGIN, given
        )(REQUEST)

    assert text == seen


@pytest.mark.parametrize(("size", "reason"), [(32 * KIB, None), (32 * KIB + 1, "size")])
def test_the_output_may_be_32_kib_and_not_a_byte_more(
    tmp_path: Path, size: int, reason: str | None
) -> None:
    command = command_narrator(stub_argv(tmp_path, "size", str(size)), DEADLINE + MARGIN)

    with returns_within(DEADLINE + MARGIN):
        if reason is None:
            assert len(command(REQUEST)) == size
        else:
            with pytest.raises(NarratorError) as caught:
                command(REQUEST)
            assert caught.value.reason == reason


def test_without_killpg_nothing_is_started_and_the_reason_is_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def started(*args: object, **kwargs: object) -> None:
        raise AssertionError("a process was started")

    monkeypatch.delattr(os, "killpg")
    monkeypatch.setattr(subprocess, "Popen", started)

    with pytest.raises(NarratorError) as caught:
        command_narrator(stub_argv(tmp_path, "exit"), DEADLINE)(REQUEST)

    assert caught.value.reason == "start"


def test_a_command_that_never_reads_and_never_answers_runs_into_the_deadline_and_its_group_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request = padded(monkeypatch)  # a blocking write would wait for a command that never reads
    started = recording(monkeypatch)

    with returns_within(DEADLINE + MARGIN), pytest.raises(NarratorError) as caught:
        command_narrator(stub_argv(tmp_path, "sleep", "hold"), DEADLINE)(request)

    assert caught.value.reason == "timeout"
    # the command, which ignores SIGTERM, and the grandchild that holds its output
    assert gone(*recorded(tmp_path))
    (child,) = started
    assert child.returncode is not None and child.stdin.closed and child.stdout.closed


@WAITID
@pytest.mark.parametrize("code", [0, 1], ids=["exit 0", "exit 1"])
def test_the_read_ends_when_the_command_exits_and_a_grandchild_holding_its_output_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, how: str, code: int
) -> None:
    without_waitid(monkeypatch, how)
    command = command_narrator(
        stub_argv(tmp_path, "leave", str(code), valid_file(tmp_path)), DEADLINE + MARGIN
    )

    with returns_within(DEADLINE + MARGIN):
        if code == 0:
            assert command(REQUEST) == VALID
        else:
            with pytest.raises(NarratorError) as caught:
                command(REQUEST)
            assert caught.value.reason == "exit"

    assert gone(*recorded(tmp_path))


@WAITID
def test_a_command_that_ignores_its_input_and_exits_does_not_break_the_pipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, how: str
) -> None:
    without_waitid(monkeypatch, how)  # collected at once, the group of a command is empty
    started = recording(monkeypatch)
    command = command_narrator(stub_argv(tmp_path, "cat", valid_file(tmp_path)), DEADLINE + MARGIN)

    with returns_within(DEADLINE + MARGIN):
        assert command(padded(monkeypatch)) == VALID  # `cat FILE`, the documented replay

    (child,) = started
    assert child.returncode == 0 and child.stdin.closed and child.stdout.closed


@pytest.mark.parametrize("timeout_s", [DEADLINE + MARGIN, 0], ids=["", "the deadline is over"])
def test_what_a_command_wrote_before_it_exited_is_read_however_late_its_exit_is_seen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, timeout_s: float
) -> None:
    """Referee looks late: the command has exited, written 30 KiB, and the pipe holds it all. A
    command that has exited when the deadline is reached is read, not timed out."""

    def looked_late(child: subprocess.Popen) -> bool:
        child.wait()
        return True

    big = tmp_path / "big.txt"
    big.write_text("a" * 30 * KIB, encoding="utf-8")
    monkeypatch.setattr(narrator, "_exited", looked_late)
    monkeypatch.setattr(narrator, "CHUNK", KIB)  # so that it takes more than one read

    with returns_within(DEADLINE + MARGIN):
        text = command_narrator(stub_argv(tmp_path, "cat", str(big)), timeout_s)(REQUEST)

    assert text == "a" * 30 * KIB


@pytest.mark.parametrize("kind", ["not there", "a directory", "a NUL in a word"])
def test_a_command_that_cannot_be_started_is_start_and_shows_no_cause_in_a_traceback(
    tmp_path: Path, kind: str
) -> None:
    program = {"not there": str(tmp_path / "missing"), "a directory": str(tmp_path)}.get(
        kind, "a\0b"
    )

    with pytest.raises(NarratorError) as caught:
        command_narrator([program], DEADLINE)(REQUEST)

    assert caught.value.reason == "start"
    assert (
        caught.value.__suppress_context__
    )  # the cause holds the arguments, which a traceback shows


def test_output_that_is_not_utf_8_shows_no_cause_in_a_traceback(tmp_path: Path) -> None:
    with pytest.raises(NarratorError) as caught:
        command_narrator(stub_argv(tmp_path, "encoding"), DEADLINE + MARGIN)(REQUEST)

    assert caught.value.reason == "encoding"
    assert caught.value.__suppress_context__  # the cause holds the bytes of the output


def test_a_read_or_a_write_that_would_block_is_tried_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A wake-up of the selector without room or data (kqueue may give one) is not an error."""
    failing, blocking = {"read", "write"}, []

    class OnceBlocked:  # `os` as the narrator sees it: the first read and the first write block
        def __getattr__(self, name: str):
            real = getattr(os, name)
            if name == "set_blocking":  # and the ends of both pipes are asked not to block
                return lambda fd, flag: (blocking.append(flag), real(fd, flag))[1]
            if name not in failing:
                return real

            def blocked(*args: object) -> object:
                if name in failing:
                    failing.discard(name)
                    raise BlockingIOError
                return real(*args)

            return blocked

    monkeypatch.setattr(narrator, "os", OnceBlocked())
    command = command_narrator(stub_argv(tmp_path, "cat", valid_file(tmp_path)), DEADLINE + MARGIN)

    with returns_within(DEADLINE + MARGIN):
        assert command(REQUEST) == VALID

    assert failing == set() and blocking == [False, False]  # both were met


def test_the_check_that_a_process_is_gone_sees_one_that_is_not() -> None:
    assert alive(os.getpid()) and not gone(os.getpid(), wait_s=0.05)


def test_an_interrupt_kills_the_group_before_it_goes_on(tmp_path: Path) -> None:
    command = command_narrator(stub_argv(tmp_path, "interrupt"), DEADLINE + MARGIN)

    with returns_within(DEADLINE + MARGIN), sigint_raises(), pytest.raises(KeyboardInterrupt):
        command(REQUEST)  # the stub sends SIGINT to us once its grandchild is running

    assert gone(*recorded(tmp_path))
