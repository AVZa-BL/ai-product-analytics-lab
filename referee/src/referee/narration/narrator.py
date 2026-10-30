"""The narrator of the model path (design 24.5): a request in, the raw text of a selection out.

    narrator = command_narrator(argv, timeout_s, env)    # a Narrator; starts nothing yet
    text = narrator(ModelRequest(system, user, max_tokens))    # or NarratorError(reason)
    request_bytes(request)    # what the command receives on standard input, and --show-request

`command_narrator` is for POSIX and is the only code of the layer that starts a process. The command
is run as given, without a shell, in a session of its own, and gets the request on its standard
input as one line of JSON (`referee-narration-request/1`). The request is written without blocking
while standard output is read against a deadline, never to its end: a command that does not read
its input (`cat FILE` does not) or exits early cannot hold Referee up. The read ends when the
command itself has exited and what is readable is drained, so a process it leaves holding standard
output waits for nothing. Whatever the way out (the output, a failure, the deadline, an interrupt)
the whole process group is killed before the command is collected, and the pipes are closed. Its
standard error is discarded and its environment is Referee's own, which Referee neither reads nor
prints.

A failure is `NarratorError(reason)` with a reason of the closed list `REASONS`. It holds that word
and nothing else, no text of the command's output, no argument and no exception text, so that
nothing of what the command says or what the user typed reaches a message.

Not covered: what the command does with files or the network; a process that leaves the group
(`setsid`); Referee itself being killed (SIGTERM, SIGKILL), which leaves the group running; an
interrupt in the few instructions between the start of the child and the `try` that guards it; and,
on a system without `os.waitid`, the order of the kill and the collection (see `_exited`).
"""

from __future__ import annotations

import contextlib
import json
import os
import selectors
import shlex
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

REQUEST_SCHEMA = "referee-narration-request/1"
MAX_REQUEST_BYTES = 32 * 1024  # on standard input, newline included
MAX_OUTPUT_BYTES = 32 * 1024  # on standard output
REASONS = ("start", "exit", "timeout", "empty", "size", "encoding")
POLL_S = 0.05  # how long a wait for the pipes lasts before the command is asked whether it exited
CHUNK = 65_536


@dataclass(frozen=True)
class ModelRequest:
    """What a narrator is asked: the instructions, the sheet as text and the room for the answer.
    There is no field for a model, and nothing here names one."""

    system: str
    user: str
    max_tokens: int


Narrator = Callable[[ModelRequest], str]


class NarratorError(Exception):
    """The narrator failed. `reason` is one of `REASONS`, and it is all the message holds."""

    def __init__(self, reason: str) -> None:
        if reason not in REASONS:
            raise ValueError("the reason is not one of the six")
        self.reason = reason
        super().__init__(reason)


class RequestTooLarge(ValueError):
    """The request is over 32 KiB: a failure inside Referee, not of the command."""


def request_bytes(request: ModelRequest) -> bytes:
    """The request as the command receives it: canonical JSON on one line, ASCII, ending in a
    newline, of at most 32 KiB (`RequestTooLarge` if longer, before anything is started)."""
    data = json.dumps(
        {
            "schema": REQUEST_SCHEMA,
            "system": request.system,
            "user": request.user,
            "max_tokens": request.max_tokens,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    if len(data) + 1 > MAX_REQUEST_BYTES:
        raise RequestTooLarge("the request is longer than 32 KiB")
    return data + b"\n"


def split_command(text: str) -> list[str]:
    """The words of the command line of `--llm-command`, as a POSIX shell would split them, to be
    run without one. `ValueError` for a quote or backslash left open and for no word at all; the
    message is fixed and holds none of the text, which can hold a secret."""
    try:
        argv = shlex.split(text)
    except ValueError:
        raise ValueError("--llm-command has a quote or a backslash that is not closed") from None
    if not argv:
        raise ValueError("--llm-command is empty")
    return argv


def _exited(child: subprocess.Popen[bytes]) -> bool:
    """Whether the command has exited. Where the system can say so without collecting the exit
    status (`waitid` with `WNOWAIT`) it is left to be collected after the group is killed, so that
    the id the group is known by cannot have passed to another process by then; elsewhere
    `poll` collects it."""
    try:
        return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except (AttributeError, OSError):
        return child.poll() is not None


def _exchange(child: subprocess.Popen[bytes], data: bytes, deadline: float) -> bytes:
    """Send `data` and read the output until the command has exited and nothing more is readable.
    `NarratorError` for the deadline and for more output than the limit."""
    assert child.stdin is not None and child.stdout is not None
    writer, reader = child.stdin.fileno(), child.stdout.fileno()
    os.set_blocking(writer, False)
    os.set_blocking(reader, False)
    view, sent, output = memoryview(data), 0, bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(writer, selectors.EVENT_WRITE)
        selector.register(reader, selectors.EVENT_READ)
        while True:
            exited = _exited(child)
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not exited:
                raise NarratorError("timeout")
            ready = selector.select(0 if exited else min(POLL_S, remaining))
            for key, _ in ready:
                if key.fd == reader:
                    try:
                        chunk = os.read(reader, CHUNK)
                    except BlockingIOError:
                        continue
                    if not chunk:  # every holder of the pipe has closed it
                        selector.unregister(reader)
                    output += chunk
                    if len(output) > MAX_OUTPUT_BYTES:
                        raise NarratorError("size")
                    continue
                try:
                    sent += os.write(writer, view[sent:])
                except BlockingIOError:
                    continue
                except BrokenPipeError:  # the command exited or closed its input: not an error
                    sent = len(data)
                if sent == len(data):  # the last byte is out: close, so that the command sees EOF
                    selector.unregister(writer)
                    child.stdin.close()
            if exited and not ready:
                return bytes(output)


def _stop(child: subprocess.Popen[bytes]) -> None:
    """Kill every process of the command's group, then collect the command, then close the pipes.
    The group is killed first, whether the command is running or has exited (a process it left
    behind is in the group, whose id is the command's own)."""
    try:
        with contextlib.suppress(ProcessLookupError, PermissionError):  # no member left to kill
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    finally:
        for pipe in (child.stdin, child.stdout):
            if pipe is not None:
                pipe.close()


def _run(argv: Sequence[str], data: bytes, timeout_s: float, env: Mapping[str, str] | None) -> str:
    if not hasattr(os, "killpg"):
        raise NarratorError("start")
    deadline = time.monotonic() + timeout_s
    try:
        child = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=None if env is None else dict(env),
            bufsize=0,
            start_new_session=True,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        raise NarratorError("start") from None
    try:
        output = _exchange(child, data, deadline)
    finally:
        _stop(child)
    if child.returncode != 0:
        raise NarratorError("exit")
    if not output:
        raise NarratorError("empty")
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError:
        raise NarratorError("encoding") from None


def command_narrator(
    argv: Sequence[str], timeout_s: float, env: Mapping[str, str] | None = None
) -> Narrator:
    """A narrator that runs `argv` for each request, once, with at most `timeout_s` seconds for
    the whole exchange. `env` None is Referee's own environment, which the child inherits."""

    def narrator(request: ModelRequest) -> str:
        return _run(argv, request_bytes(request), timeout_s, env)

    return narrator
