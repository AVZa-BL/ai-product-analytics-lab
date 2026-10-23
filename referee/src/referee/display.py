"""What a person reads is capped; what a computation reads is not.

Section 20.3 of the design: a text report lists at most 1,000 rows per listing and says so, and
the JSON report holds every row. The cap is applied to a finished list only, after every count
and statistic is computed, so it can change what is shown and nothing else: `total` is always
the exact number of rows, and no function here sees anything it could compute from.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

DISPLAY_ROW_LIMIT = 1_000


@dataclass(frozen=True, kw_only=True)
class Listing[T]:
    """The rows to show, how many there are in all, and the cap that was applied."""

    shown: tuple[T, ...]
    total: int
    limit: int

    @property
    def truncated(self) -> bool:
        return self.total > len(self.shown)

    @property
    def notice(self) -> str | None:
        """The line that tells a reader rows are missing, or None when all are shown."""
        if not self.truncated:
            return None
        return f"showing {len(self.shown):,} of {self.total:,}; the full list is in the JSON report"


def cap_listing[T](rows: Sequence[T], *, limit: int = DISPLAY_ROW_LIMIT) -> Listing[T]:
    """The first `limit` of `rows`, in their order, with the exact total."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit must be a whole number of at least 1, got {limit!r}")
    return Listing(shown=tuple(rows[:limit]), total=len(rows), limit=limit)


def _written(text: str, *, keep_newline: bool) -> str:
    return "".join(
        ascii(char)[1:-1]
        if (not keep_newline or char != "\n")
        and unicodedata.category(char).startswith(("C", "Zl", "Zp"))
        else char
        for char in text
    )


def for_terminal(text: str) -> str:
    """`text` with each control, format, unassigned, line-separator and paragraph-separator
    character but the newline written as an escape (`\\x1b`), so that a player id, a title or
    a file's content cannot move the cursor, recolour the screen or hide what follows it.

    For a block of lines made by Referee. A value that comes from a spec or an export and is
    printed as part of a line goes through `for_line`: with a newline in it, it would make
    lines of its own.
    """
    return _written(text, keep_newline=True)


def for_line(text: str) -> str:
    """`text` as `for_terminal` writes it, and with the newline written as an escape too."""
    return _written(text, keep_newline=False)
