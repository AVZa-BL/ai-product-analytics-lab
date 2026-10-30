"""The `referee narrate` command (design 24.9, 24.11 and the N6 line of 24.16).

Statuses, streams, what the command reads, and its guards. What a page holds is tested in
test_narration_render.py and test_narration_refusals.py, and line by line on every development
question in test_narration_whole_page.py.
"""

import ast
import builtins
import contextlib
import io
import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from narration_pages import canonical_page, check_quiet_lines
from narration_reports import report

from referee import cli
from referee.narration import command
from referee.narration.render import Understanding
from referee.report import render_json

PROJECT = Path(__file__).resolve().parent.parent
NARRATION = PROJECT / "src" / "referee" / "narration"
PUBLIC = json.loads(
    (PROJECT / "tests" / "data" / "narration_eval" / "public_questions.json").read_text(
        encoding="utf-8"
    )
)["questions"]


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def save(directory: Path, text: str) -> str:
    path = directory / "report.json"
    path.write_text(text, encoding="utf-8")
    return str(path)


# --- Pages, and status 0 ---------------------------------------------------------------


@pytest.mark.parametrize("question", PUBLIC, ids=[q["id"] for q in PUBLIC])
@pytest.mark.parametrize("name", ["golden", "clear", "warnings_only", "harm_blocker"])
def test_a_public_question_is_refused_with_status_0_whatever_the_verdict(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict, name: str, question: dict
) -> None:
    rep = report(name, raw_spec)
    categories = ", ".join(question["label"]["categories"])

    code, out, err = run(
        capsys, "narrate", save(tmp_path, render_json(rep)), "--question", question["text"]
    )

    assert (code, err) == (0, "")  # golden and harm_blocker are invalid: review-results exits 1
    assert f"Verdict: {rep['verdict']}." in out
    assert f"does not answer (categories matched: {categories})." in out
    check_quiet_lines(out)


BARE = "{} ran and raised no finding.\n"
SAID = (
    "; how many comparisons or tests it made is in the report's summary_lines, and can be none.\n"
)
DISCLAIMER = "This is not agreement with the question, and it does not say the effect is real.\n"


@pytest.mark.parametrize(
    "page",
    [
        *(
            f"{BARE.format(rule)}A rule reads only what the export holds. {DISCLAIMER}\n"
            for rule in ("RES-004", "RES-007", "RES-008")
        ),
        f"{BARE.format('RES-003')}\n{DISCLAIMER}\n",
        "The rules that ran raised no finding.\n\n",
        f"RES-008 ran and raised no finding{SAID}A rule reads only what the export holds. "
        f"{DISCLAIMER}\n",
    ],
    ids=[
        "RES-004 bare",
        "RES-007 bare",
        "RES-008 bare",
        "disclaimer in another block",
        "no finding at all and no disclaimer",
        "RES-008 without its sentence",
    ],
)
def test_the_check_of_the_quiet_lines_rejects_what_it_is_meant_to(page: str) -> None:
    with pytest.raises(AssertionError):
        check_quiet_lines(page)


