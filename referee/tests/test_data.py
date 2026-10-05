"""Reading an experiment's export: every row, the right types, and a located message for every
way the files can be wrong."""

import csv
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from referee import data
from referee.data import (
    Assignment,
    DataError,
    Exposure,
    Outcome,
    list_experiment_ids,
    load_export,
)

ASSIGNMENT_COLUMNS = ["experiment_id", "player_id", "arm", "assigned_at_utc", "arm_config_version"]
EXPOSURE_COLUMNS = ["experiment_id", "player_id", "exposed_at_utc", "arm_config_version"]
OUTCOME_COLUMNS = [
    "experiment_id",
    "player_id",
    "sessions_7d",
    "purchases_7d",
    "revenue_usd_7d",
    "first_purchase_at_utc",
]


def _row(columns: list[str], *values: object) -> dict[str, str]:
    return dict(zip(columns, (str(value) for value in values), strict=True))


def _assignments() -> list[dict[str, str]]:
    cols = ASSIGNMENT_COLUMNS
    return [
        _row(cols, "e1", "p1", "control", "2026-04-11 00:02:25+00", 1),
        _row(cols, "e1", "p2", "variant_b", "2026-04-11 00:08:33+00", 1),
        _row(cols, "e1", "p3", "control", "2026-04-12 09:00:00+00", 1),
        _row(cols, "e1", "p4", "variant_b", "2026-04-26 12:30:00+00", 2),
    ]


def _exposures() -> list[dict[str, str]]:
    cols = EXPOSURE_COLUMNS
    return [
        _row(cols, "e1", "p1", "2026-04-11 00:05:00+00", 1),
        _row(cols, "e1", "p2", "2026-04-11 00:10:00+00", 1),
        _row(cols, "e1", "p2", "2026-04-13 08:00:00+00", 1),
        _row(cols, "e1", "p4", "2026-04-26 12:31:00+00", 2),
    ]  # p3 was never exposed, which the contract allows


def _outcomes() -> list[dict[str, str]]:
    cols = OUTCOME_COLUMNS
    return [
        _row(cols, "e1", "p1", 3, 0, "0.0", ""),
        _row(cols, "e1", "p2", 5, 1, "4.99", "2026-04-12 10:00:00+00"),
        _row(cols, "e1", "p3", 0, 0, "0.0", ""),
        _row(cols, "e1", "p4", 7, 2, "19.5", "2026-04-27 01:00:00+00"),
    ]


