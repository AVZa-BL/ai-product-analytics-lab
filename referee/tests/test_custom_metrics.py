"""Metrics the spec names: columns of the analyst's own export (design section 28)."""

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

from referee.cli import main
from referee.data import load_export
from referee.loader import load_spec
from referee.monitor import monitor_report
from referee.results import ResultsContext
from referee.rules.guardrails import guardrail_report

FOLDER = Path(__file__).parents[1] / "examples" / "custom-metrics"
ARGS = ("--experiment-id", "tutorial_test", "--as-of", "2026-03-20T00:00:00Z")


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def copy_with(tmp_path: Path, *, spec=None, outcomes=None) -> tuple[Path, Path]:
    """The example in `tmp_path`, with its spec (a dict -> dict function) or its outcomes (a rows
    -> rows function) changed."""
    folder = tmp_path / "export"
    shutil.copytree(FOLDER, folder)
    if spec is not None:
        raw = yaml.safe_load((FOLDER / "spec.yaml").read_text())
        (folder / "spec.yaml").write_text(yaml.safe_dump(spec(raw), sort_keys=False))
    if outcomes is not None:
        path = folder / "experiment_outcomes.csv"
        rows = list(csv.DictReader(path.open()))
        rows = outcomes(rows)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return folder / "spec.yaml", folder


def report(spec_path: Path, folder: Path) -> dict:
    data = load_export(folder, "tutorial_test")
    from dataclasses import replace

    from referee.data import parse_utc

    data = replace(data, exported_at=parse_utc("2026-03-20T00:00:00Z"))
    return monitor_report(load_spec(spec_path), data, file_hashes={}, as_of_source="command line")


def test_the_monitor_reads_the_columns_the_spec_names_and_gets_the_numbers_of_the_file() -> None:
    result = report(FOLDER / "spec.yaml", FOLDER)

    assert result["status"] == "on_track"
    assert [(e["role"], e["name"], e["column"], e["family"]) for e in result["ledger"]] == [
        ("primary", "tutorial_completion", "tutorial_done", "binary"),
        ("guardrail", "session_minutes", "minutes_played", "other"),
        ("other", "levels_cleared", "levels_cleared", "count"),
    ]
    assert all(e["evaluated"] for e in result["ledger"])
    # the difference of the rates, worked out from the file by hand
    arm = {
        r["player_id"]: r["arm"]
        for r in csv.DictReader((FOLDER / "experiment_assignments.csv").open())
    }
    done: dict[str, list[int]] = {"control": [], "variant_a": []}
    levels: dict[str, list[int]] = {"control": [], "variant_a": []}
    for row in csv.DictReader((FOLDER / "experiment_outcomes.csv").open()):
        done[arm[row["player_id"]]].append(int(row["tutorial_done"]))
        levels[arm[row["player_id"]]].append(int(row["levels_cleared"]))
    rate = {a: sum(v) / len(v) for a, v in done.items()}
    primary = result["primary_metric"]["arms"][0]
    assert primary["difference"] == pytest.approx(rate["variant_a"] - rate["control"], abs=1e-6)
    mean = {a: sum(v) / len(v) for a, v in levels.items()}
    secondary = result["secondary_metrics"][0]["arms"][0]
    assert secondary["difference"] == pytest.approx(mean["variant_a"] - mean["control"], abs=1e-6)
    assert "p_value" not in json.dumps(result["secondary_metrics"])


def test_a_declared_family_decides_what_a_guardrail_is_read_as() -> None:
    spec = load_spec(FOLDER / "spec.yaml")
    context = ResultsContext.of(spec, load_export(FOLDER, "tutorial_test"))
    assert guardrail_report(context)["tests"][0]["family"] == "other"

    revenue = load_spec(FOLDER / "spec.yaml").to_dict()
    revenue["guardrails"][0]["family"] = "revenue_like"
    from referee.spec import ExperimentSpec

    context = ResultsContext.of(
        ExperimentSpec.from_dict(revenue), load_export(FOLDER, "tutorial_test")
    )
    assert guardrail_report(context)["tests"][0]["family"] == "revenue_like"


@pytest.mark.parametrize(
    ("change", "reason", "role"),
    [
        ("misnamed", "column_missing", "guardrail"),
        ("not_binary", "values_not_binary", "primary"),
        ("empty_cell", "column_not_numeric", "other"),
    ],
)
def test_a_column_that_cannot_be_read_is_reported_with_its_reason_and_never_ignored(
    tmp_path: Path, change: str, reason: str, role: str
) -> None:
    def spec(raw: dict) -> dict:
        if change == "misnamed":
            raw["guardrails"][0]["column"] = "minutes_playd"
        return raw

    def outcomes(rows: list) -> list:
        if change == "not_binary":
            rows[3]["tutorial_done"] = "2"
        if change == "empty_cell":
            rows[5]["levels_cleared"] = ""
        return rows

    spec_path, folder = copy_with(tmp_path, spec=spec, outcomes=outcomes)

    if role == "primary":
        with pytest.raises(Exception, match=reason):
            report(spec_path, folder)
        return
    result = report(spec_path, folder)
    unread = [e for e in result["ledger"] if not e["evaluated"]]
    assert [(e["role"], e["reason"]) for e in unread] == [(role, reason)]
    assert result["status"] == "attention"
    assert any(r["rule_id"] == "ledger" for r in result["reasons"])


def test_the_command_refuses_a_misnamed_primary_column_and_notes_the_unread_secondary_metrics(
    capsys, tmp_path: Path
) -> None:
    spec_path, folder = copy_with(
        tmp_path,
        spec=lambda raw: {
            **raw,
            "primary_metric": {**raw["primary_metric"], "column": "tutorial_don"},
        },
    )
    code, out, err = run(
        capsys, "review-results", str(spec_path), str(folder), *ARGS, "--mode", "monitor"
    )
    assert (code, out) == (2, "") and "tutorial_don" in err and "column_missing" in err

    code, out, err = run(capsys, "review-results", str(FOLDER / "spec.yaml"), str(FOLDER), *ARGS)
    assert "secondary metrics (levels_cleared) are not analysed in a results review" in err
    assert code == 1  # RES-002 and RES-003 block an experiment that has not ended


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda raw: raw["primary_metric"].update(column="player_id"), "reads for another purpose"),
        (lambda raw: raw["primary_metric"].update(column="bad name"), "must be a column name"),
        (
            lambda raw: raw["secondary_metrics"][0].update(name="tutorial_completion"),
            "already the primary",
        ),
        (lambda raw: raw["secondary_metrics"][0].update(family="rare"), "family"),
    ],
)
def test_the_spec_refuses_a_metric_declared_badly(change, fragment: str) -> None:
    from referee.spec import ExperimentSpec, SpecError

    raw = yaml.safe_load((FOLDER / "spec.yaml").read_text())
    change(raw)
    with pytest.raises(SpecError, match=fragment):
        ExperimentSpec.from_dict(raw)
