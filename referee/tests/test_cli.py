"""The `referee review-design` command: output, exit codes and what goes to which stream."""

import json
from pathlib import Path

import pytest
from rule_helpers import write_yaml

from referee import __version__, cli
from referee.cli import main

SECTION_6_SHA256 = "b0332774feccd582db109bfffff10e1330ce418ab28471ccb625fe0b00af10e8"


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def section_6(tmp_path: Path, raw_spec: dict) -> Path:
    return write_yaml(tmp_path, raw_spec)


@pytest.fixture
def clean(tmp_path: Path, clean_raw_spec: dict) -> Path:
    return write_yaml(tmp_path, clean_raw_spec, "clean.yaml")


# --- A review that completes -----------------------------------------------------------


def test_a_worst_case_spec_reports_eighteen_findings(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, worst_raw_spec: dict
) -> None:
    path = write_yaml(tmp_path, worst_raw_spec)

    code, out, _ = run(capsys, "review-design", str(path), "--format", "json")

    assert code == 1
    assert len(json.loads(out)["findings"]) == 18


# --- Input that cannot be reviewed: exit 2, nothing on stdout --------------------------


def test_a_missing_file_exits_2_naming_the_path(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    missing = tmp_path / "nope.yaml"

    code, out, err = run(capsys, "review-design", str(missing))

    assert (code, out) == (2, "")
    assert err == f"referee: error: {missing}: cannot be read: No such file or directory\n"


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


@pytest.mark.parametrize("argv", [[]], ids=["no command"])
def test_a_usage_error_exits_2_with_usage_on_stderr(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out, err = run(capsys, *argv)

    assert (code, out) == (2, "")
    assert err.startswith("usage: referee")


def test_version_prints_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "--version") == (0, f"referee {__version__}\n", "")


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
