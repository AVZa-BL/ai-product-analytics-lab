"""Read an experiment's exported data: three CSV files, read in full.

The files are the lab's raw tables `experiment_assignments`, `experiment_exposures` and
`experiment_outcomes`, written as CSV (see section 20.2 of the design). Every row of the chosen
experiment is read. Nothing here samples, truncates or caps: a statistic computed from some of
the rows is not the statistic of the experiment, and the first rows are the earliest
assignments, which is where a novelty effect sits.

A file that does not match the contract is refused with a `DataError` listing the problems
found, each with its file and, where it has one, its line and column. They come in two stages:
every bad cell, short row and missing file or column is listed first (a CSV syntax error ends
the reading of its file at that point), and only when there are none are the rules across the
files checked, so fixing one stage can show the next. `total` counts the problems of the stage
that failed. Rows come back in a canonical order (by player, not by file position), so a
seeded bootstrap gives the same answer however the export was sorted.

A file cut short in the middle of its last line is refused, because the last row is then
missing or incomplete. A cut that lands exactly between two rows, or inside the last cell of
the last row, cannot be told from a complete file.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ASSIGNMENTS_FILE = "experiment_assignments.csv"
EXPOSURES_FILE = "experiment_exposures.csv"
OUTCOMES_FILE = "experiment_outcomes.csv"

# Columns Referee reads. Others may be present and are ignored; `arm_config_version` in the
# exposures file is read when it is there.
_REQUIRED: dict[str, tuple[str, ...]] = {
    ASSIGNMENTS_FILE: (
        "experiment_id",
        "player_id",
        "arm",
        "assigned_at_utc",
        "arm_config_version",
    ),
    EXPOSURES_FILE: ("experiment_id", "player_id", "exposed_at_utc"),
    OUTCOMES_FILE: (
        "experiment_id",
        "player_id",
        "sessions_7d",
        "purchases_7d",
        "revenue_usd_7d",
        "first_purchase_at_utc",
    ),
}

# Problems are listed, not counted away: a listing stops here, and the total is still exact.
_MAX_PROBLEMS_KEPT = 10_000


class DataError(ValueError):
    """The export cannot be read as an experiment. `problems` lists what is wrong."""

    def __init__(self, problems: list[str], total: int) -> None:
        self.problems = tuple(problems)
        self.total = total
        noun = "problem" if total == 1 else "problems"
        super().__init__(f"the experiment export has {total} {noun}; first: {problems[0]}")


@dataclass(frozen=True, slots=True)
class Assignment:
    player_id: str
    arm: str
    assigned_at: datetime
    config_version: int


@dataclass(frozen=True, slots=True)
class Exposure:
    player_id: str
    exposed_at: datetime
    config_version: int | None  # None when the exposures file has no such column


@dataclass(frozen=True, slots=True)
class Outcome:
    player_id: str
    sessions_7d: int
    purchases_7d: int
    revenue_usd_7d: float
    first_purchase_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class ExperimentData:
    """One experiment, in canonical order: by player, and each player's exposures by time."""

    experiment_id: str
    assignments: tuple[Assignment, ...]
    exposures: tuple[Exposure, ...]
    outcomes: tuple[Outcome, ...]


class _Problems:
    def __init__(self) -> None:
        self.kept: list[str] = []
        self.total = 0

    def add(self, text: str) -> None:
        self.total += 1
        if len(self.kept) < _MAX_PROBLEMS_KEPT:
            self.kept.append(text)

    def raise_if_any(self) -> None:
        if self.total:
            raise DataError(self.kept, self.total)


def _lines(handle: Iterator[str], seen: list) -> Iterator[str]:
    """The lines of a file; `seen` becomes [lines read so far, the last one].

    The last line tells a cut-off ending, and the count locates a syntax error, which
    `csv.DictReader.line_num` does not (it is updated only after a row is read).
    """
    for text in handle:
        seen[0] += 1
        seen[1] = text
        yield text


