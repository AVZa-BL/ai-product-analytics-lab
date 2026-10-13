"""A table of text cells with the row numbers the person sees in the spreadsheet."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

# A spreadsheet row is one CSV record, even when a cell holds line breaks.
csv.field_size_limit(1_000_000)


class TableError(ValueError):
    """A table cannot be read. The message names the source and, where known, the row."""


@dataclass(frozen=True, kw_only=True)
class Table:
    label: str  # where it came from: a file name, or "Google Sheet, tab 'Events'"
    header_row: int  # 1-based row number of the header in the source
    header: tuple[str, ...]
    rows: tuple[tuple[int, tuple[str, ...]], ...]  # (row number in the source, cells)


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA: how a spreadsheet names the column."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def clean_cell(value: object) -> str:
    """Cell text with no-break spaces made ordinary and the ends trimmed."""
    return str(value).replace(" ", " ").strip()


def table_from_rows(label: str, records: list[list[object]], header_row: int = 1) -> Table:
    """A table from rows of cells, where `records[0]` is source row 1."""
    if header_row < 1:
        raise TableError(f"{label}: --header-row must be 1 or more")
    if header_row > len(records):
        raise TableError(
            f"{label}: --header-row {header_row} is past the end; the source has "
            f"{len(records)} row(s)"
        )
    header = tuple(clean_cell(cell) for cell in records[header_row - 1])
    rows = tuple(
        (number, tuple(clean_cell(cell) for cell in record))
        for number, record in enumerate(records[header_row:], start=header_row + 1)
    )
    return Table(label=label, header_row=header_row, header=header, rows=rows)


def read_csv_text(text: str, label: str, header_row: int = 1) -> Table:
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as error:
        raise TableError(f"{label}: not readable as CSV: {error}") from error
    return table_from_rows(label, records, header_row)