def _write(folder: Path, name: str, rows: list[dict[str, str]], *, columns=None) -> None:
    header = columns if columns is not None else list(rows[0])
    with (folder / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export(folder: Path, *, assignments=None, exposures=None, outcomes=None, **columns) -> Path:
    """Write a valid three-file export, replacing any part with `assignments=`, `outcomes=`..."""
    _write(
        folder,
        data.ASSIGNMENTS_FILE,
        assignments if assignments is not None else _assignments(),
        columns=columns.get("assignment_columns"),
    )
    _write(
        folder,
        data.EXPOSURES_FILE,
        exposures if exposures is not None else _exposures(),
        columns=columns.get("exposure_columns"),
    )
    _write(
        folder,
        data.OUTCOMES_FILE,
        outcomes if outcomes is not None else _outcomes(),
        columns=columns.get("outcome_columns"),
    )
    return folder


def _problems(folder: Path, experiment_id: str = "e1") -> tuple[str, ...]:
    with pytest.raises(DataError) as caught:
        load_export(folder, experiment_id)
    return caught.value.problems


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


# --- A valid export ----------------------------------------------------------------------


def test_every_row_is_read_with_its_types(tmp_path: Path) -> None:
    loaded = load_export(export(tmp_path), "e1")

    assert loaded.experiment_id == "e1"
    assert loaded.assignments[0] == Assignment("p1", "control", _utc(2026, 4, 11, 0, 2, 25), 1)
    assert loaded.assignments[3] == Assignment("p4", "variant_b", _utc(2026, 4, 26, 12, 30), 2)
    assert len(loaded.assignments) == 4 and len(loaded.exposures) == 4
    assert loaded.exposures[1] == Exposure("p2", _utc(2026, 4, 11, 0, 10), 1)
    assert loaded.outcomes[0] == Outcome("p1", 3, 0, 0.0, None)
    assert loaded.outcomes[1] == Outcome("p2", 5, 1, 4.99, _utc(2026, 4, 12, 10))
    assert all(
        isinstance(row.assigned_at, datetime) and row.assigned_at.utcoffset().total_seconds() == 0
        for row in loaded.assignments
    )


def test_the_order_of_the_rows_in_the_files_does_not_change_what_is_read(tmp_path: Path) -> None:
    (tmp_path / "in_order").mkdir()
    (tmp_path / "shuffled").mkdir()
    shuffled = random.Random(7)
    parts = {"assignments": _assignments(), "exposures": _exposures(), "outcomes": _outcomes()}
    for rows in parts.values():
        shuffled.shuffle(rows)

    assert load_export(export(tmp_path / "shuffled", **parts), "e1") == load_export(
        export(tmp_path / "in_order"), "e1"
    )


def test_a_player_with_several_exposures_has_them_in_time_order(tmp_path: Path) -> None:
    rows = _exposures()
    rows[1], rows[2] = rows[2], rows[1]  # the later exposure of p2 comes first in the file

    loaded = load_export(export(tmp_path, exposures=rows), "e1")

    assert [e.exposed_at for e in loaded.exposures if e.player_id == "p2"] == [
        _utc(2026, 4, 11, 0, 10),
        _utc(2026, 4, 13, 8),
    ]


def test_extra_columns_a_byte_order_mark_and_other_experiments_are_tolerated(
    tmp_path: Path,
) -> None:
    extra_assignments = [dict(row, scenario_run_id="r1") for row in _assignments()]
    other = _row(ASSIGNMENT_COLUMNS, "other", "px", "control", "not a time", "x")  # never checked
    export(tmp_path, assignments=[*extra_assignments, dict(other, scenario_run_id="r1")])
    path = tmp_path / data.OUTCOMES_FILE
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    loaded = load_export(tmp_path, "e1")

    assert [a.player_id for a in loaded.assignments] == ["p1", "p2", "p3", "p4"]
    assert len(loaded.outcomes) == 4


def test_the_exposures_file_may_omit_the_config_version(tmp_path: Path) -> None:
    columns = ["experiment_id", "player_id", "exposed_at_utc"]
    loaded = load_export(export(tmp_path, exposure_columns=columns), "e1")

    assert {e.config_version for e in loaded.exposures} == {None}


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-04-11 00:02:25+00",
        "2026-04-11T00:02:25Z",
        "2026-04-11T00:02:25+00:00",
        "2026-04-11 00:02:25.250000+00",
    ],
)
def test_timestamps_in_the_formats_duckdb_and_iso_8601_write_are_read_as_utc(
    tmp_path: Path, stamp: str
) -> None:
    rows = _assignments()
    rows[0]["assigned_at_utc"] = stamp

    moment = load_export(export(tmp_path, assignments=rows), "e1").assignments[0].assigned_at

    assert moment.date().isoformat() == "2026-04-11" and moment.utcoffset().total_seconds() == 0


# --- What is refused, and how it is said --------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "fragment"),
    [
        ("2026-04-11 00:02:25", "must carry a UTC offset"),
        ("2026-04-11 02:02:25+02:00", "must be in UTC"),
        ("yesterday", "must be an ISO 8601 timestamp"),
        ("", "must not be empty"),
    ],
)
def test_a_timestamp_that_is_not_utc_is_refused_with_its_line_and_column(
    tmp_path: Path, stamp: str, fragment: str
) -> None:
    rows = _assignments()
    rows[2]["assigned_at_utc"] = stamp

    (problem,) = _problems(export(tmp_path, assignments=rows))

    assert problem.startswith("experiment_assignments.csv:4: column 'assigned_at_utc': ")
    assert fragment in problem