def _rows(
    directory: Path, name: str, problems: _Problems
) -> Iterator[tuple[int, dict[str, str | None]]]:
    """Yield (line, row) for each data row of a file, or record why it cannot be read.

    `line` is the line on which the record ends, which is its only line unless a quoted field
    contains a newline. A short final row of a file that does not end in a newline is marked
    with the key "\0cut": the file was most likely cut off in the middle of it.
    """
    path = directory / name
    try:
        handle = path.open(encoding="utf-8-sig", newline="")
    except FileNotFoundError:
        problems.add(f"{name}: the file is missing from {directory}")
        return
    except OSError as error:
        problems.add(f"{name}: cannot be opened ({error.strerror or error})")
        return
    seen: list = [0, ""]
    with handle:
        try:
            reader = csv.DictReader(
                _lines(handle, seen), restkey="\0extra", restval=None, strict=True
            )
            header = reader.fieldnames
            if not header:
                problems.add(f"{name}: the file is empty; it needs a header row")
                return
            repeated = sorted({column for column in header if header.count(column) > 1})
            if repeated:
                problems.add(f"{name}: repeated column names {repeated}")
                return
            missing = [column for column in _REQUIRED[name] if column not in header]
            if missing:
                problems.add(f"{name}: missing required columns {missing}")
                return
            held: tuple[int, dict[str, str | None]] | None = None
            for row in reader:
                if held is not None:
                    yield held
                held = (reader.line_num, row)
            if held is not None:
                line, row = held
                if None in row.values() and not seen[1].endswith(("\n", "\r")):
                    row["\0cut"] = ""
                yield line, row
        except UnicodeDecodeError as error:
            problems.add(f"{name}: not readable as UTF-8 ({error})")
        except csv.Error as error:
            where = f"{name}:{seen[0]}" if seen[0] else name
            problems.add(f"{where}: not readable as CSV ({error}); reading of this file stops here")


def list_experiment_ids(directory: str | Path) -> tuple[str, ...]:
    """The experiment IDs the three files contain, sorted.

    Every row is read, but only the `experiment_id` values are kept; a row that is cut off
    before the end of its ID does not count.
    """
    ids: set[str] = set()
    problems = _Problems()
    for name in _REQUIRED:
        for _, row in _rows(Path(directory), name, problems):
            value = row.get("experiment_id")
            if value and "\0cut" not in row:
                ids.add(value)
    problems.raise_if_any()
    return tuple(sorted(ids))


class _Reader:
    """Parses the cells of one row, recording a problem (and returning None) for a bad one."""

    def __init__(self, name: str, line: int, row: dict[str, str | None], problems: _Problems):
        self.name, self.line, self.row, self.problems = name, line, row, problems

    def fail(self, column: str, message: str) -> None:
        self.problems.add(f"{self.name}:{self.line}: column '{column}': {message}")

    def _cell(self, column: str) -> str | None:
        value = self.row.get(column)
        if value is None:
            self.fail(column, "the row has no value (fewer fields than the header)")
        return value

    def text(self, column: str) -> str | None:
        value = self._cell(column)
        if value is not None and not value:
            self.fail(column, "must not be empty")
            return None
        return value

    def integer(self, column: str, *, minimum: int | None = None) -> int | None:
        value = self.text(column)
        if value is None:
            return None
        try:
            number = int(value)
        except ValueError:
            self.fail(column, f"must be a whole number, got {value!r}")
            return None
        if minimum is not None and number < minimum:
            self.fail(column, f"must be at least {minimum}, got {number}")
            return None
        return number

    def real(self, column: str, *, minimum: float | None = None) -> float | None:
        value = self.text(column)
        if value is None:
            return None
        try:
            number = float(value)
        except ValueError:
            self.fail(column, f"must be a number, got {value!r}")
            return None
        if not math.isfinite(number):
            self.fail(column, f"must be finite, got {value!r}")
            return None
        if minimum is not None and number < minimum:
            self.fail(column, f"must be at least {minimum}, got {number}")
            return None
        return number

    def timestamp(self, column: str, *, optional: bool = False) -> datetime | None:
        value = self._cell(column)
        if value is None:
            return None
        if not value:
            if not optional:
                self.fail(column, "must not be empty")
            return None
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            self.fail(column, f"must be an ISO 8601 timestamp, got {value!r}")
            return None
        if moment.utcoffset() is None:
            self.fail(column, f"must carry a UTC offset (Z, +00 or +00:00), got {value!r}")
            return None
        if moment.utcoffset() != timedelta(0):
            self.fail(column, f"must be in UTC (offset 0), got {value!r}")
            return None
        return moment.astimezone(UTC)


def _read[T](
    directory: Path,
    name: str,
    experiment_id: str,
    problems: _Problems,
    build: Callable[[_Reader], T | None],
) -> list[tuple[int, T]]:
    """Every row of `experiment_id` in a file, built by `build`, with its line number.

    Rows of other experiments are skipped without being checked, but a row that ends before
    its `experiment_id` cell, or the cut-off last row of a file, belongs to no experiment and
    is a problem.
    """
    built: list[tuple[int, T]] = []
    for line, row in _rows(directory, name, problems):
        if "\0cut" in row:
            problems.add(
                f"{name}:{line}: the file ends in the middle of a row "
                "(fewer fields than the header)"
            )
            continue
        if row.get("experiment_id") is None:
            problems.add(
                f"{name}:{line}: column 'experiment_id': the row has no value "
                "(fewer fields than the header)"
            )
            continue
        if row.get("experiment_id") != experiment_id:
            continue
        if "\0extra" in row:
            problems.add(f"{name}:{line}: the row has more fields than the header")
            continue
        item = build(_Reader(name, line, row, problems))
        if item is not None:
            built.append((line, item))
    return built


