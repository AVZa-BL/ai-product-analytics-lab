"""Reading an experiment's export: every row, the right types, and a located message for every
way the files can be wrong."""

import csv
import errno
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from referee import data
from referee.data import (
    DataError,
    Outcome,
    export_file_hashes,
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


# --- What is refused, and how it is said --------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "fragment"),
    [
        ("sessions_7d", "-1", "must be at least 0"),
        ("purchases_7d", "many", "must be a whole number"),
        ("revenue_usd_7d", "inf", "must be finite"),
        ("revenue_usd_7d", "-0.01", "must be at least 0.0"),
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
        p.startswith("experiment_exposures.csv: not readable as UTF-8 (")
        for p in _problems(tmp_path)
    )


def test_something_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    assert _problems(tmp_path / "nowhere") == (f"{tmp_path / 'nowhere'}: is not a directory",)


@pytest.mark.parametrize(
    "refusal",
    [PermissionError(errno.EACCES, "Permission denied"), OSError(errno.ENAMETOOLONG, "Too long")],
)
def test_a_folder_that_cannot_be_examined_is_a_problem_and_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: OSError
) -> None:
    def refuse(self: Path) -> bool:
        raise refusal

    monkeypatch.setattr(Path, "is_dir", refuse)

    with pytest.raises(DataError) as caught:
        load_export(tmp_path / "export", "e1")

    assert caught.value.problems == (
        f"{tmp_path / 'export'}: cannot be examined ({refusal.strerror})",
    )
    assert caught.value.total == 1


# --- Rules across the three files ---------------------------------------------------------


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


# --- A file cut short, and what a short row means -------------------------------------------


def test_a_csv_syntax_error_names_its_line_and_says_reading_of_the_file_stops(
    tmp_path: Path,
) -> None:
    export(tmp_path)
    path = tmp_path / data.OUTCOMES_FILE
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[2] = 'e1,p2,"5"x,1,4.99,2026-04-12 10:00:00+00\n'  # text after a closing quote
    path.write_text("".join(lines), encoding="utf-8")

    (problem,) = _problems(tmp_path)

    assert problem.startswith("experiment_outcomes.csv:3: not readable as CSV")
    assert "reading of this file stops here" in problem


def test_a_short_terminated_last_row_that_ends_before_its_id_is_an_id_problem_not_a_cut(
    tmp_path: Path,
) -> None:
    columns = ["exposure_id", "experiment_id", "player_id", "exposed_at_utc"]
    exposures = [{"exposure_id": f"x{i}", **row} for i, row in enumerate(_exposures())]
    export(tmp_path, exposures=exposures, exposure_columns=columns)
    path = tmp_path / data.EXPOSURES_FILE
    path.write_text(path.read_text(encoding="utf-8") + "x9\n", encoding="utf-8")

    (problem,) = _problems(tmp_path)

    assert "column 'experiment_id': the row has no value" in problem


def test_a_file_with_old_style_carriage_return_line_ends_is_read_and_its_cut_is_still_seen(
    tmp_path: Path,
) -> None:
    export(tmp_path)
    path = tmp_path / data.EXPOSURES_FILE
    text = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r")
    path.write_bytes(text + b"other,p9\r")  # a terminated short row of another experiment
    assert len(load_export(tmp_path, "e1").exposures) == 4

    path.write_bytes(text + b"e1,p4")  # an unterminated one
    assert "the file ends in the middle of a row" in _problems(tmp_path)[0]


# --- What the reviewers found unpinned in the loader ---------------------------------------


def test_a_file_that_cannot_be_opened_is_named(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / data.EXPOSURES_FILE).unlink()
    (tmp_path / data.EXPOSURES_FILE).mkdir()  # a directory where the file should be

    assert any(
        p.startswith("experiment_exposures.csv: cannot be opened") for p in _problems(tmp_path)
    )


def test_a_negative_config_version_on_an_exposure_is_refused(tmp_path: Path) -> None:
    rows = _exposures()
    rows[0]["arm_config_version"] = "-1"

    (problem,) = _problems(export(tmp_path, exposures=rows))

    assert problem.startswith(
        "experiment_exposures.csv:2: column 'arm_config_version': must be at least 0"
    )


def test_the_problems_of_the_second_stage_come_in_a_fixed_order_with_exact_text(
    tmp_path: Path,
) -> None:
    assignments = [
        *_assignments(),
        _row(ASSIGNMENT_COLUMNS, "e1", "p2", "control", "2026-04-20 00:00:00+00", 1),
    ]
    outcomes = [*_outcomes()[:3], _row(OUTCOME_COLUMNS, "e1", "ghost", 1, 0, "0.0", "")]
    exposures = [*_exposures(), _row(EXPOSURE_COLUMNS, "e1", "ghost", "2026-04-11 00:05:00+00", 1)]

    with pytest.raises(DataError) as caught:
        load_export(
            export(tmp_path, assignments=assignments, outcomes=outcomes, exposures=exposures), "e1"
        )

    assert caught.value.problems == (
        "experiment_assignments.csv:6: player_id 'p2' is assigned twice (first on line 3)",
        "experiment_outcomes.csv:5: player_id 'ghost' was never assigned",
        "experiment_assignments.csv:5: player_id 'p4' has no outcome row",
        "experiment_exposures.csv:6: player_id 'ghost' was never assigned",
    )
    assert caught.value.total == 4


