"""Build a tracking plan from a CSV export of the tracking you already have.

Most teams keep their tracking in a spreadsheet. One row is one property of one event; a row with
an empty `property` describes the event itself. Columns (a header row is required):

    event        required; the event name
    property     the property name; empty on a row that describes the event only
    type         string, integer, number, boolean, timestamp or enum (default string)
    required     true/false/yes/no/1/0 (property rows)
    pii          true/false/yes/no/1/0 (property rows)
    allowed_values  values separated by | (property rows, enum)
    description  of the property on a property row, of the event on an event row
    trigger, owner, status   describe the event; the same on every row of an event if repeated

Unknown columns, conflicting event fields and unreadable values are refused with a row number.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from tracewright.plan import PLAN_VERSION, VERSION_KEY, TrackingPlan

MAX_BYTES = 5_000_000
COLUMNS = (
    "event",
    "property",
    "type",
    "required",
    "pii",
    "allowed_values",
    "description",
    "trigger",
    "owner",
    "status",
)
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


class CsvImportError(ValueError):
    """The CSV cannot be turned into a plan. The message names the row."""


def _flag(value: str, row: int, column: str) -> bool | None:
    text = value.strip().lower()
    if not text:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise CsvImportError(f"row {row}: {column} must be true or false, got {value!r}")


def import_plan_csv(
    path: str | Path,
    *,
    plan_id: str,
    title: str,
    identity_keys: list[str],
    owner: str | None = None,
) -> TrackingPlan:
    """Read a CSV file into a validated plan. Raises CsvImportError or PlanError."""
    file = Path(path)
    try:
        raw = file.read_bytes()
    except OSError as error:
        raise CsvImportError(f"{file}: cannot be read: {error.strerror or error}") from error
    if len(raw) > MAX_BYTES:
        raise CsvImportError(f"{file}: is {len(raw):,} bytes; the limit is {MAX_BYTES:,}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvImportError(f"{file}: not valid UTF-8 (at byte offset {error.start})") from error

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
        if "event" not in header:
            raise CsvImportError(f"{file}: the header row must have an 'event' column")
        unknown = [name for name in header if name not in COLUMNS]
        if unknown:
            raise CsvImportError(f"{file}: unknown column(s) {unknown}; known: {list(COLUMNS)}")
        rows = [
            (number, {(k or "").strip().lower(): (v or "") for k, v in record.items()})
            for number, record in enumerate(reader, start=2)
        ]
    except csv.Error as error:
        raise CsvImportError(f"{file}: not readable as CSV: {error}") from error

    events: dict[str, dict[str, Any]] = {}
    for number, row in rows:
        name = row.get("event", "").strip()
        if not name:
            if any(value.strip() for value in row.values()):
                raise CsvImportError(f"row {number}: the event column is empty")
            continue
        event = events.setdefault(name, {"name": name, "properties": []})
        for column in ("trigger", "owner", "status"):
            value = row.get(column, "").strip()
            if value:
                if column in event and event[column] != value:
                    raise CsvImportError(
                        f"row {number}: {column} of event {name!r} is {value!r}, but an earlier "
                        f"row says {event[column]!r}"
                    )
                event[column] = value
        prop = row.get("property", "").strip()
        description = row.get("description", "").strip()
        if not prop:
            if description:
                event["description"] = description
            continue
        entry: dict[str, Any] = {"name": prop, "type": row.get("type", "").strip() or "string"}
        required = _flag(row.get("required", ""), number, "required")
        pii = _flag(row.get("pii", ""), number, "pii")
        if required is not None:
            entry["required"] = required
        if pii is not None:
            entry["pii"] = pii
        if description:
            entry["description"] = description
        values = [v.strip() for v in row.get("allowed_values", "").split("|") if v.strip()]
        if values:
            entry["allowed_values"] = values
        event["properties"].append(entry)

    if not events:
        raise CsvImportError(f"{file}: no events found")
    data: dict[str, Any] = {
        VERSION_KEY: PLAN_VERSION,
        "id": plan_id,
        "title": title,
        "identity_keys": identity_keys,
        "events": list(events.values()),
    }
    if owner:
        data["owner"] = owner
    return TrackingPlan.from_dict(data)
