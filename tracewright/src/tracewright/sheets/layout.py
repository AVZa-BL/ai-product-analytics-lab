"""Which column of a table means what.

A real sheet never has our column names. Each meaning has a list of header spellings that people
use (compared with case, spaces and punctuation ignored), and the person can name a column
explicitly. Two columns that both fit one meaning are an error, not a coin toss, and a column that
fits no meaning is refused unless the person says to ignore the others.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tracewright.sheets.table import Table, TableError, column_letter
from tracewright.sheets.values import key

CANONICAL = (
    "event",
    "property",
    "type",
    "required",
    "pii",
    "allowed_values",
    "description",
    "event_description",
    "trigger",
    "owner",
    "status",
)

# Header spellings, as `key()` writes them. Bare 'name' is not here: it could be either name.
ALIASES: dict[str, tuple[str, ...]] = {
    "event": (
        "event", "eventname", "eventnames", "trackingevent", "trackingcall", "trackcall",
        "call", "calls", "eventtitle",
    ),
    "property": (
        "property", "propertyname", "parameter", "parametername", "param", "paramname",
        "attribute", "attributename", "field", "fieldname", "eventproperty", "eventparameter",
        "propertykey", "key",
    ),
    "type": (
        "type", "datatype", "propertytype", "parametertype", "paramtype", "valuetype",
        "fieldtype", "attributetype", "dtype",
    ),
    "required": ("required", "mandatory", "isrequired", "requiredfield"),
    "pii": ("pii", "personaldata", "containspii", "ispii", "sensitive"),
    "allowed_values": (
        "allowedvalues", "values", "possiblevalues", "enumvalues", "validvalues", "valuelist",
        "options",
    ),
    "description": (
        "description", "propertydescription", "parameterdescription", "desc",
        "propertydesc", "attributedescription", "fielddescription",
    ),
    "event_description": (
        "eventdescription", "eventdesc", "descriptionofevent", "eventdefinition",
    ),
    "trigger": (
        "trigger", "eventtrigger", "triggercondition", "firewhen", "fireswhen", "whenfired",
        "whentofire", "triggeredwhen", "when",
    ),
    "owner": ("owner", "eventowner", "ownedby", "responsible", "team", "dri"),
    "status": ("status", "eventstatus", "implementationstatus", "state"),
}
_ALIAS_TO_CANONICAL = {alias: name for name, aliases in ALIASES.items() for alias in aliases}
assert len(_ALIAS_TO_CANONICAL) == sum(len(a) for a in ALIASES.values()), "an alias is repeated"


@dataclass(frozen=True, kw_only=True)
class Layout:
    columns: dict[str, int]  # canonical name -> column index in the table
    ignored: tuple[int, ...]  # column indexes that fit no meaning and were set aside

    def describe(self, table: Table) -> list[str]:
        """One line per column used, and one for the columns ignored, for the person to read."""
        lines = []
        for name, i in sorted(self.columns.items(), key=lambda item: item[1]):
            line = f"{name} <- column {column_letter(i)} {table.header[i]!r}"
            if name == "description" and "event_description" not in self.columns:
                line += (
                    " (a property's description; on a row with no property, the event's. "
                    "If this column describes the event, use --map event_description=...)"
                )
            lines.append(line)
        if self.ignored:
            skipped = ", ".join(f"{column_letter(i)} {table.header[i]!r}" for i in self.ignored)
            lines.append(f"ignored: {skipped}")
        return lines


def parse_overrides(pairs: list[str]) -> dict[str, str]:
    """`--map type="Data Type"` pairs as a dict. Raises TableError for a bad one."""
    overrides: dict[str, str] = {}
    for pair in pairs:
        name, sep, header = pair.partition("=")
        name, header = name.strip(), header.strip()
        if not sep or not header:
            raise TableError(
                f"--map {pair!r}: write it as NAME=HEADER, for example type='Data Type'"
            )
        if name not in CANONICAL:
            raise TableError(f"--map {pair!r}: NAME must be one of {list(CANONICAL)}")
        if name in overrides:
            raise TableError(f"--map names {name!r} twice")
        overrides[name] = header
    return overrides


_LETTER_REF = re.compile(r"@([A-Za-z]{1,3})")


def letter_index(letters: str) -> int:
    """'A' -> 0, 'AA' -> 26: the column a spreadsheet calls this."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _find(table: Table, wanted: str, found: str, what: str) -> list[int]:
    """The columns a person means by a header text or by '@E' (a column letter)."""
    ref = _LETTER_REF.fullmatch(wanted.strip())
    if ref:
        index = letter_index(ref.group(1))
        if index >= len(table.header):
            raise TableError(
                f"{table.label}: {what}: there is no column {ref.group(1).upper()}. "
                f"Columns found: {found}"
            )
        return [index]
    matches = [i for i, h in enumerate(table.header) if h and key(h) == key(wanted)]
    if not matches:
        raise TableError(f"{table.label}: {what}: no such column. Columns found: {found}")
    return matches