def test_the_error_message_is_singular_for_one_problem_and_starts_with_the_first() -> None:
    one = DataError(["a: first"], 1)
    many = DataError(["a: first", "b: second"], 2)

    assert str(one) == "the experiment export has 1 problem; first: a: first"
    assert str(many) == "the experiment export has 2 problems; first: a: first"


def test_the_listing_keeps_ten_thousand_problems_by_default() -> None:
    assert data._MAX_PROBLEMS_KEPT == 10_000


def test_a_directory_that_is_missing_and_an_experiment_that_is_absent_each_count_as_one_problem(
    tmp_path: Path,
) -> None:
    with pytest.raises(DataError) as nowhere:
        load_export(tmp_path / "nowhere", "e1")
    export(tmp_path)
    with pytest.raises(DataError) as absent:
        load_export(tmp_path, "missing")

    assert nowhere.value.total == 1 and absent.value.total == 1


def test_listing_the_experiments_of_an_export_with_a_missing_file_is_refused(
    tmp_path: Path,
) -> None:
    export(tmp_path)
    (tmp_path / data.OUTCOMES_FILE).unlink()

    with pytest.raises(DataError, match="missing"):
        list_experiment_ids(tmp_path)


# --- When each outcome window closes, and when the export was taken (design section 21.8) ---

WINDOW_COLUMNS = [*OUTCOME_COLUMNS, "window_end_utc"]
WINDOW_ENDS = [
    "2026-04-18 00:02:25+00",
    "2026-04-18 00:08:33+00",
    "2026-04-19 09:00:00+00",
    "2026-05-03 12:30:00+00",
]


def _outcomes_with_window_ends() -> list[dict[str, str]]:
    return [
        dict(row, window_end_utc=end) for row, end in zip(_outcomes(), WINDOW_ENDS, strict=True)
    ]


def _manifest(folder: Path, text: str) -> None:
    (folder / data.MANIFEST_FILE).write_text(text, encoding="utf-8")


def test_the_end_of_each_window_is_read_when_the_column_is_there(tmp_path: Path) -> None:
    loaded = load_export(
        export(tmp_path, outcomes=_outcomes_with_window_ends(), outcome_columns=WINDOW_COLUMNS),
        "e1",
    )

    assert [o.window_end for o in loaded.outcomes] == [
        _utc(2026, 4, 18, 0, 2, 25),
        _utc(2026, 4, 18, 0, 8, 33),
        _utc(2026, 4, 19, 9),
        _utc(2026, 5, 3, 12, 30),
    ]
    assert loaded.outcomes[1] == Outcome(
        "p2", 5, 1, 4.99, _utc(2026, 4, 12, 10), _utc(2026, 4, 18, 0, 8, 33)
    )


@pytest.mark.parametrize(
    ("stamp", "fragment"),
    [
        ("2026-04-18 02:02:25+02:00", "must be in UTC"),
        ("", "must not be empty"),
    ],
)
def test_once_the_column_is_there_every_row_of_the_experiment_must_have_a_good_value(
    tmp_path: Path, stamp: str, fragment: str
) -> None:
    rows = _outcomes_with_window_ends()
    rows[2]["window_end_utc"] = stamp

    (problem,) = _problems(export(tmp_path, outcomes=rows, outcome_columns=WINDOW_COLUMNS))

    assert problem.startswith("experiment_outcomes.csv:4: column 'window_end_utc': ")
    assert fragment in problem


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ('["2026-05-09T06:00:00Z"]', "must be a JSON object"),
        ('{"exported_at_utc": 20260509}', "must be an ISO 8601 timestamp, got 20260509"),
        ('{"exported_at_utc": "2026-05-09T06:00:00"}', "must carry a UTC offset"),
        ('{"exported_at_utc": ""}', "must be an ISO 8601 timestamp"),
    ],
)
def test_a_manifest_that_is_there_but_cannot_be_read_is_a_problem_not_a_guess(
    tmp_path: Path, text: str, fragment: str
) -> None:
    export(tmp_path)
    _manifest(tmp_path, text)

    (problem,) = _problems(tmp_path)

    assert problem.startswith("manifest.json: ") and fragment in problem


