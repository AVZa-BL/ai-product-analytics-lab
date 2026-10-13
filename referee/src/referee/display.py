"""What a person reads is capped; what a computation reads is not.

Section 20.3 of the design: a text report lists at most 1,000 rows per listing and says so, and
the JSON report holds every row. The cap is applied to a finished list only, after every count
and statistic is computed, so it can change what is shown and nothing else: `total` is always
the exact number of rows, and no function here sees anything it could compute from.
"""

from __future__ import annotations

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