@pytest.mark.parametrize(
    ("column", "value", "fragment"),
    [
        ("sessions_7d", "3.5", "must be a whole number"),
        ("sessions_7d", "-1", "must be at least 0"),
        ("purchases_7d", "many", "must be a whole number"),
        ("revenue_usd_7d", "nan", "must be finite"),
        ("revenue_usd_7d", "inf", "must be finite"),
        ("revenue_usd_7d", "-0.01", "must be at least 0.0"),
        ("revenue_usd_7d", "", "must not be empty"),
    ],
)
def test_a_bad_number_in_the_outcomes_is_refused_with_its_line_and_column(
    tmp_path: Path, column: str, value: str, fragment: str
) -> None:
    rows = _outcomes()
    rows[0][column] = value
    if column == "purchases_7d":
        rows[0]["first_purchase_at_utc"] = ""

    problems = _problems(export(tmp_path, outcomes=rows))

    assert len(problems) == 1
    assert problems[0].startswith(f"experiment_outcomes.csv:2: column '{column}': ")
    assert fragment in problems[0]


def test_a_first_purchase_time_must_be_present_exactly_when_there_are_purchases(
    tmp_path: Path,
) -> None:
    rows = _outcomes()
    rows[0]["first_purchase_at_utc"] = "2026-04-11 01:00:00+00"  # p1 bought nothing
    rows[1]["first_purchase_at_utc"] = ""  # p2 bought once

    problems = _problems(export(tmp_path, outcomes=rows))

    assert [p.split(": column")[0] for p in problems] == [
        "experiment_outcomes.csv:2",
        "experiment_outcomes.csv:3",
    ]
    assert all("exactly when purchases_7d is above 0" in p for p in problems)


def test_a_negative_config_version_and_an_empty_arm_are_refused(tmp_path: Path) -> None:
    rows = _assignments()
    rows[0]["arm_config_version"] = "-1"
    rows[1]["arm"] = ""

    problems = _problems(export(tmp_path, assignments=rows))

    assert (
        "experiment_assignments.csv:2: column 'arm_config_version': must be at least 0"
        in (problems[0])
    )
    assert problems[1] == "experiment_assignments.csv:3: column 'arm': must not be empty"


def test_every_problem_is_listed_at_once_with_an_exact_total(tmp_path: Path) -> None:
    assignments, outcomes = _assignments(), _outcomes()
    assignments[0]["assigned_at_utc"] = "later"
    assignments[3]["arm"] = ""
    outcomes[2]["sessions_7d"] = "x"

    with pytest.raises(DataError) as caught:
        load_export(export(tmp_path, assignments=assignments, outcomes=outcomes), "e1")

    assert caught.value.total == 3 and len(caught.value.problems) == 3
    assert "3 problems" in str(caught.value)


def test_the_list_of_problems_is_cut_but_the_total_stays_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "_MAX_PROBLEMS_KEPT", 3)
    rows = [_row(OUTCOME_COLUMNS, "e1", f"q{i}", "x", 0, "0.0", "") for i in range(10)]

    with pytest.raises(DataError) as caught:
        load_export(export(tmp_path, outcomes=rows), "e1")

    assert caught.value.total == 10 and len(caught.value.problems) == 3


def test_a_row_with_fewer_or_more_fields_than_the_header_is_refused(tmp_path: Path) -> None:
    export(tmp_path)
    path = tmp_path / data.OUTCOMES_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = "e1,p1,3,0"  # too few
    lines[2] = lines[2] + ",extra"  # too many
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    problems = _problems(tmp_path)

    assert any(p.startswith("experiment_outcomes.csv:2: column 'revenue_usd_7d'") for p in problems)
    assert "experiment_outcomes.csv:3: the row has more fields than the header" in problems


def test_a_missing_file_a_missing_column_and_an_empty_file_are_each_named(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / data.EXPOSURES_FILE).unlink()
    _write(
        tmp_path,
        data.OUTCOMES_FILE,
        _outcomes(),
        columns=["experiment_id", "player_id", "sessions_7d"],
    )
    (tmp_path / data.ASSIGNMENTS_FILE).write_text("", encoding="utf-8")

    problems = _problems(tmp_path)

    assert any(p.startswith("experiment_exposures.csv: the file is missing") for p in problems)
    assert any(
        p.startswith("experiment_outcomes.csv: missing required columns") and "'purchases_7d'" in p
        for p in problems
    )
    assert "experiment_assignments.csv: the file is empty; it needs a header row" in problems