def test_a_manifest_that_is_a_directory_cannot_be_read(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / data.MANIFEST_FILE).mkdir()

    (problem,) = _problems(tmp_path)

    assert problem.startswith("manifest.json: cannot be read")


def test_a_manifest_with_a_byte_order_mark_is_read_like_the_csv_files(tmp_path: Path) -> None:
    export(tmp_path)
    (tmp_path / data.MANIFEST_FILE).write_bytes(
        b"\xef\xbb\xbf" + b'{"exported_at_utc": "2026-05-09T06:00:00Z"}'
    )

    assert load_export(tmp_path, "e1").exported_at == _utc(2026, 5, 9, 6)


# --- The manifest, after the independent review of 4b-1 -----------------------------------------


@pytest.mark.parametrize("depth", [100_000])
def test_a_manifest_nested_too_deeply_for_json_is_a_problem_not_a_crash(
    tmp_path: Path, depth: int
) -> None:
    export(tmp_path)
    _manifest(tmp_path, "[" * depth + "]" * depth)

    (problem,) = _problems(tmp_path)

    assert problem == "manifest.json: nested too deeply to read"


def test_a_manifest_that_gives_a_key_twice_is_refused_not_resolved_to_the_last(
    tmp_path: Path,
) -> None:
    export(tmp_path)
    _manifest(
        tmp_path,
        '{"exported_at_utc": "2026-01-01T00:00:00Z", "exported_at_utc": "2026-02-01T00:00:00Z"}',
    )

    (problem,) = _problems(tmp_path)

    assert problem.startswith("manifest.json: not valid JSON")
    assert "'exported_at_utc' is given more than once" in problem


def test_a_manifest_that_is_a_link_to_nothing_is_a_problem_not_an_absent_file(
    tmp_path: Path,
) -> None:
    export(tmp_path)
    (tmp_path / data.MANIFEST_FILE).symlink_to(tmp_path / "nowhere.json")

    (problem,) = _problems(tmp_path)

    assert problem == "manifest.json: is a link to a file that does not exist"


# --- The hashes of the files ---------------------------------------------------------------


def test_a_file_larger_than_one_read_is_hashed_whole(tmp_path: Path) -> None:
    names = (data.ASSIGNMENTS_FILE, data.EXPOSURES_FILE, data.OUTCOMES_FILE)
    contents = {name: bytes(range(256)) * 12_000 + name.encode() for name in names}
    for name, content in contents.items():
        (tmp_path / name).write_bytes(content)

    assert export_file_hashes(tmp_path) == {
        name: hashlib.sha256(content).hexdigest() for name, content in contents.items()
    }


# --- The first-seen column of the assignments ------------------------------------------

FIRST_SEEN_COLUMNS = [*ASSIGNMENT_COLUMNS, "first_seen_at_utc"]
FIRST_SEEN = [
    "2025-11-23 14:27:50+00",
    "2026-04-11 00:08:33+00",  # at the instant of the assignment: not after it
    "2025-12-01 23:23:02+00",
    "2026-01-15 08:00:00+00",
]


def _assignments_with_first_seen() -> list[dict[str, str]]:
    return [
        dict(row, first_seen_at_utc=seen)
        for row, seen in zip(_assignments(), FIRST_SEEN, strict=True)
    ]


def test_when_a_player_was_first_seen_is_read_when_the_column_is_there(tmp_path: Path) -> None:
    with_column = export(
        tmp_path, assignments=_assignments_with_first_seen(), assignment_columns=FIRST_SEEN_COLUMNS
    )

    loaded = load_export(with_column, "e1")

    assert [a.first_seen_at for a in loaded.assignments] == [
        _utc(2025, 11, 23, 14, 27, 50),
        _utc(2026, 4, 11, 0, 8, 33),
        _utc(2025, 12, 1, 23, 23, 2),
        _utc(2026, 1, 15, 8),
    ]
    assert load_export(export(tmp_path), "e1").assignments[0].first_seen_at is None


@pytest.mark.parametrize(
    ("stamp", "fragment"),
    [
        ("2026-04-12 11:00:00+02:00", "must be in UTC"),
        ("", "must not be empty"),
        (
            "2026-04-12 09:00:01+00",
            "must not be after assigned_at_utc ('2026-04-12 09:00:00+00'), "
            "got '2026-04-12 09:00:01+00'",
        ),
    ],
)
def test_once_the_first_seen_column_is_there_every_row_must_hold_a_good_value(
    tmp_path: Path, stamp: str, fragment: str
) -> None:
    rows = _assignments_with_first_seen()
    rows[2]["first_seen_at_utc"] = stamp

    (problem,) = _problems(
        export(tmp_path, assignments=rows, assignment_columns=FIRST_SEEN_COLUMNS)
    )

    assert problem.startswith("experiment_assignments.csv:4: column 'first_seen_at_utc': ")
    assert fragment in problem