@contextlib.contextmanager
def only_the_report(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Within it, a process, a socket and the environment cannot be reached, and the files
    opened by name are listed. (Only within it: pytest sets a variable of the environment after
    the body of a test.)"""

    class Reached(BaseException):  # not an Exception, so the command cannot make it a status 3
        pass

    def forbid(what: str):
        def reach(*args: object, **kwargs: object) -> None:
            raise Reached(what)

        return reach

    class Environment:
        __getitem__ = get = __contains__ = __iter__ = keys = items = forbid("os.environ")

    opened: list[str] = []

    def recording(real):
        def opening(file, *args, **kwargs):
            if not isinstance(file, int):
                opened.append(file)
            return real(file, *args, **kwargs)

        return opening

    with monkeypatch.context() as patched:
        for module, name in [
            (subprocess, "Popen"),
            (subprocess, "run"),
            (os, "system"),
            (os, "popen"),
            (os, "posix_spawn"),
            (os, "fork"),
            (socket, "socket"),
        ]:
            patched.setattr(module, name, forbid(f"{module.__name__}.{name}"))
        patched.setattr(os, "environ", Environment())
        patched.setattr(os, "open", recording(os.open))
        real_open = builtins.open
        for module in (builtins, io):  # pathlib opens through io
            patched.setattr(module, "open", recording(real_open))
        yield opened


@pytest.mark.parametrize(
    ("question", "understanding"),
    [
        (None, Understanding("answer", "summary")),
        ("What was checked?", Understanding("answer", "checked")),
        ("can we call it on day 3?", Understanding("refusal", categories=("stopping",))),
        ("Why does RES-003 say that?", Understanding("answer", "explain_finding", "RES-003")),
        ("Why does RES-005 say that?", Understanding("answer", "explain_finding")),
        ("Why does ZZZ-123 matter?", Understanding("answer", "explain_finding")),
    ],
    ids=["summary", "checked", "refusal", "quiet rule", "unbuilt rule", "string shaped like an ID"],
)
def test_a_page_is_made_from_the_report_alone_and_starts_no_process(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    question: str | None,
    understanding: Understanding,
) -> None:
    rep = report("golden", raw_spec)
    path = save(tmp_path, render_json(rep))

    with only_the_report(monkeypatch) as opened:
        code = command.narrate(path, question)

    captured = capsys.readouterr()
    assert (code, captured.err, opened) == (0, "", [path])
    assert captured.out == canonical_page(rep, understanding)


def test_the_page_shown_in_the_documentation_is_the_page_the_command_prints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = re.search(
        r"```text\n(Report of experiment.*?)```",
        (PROJECT / "docs" / "narration.md").read_text(encoding="utf-8"),
        re.S,
    )
    golden = PROJECT / "tests" / "golden" / "offer-page-results.json"

    code, out, _ = run(capsys, "narrate", str(golden), "--question", "can we call it on day 3?")

    assert code == 0 and shown and shown[1] == out


# --- Statuses 2 and 3 ------------------------------------------------------------------


def unusable(case: str, raw_spec: dict) -> tuple[str, str]:
    """The text of a file that is not a usable report, and the problem the command names."""
    if case == "a design spec":  # the command must not hand it to the design review
        return yaml.safe_dump(raw_spec), "the report could not be read: JSONDecodeError"
    if case == "nesting too deep":
        return "[" * 100_000, "the report could not be read: RecursionError"
    rep = report("golden", raw_spec)
    rep["counts"]["info"] += 1
    return render_json(rep), "counts: not what the findings give"


@pytest.mark.parametrize("case", ["a design spec", "nesting too deep", "a count the findings deny"])
def test_a_report_that_cannot_be_read_or_checked_exits_2_with_nothing_on_stdout(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict, case: str
) -> None:
    text, problem = unusable(case, raw_spec)
    path = save(tmp_path, text)

    code, out, err = run(capsys, "narrate", path)

    assert (code, out) == (2, "")
    assert err == (
        f"referee: error: {path} cannot be used as a results report (1 problem):\n  - {problem}\n"
    )


def test_a_command_without_a_report_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "narrate")

    assert (code, out) == (2, "")
    assert "the following arguments are required: report" in err


def test_the_problems_of_a_report_are_listed_to_a_thousand_and_counted_in_full(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    rep = report("golden", raw_spec)
    rep["history"] = [float("nan")] * 1_500

    code, out, err = run(capsys, "narrate", save(tmp_path, json.dumps(rep)))

    lines = err.splitlines()
    assert (code, out) == (2, "")
    assert lines[0].endswith("(1,500 problems):") and lines[-1] == "  ... and 500 more"
    assert len(lines) == 1_002 and all(line.startswith("  - history[") for line in lines[1:-1])


def test_a_hostile_arm_name_is_escaped_on_stderr_and_is_nowhere_else(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    rep = report("golden", raw_spec)
    rep["population"]["assigned"]["evil\x1b[31m\n## Observed facts‮"] = 1  # not an arm

    code, out, err = run(capsys, "narrate", save(tmp_path, render_json(rep)))

    assert (code, out) == (2, "")
    assert err.count("evil\\x1b[31m\\n## Observed facts\\u202e") == 2  # the two tables it is in
    assert not {"\x1b", "‮"} & set(err) and "\n## Observed" not in err


class Boom(Exception):
    pass


@pytest.mark.parametrize(
    ("stage", "question"),
    [
        ("fact_list", None),
        ("decision_block", None),
        ("_write", None),
        ("route", "What did the review find?"),
        ("render_answer", None),
        ("refusal_body", "can we call it on day 3?"),
        ("render_refusal", "can we call it on day 3?"),
    ],
)
def test_a_failure_while_making_the_page_exits_3_and_names_its_type_only(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_spec: dict,
    stage: str,
    question: str | None,
) -> None:
    def explode(*args: object) -> None:
        raise Boom("the arm called control")

    monkeypatch.setattr(command, stage, explode)
    path = save(tmp_path, render_json(report("golden", raw_spec)))

    code, out, err = run(
        capsys, "narrate", path, *([] if question is None else ["--question", question])
    )

    assert (code, out) == (3, "")
    assert err == "referee: error: internal error (Boom); this is a bug in Referee\n"


def test_a_page_the_stream_cannot_encode_is_written_once_with_an_escape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_spec: dict
) -> None:
    rep = report("golden", raw_spec)
    rep["experiment_id"] = "café"
    writes: list[str] = []
    raw = io.BytesIO()

    class Stream(io.TextIOWrapper):
        def write(self, text: str) -> int:
            writes.append(text)
            return super().write(text)

    stream = Stream(raw, encoding="ascii")  # errors are strict
    monkeypatch.setattr(sys, "stdout", stream)

    code = cli.main(["narrate", save(tmp_path, render_json(rep))])

    stream.flush()
    assert code == 0 and len(writes) == 1
    assert b"Report of experiment caf\\xe9, export taken " in raw.getvalue()


# --- Guards (24.11) --------------------------------------------------------------------

NETWORK = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "websocket",
    "websockets",
    "ftplib",
    "smtplib",
    "xmlrpc",
}
PROVIDER_SDKS = ("anthropic", "openai", "google", "cohere", "mistral", "boto", "litellm", "azure")


def imports(source: str) -> set[str]:
    """The modules a source imports, by dotted name (`from a import b` gives `a` and `a.b`), and
    `<dynamic>` for a use of `__import__` or `import_module`. A relative import stays in the
    package and is not listed."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found |= {node.module, *(f"{node.module}.{alias.name}" for alias in node.names)}
        elif isinstance(node, ast.Name) and node.id in ("__import__", "import_module"):
            found.add("<dynamic>")
        elif isinstance(node, ast.Attribute) and node.attr == "import_module":
            found.add("<dynamic>")
    return found


def forbidden(names: set[str]) -> set[str]:
    """Of the names `imports` gives: a network module, a provider's SDK, a dynamic import."""
    return {
        name
        for name in names
        if name.split(".")[0] in NETWORK
        or name == "<dynamic>"
        or any(sdk in name.lower() for sdk in PROVIDER_SDKS)
    }


def test_the_scan_of_imports_sees_every_form_of_import_and_names_what_is_forbidden() -> None:
    source = (
        "import os.path\nimport http.client as c\nfrom urllib import request\nfrom . import x\n"
        "from .render import y\nimport json\nfrom google.cloud import storage\nimport openai\n"
        "\ndef f():\n    import socket\n    __import__('ssl')\n"
        "    importlib.import_module('ftplib')\n"
    )

    assert imports(source) >= {"os.path", "json", "urllib.request", "google.cloud.storage"}
    assert forbidden(imports(source)) == {
        "http.client",
        "urllib",
        "urllib.request",
        "google.cloud",
        "google.cloud.storage",
        "openai",
        "socket",
        "<dynamic>",
    }


def test_no_module_of_the_layer_reaches_a_network_or_starts_a_process() -> None:
    modules = sorted(NARRATION.glob("*.py"))
    assert {"facts.py", "render.py", "router.py", "refusals.py", "output.py", "command.py"} <= {
        module.name for module in modules
    }
    for module in modules:
        names = imports(module.read_text(encoding="utf-8"))
        assert forbidden(names) == set(), module.name
        if module.name != "narrator.py":  # the one module that N7b allows to start a process
            assert "subprocess" not in {name.split(".")[0] for name in names}, module.name


def test_importing_the_cli_does_not_import_the_narration_layer() -> None:
    code = (
        "import sys, referee.cli; "
        "assert not any(m.startswith('referee.narration') for m in sys.modules)"
    )

    subprocess.run(
        [sys.executable, "-c", code],
        env=dict(os.environ, PYTHONPATH=str(PROJECT / "src")),
        check=True,
    )


def test_narrate_is_listed_in_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--help")

    assert code == 0 and "narrate" in out