def test_a_repeated_column_name_is_refused(tmp_path: Path) -> None:
    export(tmp_path)
    path = tmp_path / data.EXPOSURES_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace("player_id", "player_id,player_id", 1),
        encoding="utf-8",
    )

    assert any("repeated column names ['player_id']" in p for p in _problems(tmp_path))


def test_a_file_that_is_not_utf8_is_refused_by_name(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / data.EXPOSURES_FILE).write_bytes(b"experiment_id,player_id\n\xff\xfe,p1\n")

    assert any(
        p.startswith("experiment_exposures.csv: not readable as UTF-8 CSV")
        for p in _problems(tmp_path)
    )


def test_something_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    assert _problems(tmp_path / "nowhere") == (f"{tmp_path / 'nowhere'}: is not a directory",)


# --- Rules across the three files ---------------------------------------------------------


def test_a_player_assigned_twice_is_refused_naming_both_lines(tmp_path: Path) -> None:
    rows = [
        *_assignments(),
        _row(ASSIGNMENT_COLUMNS, "e1", "p2", "control", "2026-04-20 00:00:00+00", 1),
    ]

    (problem,) = _problems(export(tmp_path, assignments=rows))

    assert problem == (
        "experiment_assignments.csv:6: player_id 'p2' is assigned twice (first on line 3)"
    )


def test_an_outcome_or_exposure_for_a_player_who_was_never_assigned_is_refused(
    tmp_path: Path,
) -> None:
    outcomes = [*_outcomes(), _row(OUTCOME_COLUMNS, "e1", "ghost", 1, 0, "0.0", "")]
    exposures = [*_exposures(), _row(EXPOSURE_COLUMNS, "e1", "ghost", "2026-04-11 00:05:00+00", 1)]

    problems = _problems(export(tmp_path, outcomes=outcomes, exposures=exposures))

    assert "experiment_outcomes.csv:6: player_id 'ghost' was never assigned" in problems
    assert "experiment_exposures.csv:6: player_id 'ghost' was never assigned" in problems


def test_an_assigned_player_without_an_outcome_is_refused_not_dropped(tmp_path: Path) -> None:
    (problem,) = _problems(export(tmp_path, outcomes=_outcomes()[:3]))

    assert problem == "experiment_assignments.csv:5: player_id 'p4' has no outcome row"


def test_two_outcome_rows_for_one_player_are_refused(tmp_path: Path) -> None:
    rows = [*_outcomes(), _row(OUTCOME_COLUMNS, "e1", "p1", 1, 0, "0.0", "")]

    (problem,) = _problems(export(tmp_path, outcomes=rows))

    assert problem == (
        "experiment_outcomes.csv:6: player_id 'p1' has two outcome rows (first on line 2)"
    )


def test_an_experiment_that_is_not_in_the_files_is_refused_listing_the_ones_that_are(
    tmp_path: Path,
) -> None:
    export(tmp_path)

    (problem,) = _problems(tmp_path, experiment_id="missing")

    assert problem == (
        "experiment_assignments.csv: no rows for experiment_id 'missing'; the files hold: 'e1'"
    )


def test_the_experiment_ids_in_the_files_are_listed_sorted_and_once(tmp_path: Path) -> None:
    rows = [
        *_assignments(),
        _row(ASSIGNMENT_COLUMNS, "a0", "p9", "control", "2026-04-11 00:00:00+00", 1),
    ]

    assert list_experiment_ids(export(tmp_path, assignments=rows)) == ("a0", "e1")


def test_an_experiment_id_that_only_one_file_holds_is_listed_too(tmp_path: Path) -> None:
    exposures = [*_exposures(), _row(EXPOSURE_COLUMNS, "x1", "p9", "2026-04-11 00:05:00+00", 1)]
    outcomes = [*_outcomes(), _row(OUTCOME_COLUMNS, "y2", "p9", 1, 0, "0.0", "")]

    assert list_experiment_ids(export(tmp_path, exposures=exposures, outcomes=outcomes)) == (
        "e1",
        "x1",
        "y2",
    )