def load_export(directory: str | Path, experiment_id: str) -> ExperimentData:
    """Read every row of `experiment_id` from the three files in `directory`.

    Raises `DataError` listing the problems found, in two stages (see the module docstring):
    first a missing file or column, a value that is not what its column promises, a short or
    cut-off row or a CSV syntax error; then, once there are none, a player assigned twice, an
    exposure or outcome for a player who was never assigned, or an assigned player with no
    outcome.
    """
    folder = Path(directory)
    if not folder.is_dir():
        raise DataError([f"{folder}: is not a directory"], 1)
    problems = _Problems()

    def assignment(cells: _Reader) -> Assignment | None:
        player = cells.text("player_id")
        arm = cells.text("arm")
        moment = cells.timestamp("assigned_at_utc")
        version = cells.integer("arm_config_version", minimum=0)
        if player is None or arm is None or moment is None or version is None:
            return None
        return Assignment(player, arm, moment, version)

    def exposure(cells: _Reader) -> Exposure | None:
        player = cells.text("player_id")
        moment = cells.timestamp("exposed_at_utc")
        has_version = "arm_config_version" in cells.row
        version = cells.integer("arm_config_version", minimum=0) if has_version else None
        if player is None or moment is None or (has_version and version is None):
            return None
        return Exposure(player, moment, version)

    def outcome(cells: _Reader) -> Outcome | None:
        player = cells.text("player_id")
        sessions = cells.integer("sessions_7d", minimum=0)
        purchases = cells.integer("purchases_7d", minimum=0)
        revenue = cells.real("revenue_usd_7d", minimum=0.0)
        first = cells.timestamp("first_purchase_at_utc", optional=True)
        if player is None or sessions is None or purchases is None or revenue is None:
            return None
        if (purchases > 0) != (first is not None):
            cells.fail(
                "first_purchase_at_utc",
                f"must be present exactly when purchases_7d is above 0 (it is {purchases})",
            )
            return None
        return Outcome(player, sessions, purchases, revenue, first)

    assigned = _read(folder, ASSIGNMENTS_FILE, experiment_id, problems, assignment)
    exposed = _read(folder, EXPOSURES_FILE, experiment_id, problems, exposure)
    measured = _read(folder, OUTCOMES_FILE, experiment_id, problems, outcome)
    problems.raise_if_any()

    if not assigned:
        found = ", ".join(repr(i) for i in list_experiment_ids(folder)) or "none"
        raise DataError(
            [
                f"{ASSIGNMENTS_FILE}: no rows for experiment_id {experiment_id!r}; "
                f"the files hold: {found}"
            ],
            1,
        )

    assigned_line: dict[str, int] = {}
    for line, row in assigned:
        if row.player_id in assigned_line:
            problems.add(
                f"{ASSIGNMENTS_FILE}:{line}: player_id {row.player_id!r} is assigned twice "
                f"(first on line {assigned_line[row.player_id]})"
            )
        else:
            assigned_line[row.player_id] = line

    outcome_line: dict[str, int] = {}
    for line, result in measured:
        if result.player_id not in assigned_line:
            problems.add(
                f"{OUTCOMES_FILE}:{line}: player_id {result.player_id!r} was never assigned"
            )
        elif result.player_id in outcome_line:
            problems.add(
                f"{OUTCOMES_FILE}:{line}: player_id {result.player_id!r} has two outcome rows "
                f"(first on line {outcome_line[result.player_id]})"
            )
        else:
            outcome_line[result.player_id] = line
    for player, line in assigned_line.items():
        if player not in outcome_line:
            problems.add(f"{ASSIGNMENTS_FILE}:{line}: player_id {player!r} has no outcome row")
    for line, seen in exposed:
        if seen.player_id not in assigned_line:
            problems.add(
                f"{EXPOSURES_FILE}:{line}: player_id {seen.player_id!r} was never assigned"
            )
    problems.raise_if_any()

    def exposure_order(seen: Exposure) -> tuple[str, datetime, int]:
        version = -1 if seen.config_version is None else seen.config_version
        return seen.player_id, seen.exposed_at, version

    return ExperimentData(
        experiment_id=experiment_id,
        assignments=tuple(sorted((row for _, row in assigned), key=lambda r: r.player_id)),
        exposures=tuple(sorted((seen for _, seen in exposed), key=exposure_order)),
        outcomes=tuple(sorted((result for _, result in measured), key=lambda r: r.player_id)),
    )
