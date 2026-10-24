"""The `referee review-design` and `review-results` commands: output, exit codes and streams."""

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from results_helpers import results_raw
from rule_helpers import write_yaml

from referee import __version__, cli
from referee.cli import main
from referee.data import DataError
from referee.findings import Finding, ResultsReview

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


# --- review-results ----------------------------------------------------------------------

LAB_EXPORT = Path(__file__).parent / "data" / "hybrid_offer_page_5000"
LAB_ID = "hybrid_offer_page"


@pytest.fixture
def results_spec_file(tmp_path: Path, raw_spec: dict) -> Path:
    return write_yaml(tmp_path, results_raw(raw_spec), "results.yaml")


@pytest.fixture(scope="module")
def export_taken_at_noon(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("export") / "export"
    shutil.copytree(LAB_EXPORT, folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["exported_at_utc"] = "2026-05-01T12:00:00Z"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


@pytest.fixture
def no_sensitivity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A review that is patched out has no origin to vary; the real one is tested apart."""
    off = {"ran": False, "reason": "patched out", "shifts": []}
    monkeypatch.setattr(cli, "origin_sensitivity", lambda spec, data, review: off)


def _review(*severities: str) -> ResultsReview:
    findings = tuple(
        Finding(
            rule_id=f"RES-00{i}",
            severity=severity,
            title="t",
            evidence={},
            why_it_matters="w",
            remediation="r",
            references=(),
        )
        for i, severity in enumerate(severities, start=1)
    )
    return ResultsReview(
        spec_id="s",
        experiment_id=LAB_ID,
        rules_run=tuple(f.rule_id for f in findings),
        findings=findings,
    )


@pytest.mark.parametrize(
    ("severities", "verdict", "status"),
    [
        ((), "clear", 0),
        (("warning",), "caution", 0),
        (("warning", "blocker"), "invalid", 1),
    ],
)
def test_the_exit_status_of_review_results_follows_the_blockers_and_nothing_else(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    no_sensitivity: None,
    results_spec_file: Path,
    severities: tuple[str, ...],
    verdict: str,
    status: int,
) -> None:
    monkeypatch.setattr(cli, "review_context", lambda context: _review(*severities))

    code, out, err = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(LAB_EXPORT),
        "--experiment-id",
        LAB_ID,
        "--format",
        "json",
    )

    assert (code, err) == (status, "")
    assert json.loads(out)["verdict"] == verdict


@pytest.mark.parametrize(
    ("spec", "folder", "options", "said"),
    [
        ("missing", "export", ["--experiment-id", LAB_ID], "missing.yaml"),
        ("good", "export", [], f"--experiment-id is required; the export holds: {LAB_ID}"),
        ("good", "nowhere", ["--experiment-id", LAB_ID], "is not a directory"),
        ("good", "empty", [], "the export holds: none"),
        ("good", "export", ["--experiment-id", LAB_ID, "--as-of", "2026-06-30"], "UTC offset"),
    ],
)
def test_input_that_cannot_be_reviewed_exits_2_and_says_why_on_stderr_only(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    raw_spec: dict,
    results_spec_file: Path,
    spec: str,
    folder: str,
    options: list[str],
    said: str,
) -> None:
    specs = {
        "good": results_spec_file,
        "missing": tmp_path / "missing.yaml",
    }
    empty = tmp_path / "empty"
    empty.mkdir()
    for name in (
        "experiment_assignments.csv",
        "experiment_exposures.csv",
        "experiment_outcomes.csv",
    ):
        header = (LAB_EXPORT / name).read_text(encoding="utf-8").splitlines()[0]
        (empty / name).write_text(header + "\n", encoding="utf-8")  # the columns, no rows
    folders = {"export": LAB_EXPORT, "empty": empty, "nowhere": tmp_path / "nowhere"}

    code, out, err = run(capsys, "review-results", str(specs[spec]), str(folders[folder]), *options)

    assert (code, out) == (2, "")
    assert err.startswith("referee: error: ")
    assert said in err


@pytest.mark.parametrize(
    ("in_manifest", "flag", "time", "source"),
    [
        (False, None, None, None),
        (False, "2026-06-30T00:00:00Z", "2026-06-30T00:00:00Z", "command line"),
        (True, None, "2026-05-01T12:00:00Z", "manifest"),
        (True, "2026-06-30T00:00:00+00:00", "2026-06-30T00:00:00Z", "command line"),
    ],
)
def test_the_time_of_the_export_is_the_flag_before_the_manifest(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    no_sensitivity: None,
    results_spec_file: Path,
    export_taken_at_noon: Path,
    in_manifest: bool,
    flag: str | None,
    time: str | None,
    source: str | None,
) -> None:
    monkeypatch.setattr(cli, "review_context", lambda context: _review())
    options = [] if flag is None else ["--as-of", flag]

    code, out, _ = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(export_taken_at_noon if in_manifest else LAB_EXPORT),
        "--experiment-id",
        LAB_ID,
        "--format",
        "json",
        *options,
    )

    assert code == 0
    as_of = json.loads(out)["as_of"]
    assert (as_of["time"], as_of["source"]) == (time, source)


def test_a_long_list_of_problems_in_the_export_is_cut_at_a_thousand_and_the_total_is_exact(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, results_spec_file: Path
) -> None:
    """The loader keeps 10,000 problems and counts them all; the command shows 1,000."""

    def refuse(folder: object, experiment_id: str) -> object:
        raise DataError([f"problem {i}" for i in range(1, 5_001)], total=12_345)

    monkeypatch.setattr(cli, "load_export", refuse)

    code, out, err = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(LAB_EXPORT),
        "--experiment-id",
        LAB_ID,
    )

    lines = err.splitlines()
    assert (code, out) == (2, "")
    assert lines[0] == "referee: error: the experiment export has 12,345 problems:"
    assert lines[1:3] == ["  - problem 1", "  - problem 2"]
    assert sum(line.startswith("  - ") for line in lines) == 1_000
    assert lines[-1] == "  ... and 11,345 more"


@pytest.mark.parametrize("output_format", ["text", "json", "memo"])
def test_the_lab_export_is_found_invalid_for_its_planted_sample_ratio_mismatch(
    capsys: pytest.CaptureFixture[str], results_spec_file: Path, output_format: str
) -> None:
    recorded = json.loads((LAB_EXPORT / "manifest.json").read_text(encoding="utf-8"))["files"]

    code, out, err = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(LAB_EXPORT),
        "--experiment-id",
        LAB_ID,
        "--format",
        output_format,
    )

    assert (code, err) == (1, "")
    if output_format == "json":
        report = json.loads(out)
        assert (report["kind"], report["verdict"]) == ("results_review", "invalid")
        assert "RES-001" in report["blocking_rule_ids"]
        assert {n: f["sha256"] for n, f in report["data"]["files"].items()} == {
            name: info["sha256"] for name, info in recorded.items()
        }
        assert [line[:7] for line in report["summary_lines"]] == ["RES-004", "RES-007", "RES-008"]
        assert report["population"]["origin_source"] == "first assignment"
        effect = report["effect"]
        assert (effect["metric"], effect["comparisons"], effect["readable"]) == (
            "purchased_7d",
            2,
            False,
        )
        assert [row["arm"] for row in effect["arms"]] == ["variant_b", "variant_c"]
        sensitivity = report["origin_sensitivity"]
        assert sensitivity["ran"] is True
        assert [shift["days_earlier"] for shift in sensitivity["shifts"]] == [1, 2, 3, 4, 5, 6]
    elif output_format == "memo":
        assert out.startswith("# Decision memo: ")
        assert [line for line in out.splitlines() if line.startswith("## ")] == [
            "## Decision",
            "## Observed facts",
            "## Assumptions and uncertainty",
            "## Data-quality qualification",
            "## Reproducibility",
        ]
        assert "Verdict: INVALID. Blocking rules: data validity RES-001" in out
    else:
        assert "Verdict: INVALID\nBlocking rules: data validity RES-001" in out
        assert "completeness was not checked" in out
        assert "Origin sensitivity: " in out
        assert "NOT TO BE READ: blocked by RES-001," in out
        assert out.count("\n  RES-0") == 3
        assert "      p_value: 6.72961e-10\n" in out  # the evidence is printed, not just pointed to
        assert max(len(line) for line in out.splitlines()) <= 100


@pytest.mark.parametrize(
    ("as_of", "said"),
    [
        (["--as-of", "2026-04-20T00:00:00Z"], "INTERIM RUN"),
        (["--as-of", "2026-06-30T00:00:00Z"], "2026-06-30T00:00:00Z (command line)"),
        ([], "completeness was not checked"),
    ],
)
def test_the_text_report_labels_an_interim_run_and_a_run_whose_completeness_is_unknown(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    no_sensitivity: None,
    results_spec_file: Path,
    as_of: list[str],
    said: str,
) -> None:
    monkeypatch.setattr(cli, "review_context", lambda context: _review())

    _, out, _ = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(LAB_EXPORT),
        "--experiment-id",
        LAB_ID,
        *as_of,
    )

    assert said in out
    assert ("INTERIM RUN" in out) == (said == "INTERIM RUN")


def test_an_internal_failure_in_review_results_exits_3_with_nothing_on_stdout(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, results_spec_file: Path
) -> None:
    def explode(context: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "review_context", explode)

    code, out, err = run(
        capsys, "review-results", str(results_spec_file), str(LAB_EXPORT), "--experiment-id", LAB_ID
    )

    assert (code, out) == (3, "")
    assert "RuntimeError: boom" in err
    assert err.rstrip().endswith("referee: error: internal error; this is a bug in Referee")


def test_one_problem_in_the_export_is_not_pluralised(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, results_spec_file: Path
) -> None:
    def refuse(folder: object, experiment_id: str) -> object:
        raise DataError(["only one"], 1)

    monkeypatch.setattr(cli, "load_export", refuse)

    code, out, err = run(
        capsys, "review-results", str(results_spec_file), str(LAB_EXPORT), "--experiment-id", LAB_ID
    )

    assert (code, out) == (2, "")
    assert err == "referee: error: the experiment export has 1 problem:\n  - only one\n"


def test_the_problems_of_an_export_against_the_spec_are_listed_one_to_a_line(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    path = write_yaml(tmp_path, raw_spec, "section_6.yaml")  # not the spec of this export

    code, out, err = run(
        capsys, "review-results", str(path), str(LAB_EXPORT), "--experiment-id", LAB_ID
    )

    lines = err.splitlines()
    assert (code, out) == (2, "")
    assert lines[0] == "referee: error: the export cannot be reviewed against the spec: 3 problems"
    assert len(lines) == 4 and all(line.startswith("  - ") for line in lines[1:])
    assert "arms the spec does not list" in lines[1]


def test_a_message_that_names_a_hostile_file_is_escaped(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    missing = tmp_path / "\x1b[31mmissing.yaml\nreferee: error: forged"

    code, out, err = run(
        capsys, "review-results", str(missing), str(LAB_EXPORT), "--experiment-id", LAB_ID
    )

    assert (code, out) == (2, "")
    assert err.count("\n") == 1 and "\x1b" not in err
    assert err.endswith(
        "missing.yaml\\nreferee: error: forged: cannot be read: No such file or directory\n"
    )
    assert "\\x1b[31mmissing.yaml" in err


def _csv_row(*cells: str) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow(cells)
    return buffer.getvalue()


def test_the_experiment_ids_listed_cannot_forge_a_line_or_move_the_terminal(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, results_spec_file: Path
) -> None:
    folder = tmp_path / "hostile"
    folder.mkdir()
    hostile = "e1\nreferee: error: forged\x1b[31m\u202e"
    for name in (
        "experiment_assignments.csv",
        "experiment_exposures.csv",
        "experiment_outcomes.csv",
    ):
        header = (LAB_EXPORT / name).read_text(encoding="utf-8").splitlines()[0]
        cells = ["x"] * (header.count(",") + 1)
        cells[header.split(",").index("experiment_id")] = hostile
        (folder / name).write_text(header + "\n" + _csv_row(*cells), encoding="utf-8")

    code, out, err = run(capsys, "review-results", str(results_spec_file), str(folder))

    assert (code, out) == (2, "")
    assert err == (
        "referee: error: --experiment-id is required; the export holds: "
        "e1\\nreferee: error: forged\\x1b[31m\\u202e\n"
    )


def test_a_file_that_cannot_be_read_after_the_checks_exits_2(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, results_spec_file: Path
) -> None:
    def fail(folder: object) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(cli, "export_file_hashes", fail)

    code, out, err = run(
        capsys, "review-results", str(results_spec_file), str(LAB_EXPORT), "--experiment-id", LAB_ID
    )

    assert (code, out) == (2, "")
    assert err == "referee: error: [Errno 5] Input/output error\n"


def test_the_files_are_hashed_as_they_were_read_and_not_as_they_are_when_the_review_ends(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    no_sensitivity: None,
    tmp_path: Path,
    results_spec_file: Path,
) -> None:
    folder = tmp_path / "export"
    shutil.copytree(LAB_EXPORT, folder)
    changing = folder / "experiment_assignments.csv"
    read = hashlib.sha256(changing.read_bytes()).hexdigest()

    def changed_while_it_runs(context: object) -> ResultsReview:
        with changing.open("ab") as handle:
            handle.write(b"\n")
        return _review()

    monkeypatch.setattr(cli, "review_context", changed_while_it_runs)

    _, out, _ = run(
        capsys,
        "review-results",
        str(results_spec_file),
        str(folder),
        "--experiment-id",
        LAB_ID,
        "--format",
        "json",
    )

    assert json.loads(out)["data"]["files"]["experiment_assignments.csv"]["sha256"] == read


@pytest.mark.parametrize("command", ["review-design", "review-results"])
def test_a_lone_surrogate_in_a_spec_is_shown_as_an_escape_and_is_not_a_crash(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict, command: str
) -> None:
    path = write_yaml(tmp_path, {**results_raw(raw_spec), "title": "PLACEHOLDER"}, "lone.yaml")
    path.write_text(
        path.read_text(encoding="utf-8").replace("PLACEHOLDER", '"a\\ud800b"'), encoding="utf-8"
    )
    where = [str(LAB_EXPORT), "--experiment-id", LAB_ID] if command == "review-results" else []

    code, out, err = run(capsys, command, str(path), *where)

    assert (code in (0, 1), err) == (True, "")
    assert "a\\ud800b" in out