def resolve_layout(
    table: Table,
    overrides: Mapping[str, str] | None = None,
    *,
    ignore_other_columns: bool = False,
    ignore_columns: Sequence[str] = (),
) -> Layout:
    """Decide which column is which. Raises TableError that says what to do about a problem."""
    overrides = dict(overrides or {})
    header = table.header
    found = ", ".join(f"{column_letter(i)} {h!r}" for i, h in enumerate(header) if h) or "(none)"
    columns: dict[str, int] = {}

    switched_off: set[int] = set()
    for wanted in ignore_columns:
        switched_off.update(_find(table, wanted, found, f"--ignore-column {wanted!r}"))

    for name, wanted in overrides.items():
        what = f"--map {name}={wanted!r}"
        matches = _find(table, wanted, found, what)
        if len(matches) > 1:
            letters = ", ".join(column_letter(i) for i in matches)
            first = column_letter(matches[0])
            raise TableError(
                f"{table.label}: {what} fits more than one column ({letters}) because their "
                f"headers are the same. Pick one by its letter: --map {name}=@{first}"
            )
        if matches[0] in switched_off:
            raise TableError(f"{table.label}: {what} names a column that --ignore-column removes")
        columns[name] = matches[0]
    taken = set(columns.values())
    if len(taken) != len(columns):
        raise TableError(f"{table.label}: --map points two meanings at the same column")

    candidates: dict[str, list[int]] = {}
    for i, h in enumerate(header):
        name = _ALIAS_TO_CANONICAL.get(key(h))
        if name and name not in columns and i not in taken and i not in switched_off:
            candidates.setdefault(name, []).append(i)
    for name, indexes in candidates.items():
        if len(indexes) > 1:
            options = ", ".join(f"{column_letter(i)} {header[i]!r}" for i in indexes)
            first, rest = column_letter(indexes[0]), column_letter(indexes[1])
            raise TableError(
                f"{table.label}: {len(indexes)} columns could be '{name}': {options}. "
                f"Say which one with --map {name}=HEADER, or by column letter with "
                f"--map {name}=@{first}; to drop one, --ignore-column @{rest}"
                + (" (the headers are identical, so a letter is the only way)"
                   if len({key(header[i]) for i in indexes}) == 1 else "")
            )
        columns[name] = indexes[0]

    if "event" not in columns:
        raise TableError(_no_event_message(table, found))

    used = set(columns.values()) | switched_off
    leftover = tuple(i for i, h in enumerate(header) if i not in used and _has_content(table, i, h))
    if leftover and not ignore_other_columns:
        names = ", ".join(f"{column_letter(i)} {header[i] or '(no header)'!r}" for i in leftover)
        raise TableError(
            f"{table.label}: these columns fit no meaning: {names}. "
            "Map one with --map NAME=HEADER (or NAME=@LETTER; NAME is one of "
            f"{list(CANONICAL)}), or add --ignore-other-columns to set them aside"
        )
    return Layout(
        columns=columns, ignored=tuple(sorted(set(leftover) | switched_off))
    )


def _has_content(table: Table, index: int, header: str) -> bool:
    """A column with a header, or with any data under it, is not set aside silently."""
    if header:
        return True
    return any(index < len(cells) and cells[index] for _, cells in table.rows)


def _no_event_message(table: Table, found: str) -> str:
    hint = ""
    if len(table.header) == 1 and (";" in table.header[0] or "\t" in table.header[0]):
        hint = (
            " The header looks ;- or tab-delimited, but the file must be comma-separated "
            "(in a spreadsheet: download as CSV, comma-separated)."
        )
    elif not any(table.header):
        hint = " The header row is empty; if the headers are lower down, pass --header-row N."
    return (
        f"{table.label}: no column looks like the event name. Columns found: {found}. "
        f"Name it with --map event=HEADER, or use --header-row N if the headers are on a later "
        f"row.{hint}"
    )
