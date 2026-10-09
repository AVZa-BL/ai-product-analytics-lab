"""Build a tracking plan from the tracking you already have in a spreadsheet or CSV.

One row is one property of one event; a row with no property describes the event itself. Which
column means what is decided in `sheets/layout.py` (header spellings, or `--map`), and the words in
the cells are cleaned in `sheets/values.py`. This module turns the cleaned rows into a plan and
refuses, with the row number, whatever it cannot read without guessing.

The columns, by meaning (the importer's own names; see `docs/import-csv.md` for the spellings):

    event            required; the event name
    property         the property name; empty on a row that describes the event only
    type             string, integer, number, boolean, timestamp or enum (default string)
    required, pii    yes/no, true/false, 1/0, a tick (property rows)
    allowed_values   values separated by | ; , or line breaks (property rows, enum)
    description      of the property on a property row, of the event on an event row
    event_description  of the event, on any row
    trigger, owner, status   describe the event; the same on every row of an event if repeated

Problems in a row's own cells name the row (the number the spreadsheet shows). Problems found only
when the whole plan is validated, such as a bad --id, are reported by field path instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from tracewright.plan import PLAN_VERSION, VERSION_KEY, PropertyType, TrackingPlan
from tracewright.sheets import values
from tracewright.sheets.layout import CANONICAL, Layout, resolve_layout
from tracewright.sheets.table import Table, TableError, read_csv_text

MAX_BYTES = 5_000_000


class CsvImportError(TableError):
    """The table cannot be turned into a plan. The message names the row."""


@dataclass(frozen=True, kw_only=True)
class ImportResult:
    plan: TrackingPlan
    mapping: tuple[str, ...]  # one line per table: which column was read as what
    notes: tuple[str, ...]  # things the person should know, not errors
    preview: tuple[str, ...]  # one line per event: how its cells were read


def read_csv_file(path: str | Path, header_row: int = 1) -> Table:
    """A CSV file as a table. Refuses a file that is too large before reading it."""
    file = Path(path)
    try:
        size = file.stat().st_size
        if size > MAX_BYTES:  # refuse before reading, so a huge file costs no memory
            raise CsvImportError(f"{file}: is {size:,} bytes; the limit is {MAX_BYTES:,}")
        raw = file.read_bytes()
    except OSError as error:
        raise CsvImportError(f"{file}: cannot be read: {error.strerror or error}") from error
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvImportError(f"{file}: not valid UTF-8 (at byte offset {error.start})") from error
    return read_csv_text(text, str(file), header_row)


def import_plan_tables(
    tables: Sequence[Table],
    *,
    plan_id: str,
    title: str,
    identity_keys: list[str],
    owner: str | None = None,
    overrides: Mapping[str, str] | None = None,
    ignore_other_columns: bool = False,
    ignore_columns: Sequence[str] = (),
    fill_down: bool = False,
    type_map: Mapping[str, str] | None = None,
    status_map: Mapping[str, str] | None = None,
) -> ImportResult:
    """Read one or more tables into a validated plan. Raises TableError or PlanError."""
    events: dict[str, dict[str, Any]] = {}
    first_row: dict[str, dict[str, int]] = {}
    mapping: list[str] = []
    notes: list[str] = []
    layouts: list[dict[str, int]] = []
    for table in tables:
        layout = resolve_layout(
            table,
            overrides,
            ignore_other_columns=ignore_other_columns,
            ignore_columns=ignore_columns,
        )
        layouts.append(layout.columns)
        mapping.append(f"{table.label} (header on row {table.header_row}):")
        mapping.extend(f"  {line}" for line in layout.describe(table))
        reader = _Reader(
            table, layout, len(tables) > 1, fill_down, dict(type_map or {}), dict(status_map or {})
        )
        reader.read(events, first_row)
        notes.extend(reader.notes)

    if not events:
        labels = ", ".join(t.label for t in tables)
        raise CsvImportError(f"{labels}: no events found below the header row")
    data: dict[str, Any] = {
        VERSION_KEY: PLAN_VERSION,
        "id": plan_id,
        "title": title,
        "identity_keys": identity_keys,
        "events": list(events.values()),
    }
    if owner:
        data["owner"] = owner
    notes.extend(_notes(events, any("status" in lay for lay in layouts)))
    plan = TrackingPlan.from_dict(data)
    return ImportResult(
        plan=plan, mapping=tuple(mapping), notes=tuple(notes), preview=tuple(_preview(plan))
    )


def _names(names: list[str]) -> str:
    shown = ", ".join(repr(n) for n in names[:5])
    return shown + (f" and {len(names) - 5} more" if len(names) > 5 else "")


def _notes(events: dict[str, dict[str, Any]], has_status_column: bool) -> list[str]:
    """What the person should check, found without guessing: neither is an error."""
    notes = []
    if has_status_column:
        unset = [n for n, e in events.items() if "status" not in e]
        if unset:
            notes.append(
                f"status: no status cell for {len(unset)} event(s): {_names(unset)}. They are "
                "read as active, the plan default. (A status cell merged over several events "
                "reaches only the first; --fill-down fills the event name only.)"
            )
    event_info = ("description", "trigger", "owner", "status")
    bare = [
        n for n, e in events.items() if not e["properties"] and not any(k in e for k in event_info)
    ]
    if bare:
        notes.append(
            f"{len(bare)} event(s) have no properties and nothing else: {_names(bare)}. If one "
            "is a section title, a legend or a note rather than an event, remove its row"
        )
    return notes


def _preview(plan: TrackingPlan) -> list[str]:
    """How each event was read: name, status, and each property with its type."""
    lines = []
    for event in plan.events:
        shown = []
        for prop in event.properties[:30]:
            mark = ("*" if prop.required else "") + ("!" if prop.pii else "")
            kind = prop.type
            if prop.allowed_values:
                kind += "[" + "|".join(prop.allowed_values) + "]"
            shown.append(f"{prop.name}:{kind}{mark}")
        more = len(event.properties) - 30
        tail = f", ... and {more} more" if more > 0 else ""
        listed = ", ".join(shown) or "no properties"
        lines.append(f"  {event.name} ({event.status}): {listed}{tail}")
    return lines


def import_plan_csv(
    path: str | Path,
    *,
    plan_id: str,
    title: str,
    identity_keys: list[str],
    owner: str | None = None,
    **options: Any,
) -> TrackingPlan:
    """Read a CSV file into a validated plan. Raises TableError or PlanError."""
    result = import_plan_tables(
        [read_csv_file(path)],
        plan_id=plan_id,
        title=title,
        identity_keys=identity_keys,
        owner=owner,
        **options,
    )
    return result.plan


class _Reader:
    """Reads the rows of one table into the shared dict of events."""

    def __init__(
        self,
        table: Table,
        layout: Layout,
        several: bool,
        fill_down: bool,
        type_map: dict[str, str],
        status_map: dict[str, str],
    ) -> None:
        self.table = table
        self.layout = layout
        self.several = several
        self.fill_down = fill_down
        self.type_map = type_map
        self.status_map = status_map
        self.notes: list[str] = []

    def where(self, number: int) -> str:
        return f"{self.table.label}, row {number}" if self.several else f"row {number}"

    def cell(self, cells: tuple[str, ...], name: str) -> str:
        index = self.layout.columns.get(name)
        return cells[index] if index is not None and index < len(cells) else ""

    def read(self, events: dict[str, dict[str, Any]], first_row: dict[str, dict[str, int]]) -> None:
        width = len(self.table.header)
        previous = ""
        for number, cells in self.table.rows:
            if len(cells) > width:
                raise CsvImportError(
                    f"{self.where(number)}: has {len(cells)} cells but the header has {width}; "
                    "put a value that contains a comma in double quotes"
                )
            if not any(cells):
                continue
            name = self.cell(cells, "event")
            if not name and self.fill_down and previous:
                name = previous
            if not name:
                raise CsvImportError(
                    f"{self.where(number)}: the event column is empty (if the event name is "
                    "written once for several rows, add --fill-down)"
                )
            previous = name
            self.read_row(number, name, cells, events, first_row)

    def read_row(
        self,
        number: int,
        name: str,
        cells: tuple[str, ...],
        events: dict[str, dict[str, Any]],
        first_row: dict[str, dict[str, int]],
    ) -> None:
        where = self.where(number)
        event = events.setdefault(name, {"name": name, "properties": []})
        for column in ("trigger", "owner"):
            self.event_field(event, column, self.cell(cells, column), name, where)
        raw_status = self.cell(cells, "status")
        if raw_status:
            try:
                state = values.status(raw_status, self.status_map)
            except ValueError as error:
                words = sorted(values.STATUS_WORDS)
                raise CsvImportError(
                    f"{where}: {error}; known words: {words}. Add one with "
                    "--status-map 'Word=active|planned|deprecated'"
                ) from error
            self.event_field(event, "status", state, name, where)
        self.event_field(
            event, "description", self.cell(cells, "event_description"), name, where
        )

        prop = self.cell(cells, "property")
        description = self.cell(cells, "description")
        if not prop:
            property_cells = ("type", "required", "pii", "allowed_values")
            stray = [c for c in property_cells if self.cell(cells, c)]
            if stray:
                raise CsvImportError(
                    f"{where}: the property cell is empty, so this row describes the event, "
                    f"but {stray} is filled in; name the property, or clear those cells"
                )
            self.event_field(event, "description", description, name, where)
            return

        problem = values.property_name_problem(prop)
        if problem:
            raise CsvImportError(f"{where}: {problem}")
        kind = self.property_type(where, self.cell(cells, "type"))
        seen = first_row.setdefault(name, {})
        if prop in seen:
            raise CsvImportError(
                f"{where}: property {prop!r} of event {name!r} is already declared on "
                f"row {seen[prop]}"
            )
        seen[prop] = number
        entry: dict[str, Any] = {"name": prop, "type": kind}
        for column in ("required", "pii"):
            try:
                flag = values.flag(self.cell(cells, column))
            except ValueError as error:
                raise CsvImportError(
                    f"{where}: {column} is {self.cell(cells, column)!r}, which is not a yes or a "
                    "no that is recognised (the words are listed in docs/column-names.md; "
                    "change the cell, a checkbox gives TRUE or FALSE)"
                ) from error
            if flag is not None:
                entry[column] = flag
        if description and self.layout.columns.get("event_description") is not None:
            entry["description"] = description
        elif description:
            entry["description"] = description
        try:
            allowed = values.split_values(self.cell(cells, "allowed_values"))
        except ValueError as error:
            raise CsvImportError(
                f"{where}: allowed values of property {prop!r}: {error}"
            ) from error
        if allowed and kind != "enum":
            raise CsvImportError(
                f"{where}: property {prop!r} has allowed values but its type is {kind!r}; "
                "write the type as enum in the sheet, or clear the allowed-values cell"
            )
        if allowed:
            entry["allowed_values"] = allowed
        events[name]["properties"].append(entry)

    def property_type(self, where: str, text: str) -> str:
        if not text:
            return "string"
        try:
            return values.property_type(text, self.type_map)
        except ValueError as error:
            accepted = list(get_args(PropertyType))
            raise CsvImportError(
                f"{where}: {error}; a plan's types are {accepted}. Add a word with "
                "--type-map 'Word=string'"
            ) from error

    @staticmethod
    def event_field(
        event: dict[str, Any], column: str, value: str, name: str, where: str
    ) -> None:
        if not value:
            return
        if column in event and event[column] != value:
            raise CsvImportError(
                f"{where}: {column} of event {name!r} is {value!r}, but an earlier row says "
                f"{event[column]!r}"
            )
        event[column] = value


__all__ = [
    "CANONICAL",
    "CsvImportError",
    "ImportResult",
    "import_plan_csv",
    "import_plan_tables",
    "read_csv_file",
]
