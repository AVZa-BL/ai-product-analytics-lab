"""A stand-in for the user's command (design 24.5, N7b): a Python script run with `sys.executable`.

    argv = stub_argv(tmp_path, mode, *arguments)    # [python, script, mode, MARKER, *arguments]

The script is written to the directory. The marker is in its arguments and on its standard error,
and in the modes that fail on its standard output too, so that a test can require that it is on no
stream of Referee. A mode that waits waits at most 20 s, so that a fault in the code under test
leaves nothing running for long. A mode that starts a grandchild, which holds the standard output
and the input of the command, records `<child pid> <grandchild pid>` in `pids.txt` of the directory
once the grandchild is running.

    exit            exits 3
    sleep [hold]    waits, ignoring SIGTERM (after starting a grandchild, with `hold`)
    empty           exits 0 with nothing on standard output
    size N          writes N bytes (the marker repeated) and exits 0
    encoding        writes bytes that are not UTF-8 and exits 0
    tty             tries to open /dev/tty, records in `tty.txt` whether it could, and exits 1
    leave CODE PATH starts a grandchild, writes the file at PATH, exits with CODE
    interrupt       starts a grandchild, sends SIGINT to its parent (the process under test), waits
    cat PATH        does not read its input; writes the file at PATH and exits 0
    select          reads the request, keeps it as `request.bin`, and selects, from the sheet in
                    it, all that the intent offers
    env NAME        writes the value of the environment variable NAME
    hash            writes the SHA-256 of the input it reads to the end
"""

import contextlib
import os
import signal
import sys
import time
from collections.abc import Iterator
from pathlib import Path

MARKER = "MARKER-4f1c9a7e"
VALID = '{"schema": "referee-narration-output/1", "findings": []}'

SCRIPT = r'''
import hashlib, json, os, signal, subprocess, sys, time

mode, marker, *rest = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
sys.stderr.write(marker)
if mode in ("exit", "sleep", "encoding", "tty"):
    sys.stdout.write(marker)
    sys.stdout.flush()


def grandchild():
    """Starts a process that holds the standard output and the input of this one and waits, and
    returns once that process has written its pid down."""
    reader, writer = os.pipe()
    code = (
        "import os, sys, time\n"
        "open(sys.argv[1] + '/grandchild.txt', 'w').write(str(os.getpid()))\n"
        "os.write(int(sys.argv[2]), b'x')\n"
        "time.sleep(20)\n"
    )
    subprocess.Popen([sys.executable, "-c", code, here, str(writer)], pass_fds=[writer])
    os.close(writer)
    os.read(reader, 1)
    os.close(reader)
    with open(here + "/pids.txt", "w") as pids:
        pids.write(f"{os.getpid()} {open(here + '/grandchild.txt').read()}")


if mode == "exit":
    sys.exit(3)
elif mode == "sleep":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)  # and so does a grandchild, which inherits it
    if rest and rest[0] == "hold":
        grandchild()
    time.sleep(20)
elif mode == "size":
    sys.stdout.write((marker * int(rest[0]))[: int(rest[0])])
elif mode == "encoding":
    sys.stdout.buffer.write(b"\xff\xfe")
elif mode == "tty":
    try:
        open("/dev/tty", "w").write(marker)
        opened = "yes"
    except OSError:
        opened = "no"
    open(here + "/tty.txt", "w").write(opened)
    sys.exit(1)
elif mode == "leave":
    grandchild()
    sys.stdout.write(open(rest[1]).read())
    sys.stdout.flush()
    sys.exit(int(rest[0]))
elif mode == "interrupt":
    grandchild()
    os.kill(os.getppid(), signal.SIGINT)
    time.sleep(20)
elif mode == "cat":
    sys.stdout.write(open(rest[0]).read())
elif mode == "hash":
    sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())
elif mode == "env":
    sys.stdout.write(os.environ.get(rest[0], ""))
elif mode == "select":
    raw = sys.stdin.buffer.read()
    open(here + "/request.bin", "wb").write(raw)
    sheet = json.loads(json.loads(raw)["user"])
    entries = [
        {
            "id": finding["rule_id"],
            "facts": [fact["id"] for fact in finding["facts"]],
            "sentences": [sentence["id"] for sentence in finding["sentences"]],
        }
        for finding in sheet["findings"]
    ]
    sys.stdout.write(json.dumps({"schema": "referee-narration-output/1", "findings": entries}))
'''


def stub_argv(directory: Path, mode: str, *arguments: str) -> list[str]:
    """The command that runs the stub in `mode`; the marker is its second argument."""
    script = directory / "stub.py"
    script.write_text(SCRIPT, encoding="utf-8")
    return [sys.executable, str(script), mode, MARKER, *arguments]


def alive(pid: int) -> bool:
    """Whether the process exists and is not a zombie. A process that is killed after its parent
    has gone stays one until its new parent collects it (where /proc says so it is counted as
    gone; elsewhere the parent that adopts it collects it at once)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] != "Z"
    except OSError:
        return True


def gone(*pids: int, wait_s: float = 5.0) -> bool:
    """Whether none of the processes is alive within `wait_s`: one that has been sent SIGKILL takes
    a moment to be gone, and this waits for that, not for a time that it then asserts."""
    end = time.monotonic() + wait_s
    while any(alive(pid) for pid in pids):
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


def recorded(directory: Path) -> tuple[int, int]:
    """The pids a mode that starts a grandchild wrote down: the child's and the grandchild's."""
    child, grandchild = (directory / "pids.txt").read_text().split()
    assert child != grandchild  # two processes
    return int(child), int(grandchild)


@contextlib.contextmanager
def sigint_raises() -> Iterator[None]:
    """Within it SIGINT is a KeyboardInterrupt, whatever disposition the test runner inherited (a
    job started in the background ignores it, and Python then leaves it ignored)."""
    before = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, before)


@contextlib.contextmanager
def returns_within(seconds: float) -> Iterator[None]:
    """Fails the test, instead of letting it hang, if the block has not ended after `seconds`.
    Only for the main thread (it uses SIGALRM); a limit, never a measurement."""

    def expired(*_: object) -> None:
        raise AssertionError(f"did not return within {seconds} s")

    before = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, before)
