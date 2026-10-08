"""The `referee review-design` command: output, exit codes and what goes to which stream."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rule_helpers import write_yaml

from referee import __version__, cli
from referee.cli import EXIT_BLOCKED, EXIT_INTERNAL, EXIT_OK, EXIT_UNREADABLE, main

SECTION_6_SHA256 = "b0332774feccd582db109bfffff10e1330ce418ab28471ccb625fe0b00af10e8"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_process(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "referee", *argv],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


@pytest.fixture
def section_6(tmp_path: Path, raw_spec: dict) -> Path:
    return write_yaml(tmp_path, raw_spec)


@pytest.fixture
def clean(tmp_path: Path, clean_raw_spec: dict) -> Path:
    return write_yaml(tmp_path, clean_raw_spec, "clean.yaml")


def test_the_exit_codes_are_the_documented_ones() -> None:
    assert (EXIT_OK, EXIT_BLOCKED, EXIT_UNREADABLE, EXIT_INTERNAL) == (0, 1, 2, 3)


# --- A review that completes -----------------------------------------------------------


def test_a_spec_with_a_blocker_exits_1_and_prints_the_review_as_text(
    capsys: pytest.CaptureFixture[str], section_6: Path
) -> None:
    code, out, err = run(capsys, "review-design", str(section_6))

    assert code == 1
    assert err == ""
    assert out.startswith("Referee design review\n")
    assert "Recommendation: REVISE\nBlocking rules: DES-001, PRO-001\n" in out
    assert f"sha256:{SECTION_6_SHA256}" in out


def test_a_spec_with_no_blocker_exits_0(capsys: pytest.CaptureFixture[str], clean: Path) -> None:
    code, out, err = run(capsys, "review-design", str(clean))

    assert (code, err) == (0, "")
    assert "Recommendation: PROCEED\nFindings: none\n" in out


def test_warnings_alone_do_not_make_the_exit_status_1(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, clean_raw_spec: dict
) -> None:
    clean_raw_spec["procedure"]["bucketing_salt"] = None  # an info finding
    clean_raw_spec["design"]["pre_period_covariate"] = None  # a warning
    path = write_yaml(tmp_path, clean_raw_spec)

    code, out, _ = run(capsys, "review-design", str(path), "--format", "json")

    report = json.loads(out)
    assert code == 0
    assert report["recommendation"] == "proceed"
    assert [f["severity"] for f in report["findings"]] == ["warning", "info"]


@pytest.mark.parametrize("position", ["before", "after"])
def test_json_output_is_the_report(
    capsys: pytest.CaptureFixture[str], section_6: Path, position: str
) -> None:
    flags = ["--format", "json"]
    argv = (
        ["review-design", *flags, str(section_6)]
        if position == "before"
        else ["review-design", str(section_6), *flags]
    )

    code, out, err = run(capsys, *argv)

    report = json.loads(out)
    assert (code, err) == (1, "")
    assert report["spec"]["sha256"] == SECTION_6_SHA256
    assert report["referee_version"] == __version__
    assert report["blocking_rule_ids"] == ["DES-001", "PRO-001"]
    assert [f["rule_id"] for f in report["findings"]] == [
        "DES-001",
        "PRO-001",
        "DES-006",
        "DES-008",
        "PRO-002",
        "PRO-004",
    ]


def test_the_output_is_the_same_whatever_the_file_is_called_or_where_it_is(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    (tmp_path / "deep" / "er").mkdir(parents=True)
    first = write_yaml(tmp_path, raw_spec, "one.yaml")
    second = write_yaml(tmp_path / "deep" / "er", raw_spec, "another_name.yml")

    outputs = [run(capsys, "review-design", str(p), "--format", "json")[1] for p in (first, second)]

    assert outputs[0] == outputs[1] != ""


def test_a_worst_case_spec_reports_seventeen_findings(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, worst_raw_spec: dict
) -> None:
    path = write_yaml(tmp_path, worst_raw_spec)

    code, out, _ = run(capsys, "review-design", str(path), "--format", "json")

    assert code == 1
    assert len(json.loads(out)["findings"]) == 17


# --- Input that cannot be reviewed: exit 2, nothing on stdout --------------------------


def test_a_missing_file_exits_2_naming_the_path(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    missing = tmp_path / "nope.yaml"

    code, out, err = run(capsys, "review-design", str(missing))

    assert (code, out) == (2, "")
    assert err == f"referee: error: {missing}: cannot be read: No such file or directory\n"


def test_a_directory_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out, err = run(capsys, "review-design", str(tmp_path))

    assert (code, out) == (2, "")
    assert "cannot be read" in err


def test_a_repeated_key_exits_2_with_the_line(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "dup.yaml"
    path.write_text("title: a\ntitle: b\n", encoding="utf-8")

    code, out, err = run(capsys, "review-design", str(path))

    assert (code, out) == (2, "")
    assert err == f"referee: error: {path}:2:1: duplicate key 'title' (first given on line 1)\n"


def test_an_invalid_spec_exits_2_listing_every_violation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    raw_spec["design"]["alpha"] = 2
    raw_spec["design"]["power"] = 0
    path = write_yaml(tmp_path, raw_spec)

    code, out, err = run(capsys, "review-design", str(path))

    assert (code, out) == (2, "")
    lines = err.splitlines()
    assert lines[0] == f"referee: error: {path} is not a valid experiment spec (2 violations):"
    assert len(lines) == 3 and all(line.startswith("  - design.") for line in lines[1:])


def test_one_violation_is_not_pluralised(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    raw_spec["design"]["alpha"] = 2
    path = write_yaml(tmp_path, raw_spec)

    _, _, err = run(capsys, "review-design", str(path))

    assert "(1 violation):" in err


def test_an_empty_file_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    code, out, err = run(capsys, "review-design", str(path))

    assert (code, out) == (2, "")
    assert "spec: must be a mapping" in err


# --- Usage -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [[], ["review-design"], ["nonsense"], ["review-design", "x.yaml", "--format", "xml"]],
    ids=["no command", "no spec", "unknown command", "bad format"],
)
def test_a_usage_error_exits_2_with_usage_on_stderr(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out, err = run(capsys, *argv)

    assert (code, out) == (2, "")
    assert err.startswith("usage: referee")


def test_version_prints_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "--version") == (0, f"referee {__version__}\n", "")


def test_help_documents_the_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "review-design", "--help")

    flat = " ".join(out.split())  # argparse re-wraps the description
    assert code == 0
    assert "0 no blocker found" in flat and "3 internal error" in flat


def test_an_exit_request_that_is_not_a_status_counts_as_a_usage_failure(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """argparse always exits with an integer; anything else must not become 0 or crash."""

    def refuse() -> None:
        raise SystemExit("a message instead of a status")

    monkeypatch.setattr(cli, "build_parser", refuse)

    assert run(capsys, "review-design", "x.yaml")[0] == 2


# --- A failure inside Referee: exit 3, never 1 -----------------------------------------


def test_an_internal_failure_exits_3_so_it_is_not_mistaken_for_a_blocker(
    capsys: pytest.CaptureFixture[str], section_6: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(spec: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "review_design", explode)

    code, out, err = run(capsys, "review-design", str(section_6))

    assert (code, out) == (3, "")
    assert "RuntimeError: boom" in err
    assert err.rstrip().endswith("referee: error: internal error; this is a bug in Referee")


# --- As a real process -----------------------------------------------------------------


def test_python_dash_m_referee_exits_with_the_documented_statuses(
    section_6: Path, clean: Path, tmp_path: Path
) -> None:
    blocked = run_process("review-design", str(section_6))
    ok = run_process("review-design", str(clean))
    unreadable = run_process("review-design", str(tmp_path / "missing.yaml"))

    assert (blocked.returncode, ok.returncode, unreadable.returncode) == (1, 0, 2)
    assert "REVISE" in blocked.stdout and blocked.stderr == ""
    assert unreadable.stdout == "" and "cannot be read" in unreadable.stderr


def test_a_terminal_that_cannot_show_a_character_gets_an_escape_not_a_crash(
    tmp_path: Path, raw_spec: dict
) -> None:
    raw_spec["title"] = "Café – offer page"
    path = write_yaml(tmp_path, raw_spec)

    result = run_process("review-design", str(path), env={"PYTHONIOENCODING": "ascii"})

    assert result.returncode == 1
    assert "Caf\\xe9 \\u2013 offer page" in result.stdout
    assert result.stderr == ""


def test_the_command_is_deterministic_across_processes(section_6: Path) -> None:
    first = run_process("review-design", str(section_6), "--format", "json")
    second = run_process("review-design", str(section_6), "--format", "json")

    assert first.stdout == second.stdout != ""


def test_an_unquoted_impossible_start_time_exits_2_not_3(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, clean_raw_spec: dict
) -> None:
    path = write_yaml(tmp_path, clean_raw_spec)
    text = path.read_text(encoding="utf-8").replace(
        "design:\n", "design:\n  start_utc: 2026-02-30T00:00:00Z\n"
    )
    assert "start_utc" in text
    path.write_text(text, encoding="utf-8")

    code, out, err = run(capsys, "review-design", str(path))

    assert (code, out) == (2, "")
    assert err.startswith(f"referee: error: {path}: ") and "day is out of range" in err
