"""What every spec of Referee is read with: the error, the typed getters and the fingerprint.

An experiment spec (`referee.spec`) and a release spec (`referee.release_spec`) are different
documents with one discipline: a mapping is read through getters that record every violation
instead of raising on the first, unknown keys are refused with a hint, and a valid spec has one
canonical form whose SHA-256 is its fingerprint. This module holds that discipline; the spec
modules hold their schemas.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SpecError(ValueError):
    """The spec is malformed. Carries every violation found, not just the first.

    `kind` names the document in the message: an experiment spec unless the spec says otherwise.
    """

    def __init__(self, violations: Sequence[str], kind: str = "experiment spec") -> None:
        self.violations = tuple(violations)
        self.kind = kind
        super().__init__(self.violations, kind)

    def __str__(self) -> str:
        noun = "violation" if len(self.violations) == 1 else "violations"
        header = f"invalid {self.kind}: {len(self.violations)} {noun}"
        return "\n".join([header, *(f"  - {violation}" for violation in self.violations)])


def drop_unset(value: Any) -> Any:
    """Plain lists and dicts from `asdict`'s output, without None values or empty mappings."""
    if isinstance(value, dict):
        kept = {key: drop_unset(item) for key, item in value.items()}
        return {key: item for key, item in kept.items() if item is not None and item != {}}
    if isinstance(value, list | tuple):
        return [drop_unset(item) for item in value]
    return value


def canonical_json(data: Mapping[str, Any]) -> str:
    """One fixed text for a spec's plain data: sorted keys, no spaces, non-ASCII written as is.

    The same spec gives the same text however the input file was laid out, ordered or
    commented. The order inside a list is kept, because it is part of the spec.
    """
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(data: Mapping[str, Any]) -> str:
    """The hex SHA-256 of the canonical JSON as UTF-8: the spec's fingerprint.

    A lone surrogate, which a YAML escape such as "\\ud800" can put in a string, is written as
    the three bytes that UTF-8 would give it, so that it has a fingerprint too.
    """
    return hashlib.sha256(canonical_json(data).encode("utf-8", "surrogatepass")).hexdigest()


# --- Machinery: typed getters that record violations instead of raising -------------------

ABSENT: Any = object()


def show(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 40 else f"{text[:37]}..."


class Node:
    """One mapping of the spec, read through getters that record violations.

    A getter never raises on bad input. It appends a message to the list shared by the
    whole parse and returns a placeholder of the right type, so parsing carries on and the
    author sees every problem at once. Placeholders never escape: `from_dict` raises
    before it returns anything if even one violation was recorded.

    The keys a parser asks for are the keys the schema allows, so unknown-key detection
    cannot drift out of step with the parsers.

    A node built with raw=None stands for a section that is missing or not a mapping. That
    is reported once, where it was looked up; its own fields stay silent.
    """

    def __init__(self, raw: Mapping[Any, Any] | None, path: str, violations: list[str]) -> None:
        self.path = path
        self._raw: Mapping[Any, Any] = {} if raw is None else raw
        self._silent = raw is None
        self._violations = violations
        self._seen: set[str] = set()
        self._failed: set[str] = set()

    # -- bookkeeping

    def _at(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def fail(self, key: str, problem: str) -> None:
        self._failed.add(key)
        self._violations.append(f"{self._at(key)}: {problem}")

    def failed(self, *keys: str) -> bool:
        """True if any of `keys` was missing or invalid, so a cross-field check must skip."""
        return self._silent or any(key in self._failed for key in keys)

    def given(self, key: str) -> bool:
        """True when `key` is present and not null: an optional section that must then be read."""
        return self._raw.get(key) is not None

    def _lookup(self, key: str, *, required: bool) -> Any:
        self._seen.add(key)
        if key in self._raw:
            return self._raw[key]
        if required and not self._silent:
            self.fail(key, "is required")
        return ABSENT

    def reject_unknown(self) -> None:
        for key in self._raw:
            if key in self._seen:
                continue
            close = difflib.get_close_matches(str(key), sorted(self._seen), n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            self._violations.append(f"{self.path or 'spec'}: unknown key {key!r}{hint}")

    # -- text, choices, booleans

    def text(self, key: str, *, pattern: re.Pattern[str] | None = None) -> str:
        value = self._lookup(key, required=True)
        return "" if value is ABSENT else self._check_text(key, value, pattern)

    def optional_text(self, key: str) -> str | None:
        value = self._lookup(key, required=False)
        return None if value is ABSENT or value is None else self._check_text(key, value, None)

    def texts(self, key: str, *, pattern: re.Pattern[str] | None = None) -> tuple[str, ...]:
        """An optional list of texts, each checked like `text`. An absent or null list is empty;
        a repeated entry is a violation. The key counts as failed when any entry is."""
        value = self._lookup(key, required=False)
        if value is ABSENT or value is None:
            return ()
        if not isinstance(value, list | tuple):
            self.fail(key, f"must be a list, got {show(value)}")
            return ()
        items = tuple(
            self._check_text(f"{key}[{index}]", item, pattern) for index, item in enumerate(value)
        )
        if not all(items):
            self._failed.add(key)
        for item, count in Counter(item for item in items if item).items():
            if count > 1:
                self.fail(key, f"duplicate entry {item!r} (used {count} times)")
        return items

    def _check_text(self, key: str, value: Any, pattern: re.Pattern[str] | None) -> str:
        if not isinstance(value, str) or not value.strip():
            self.fail(key, f"must be a non-empty string, got {show(value)}")
            return ""
        if pattern is not None and not pattern.fullmatch(value):
            self.fail(key, f"must match {pattern.pattern}, got {show(value)}")
            return ""
        return value

    def choice[T](self, key: str, options: tuple[T, ...], *, default: T | None = None) -> T:
        value = self._lookup(key, required=default is None)
        if value is ABSENT:
            return options[0] if default is None else default
        if value not in options:
            allowed = ", ".join(str(option) for option in options)
            self.fail(key, f"must be one of {allowed}; got {show(value)}")
            return options[0]
        return value

    def optional_choice[T](self, key: str, options: tuple[T, ...]) -> T | None:
        value = self._lookup(key, required=False)
        if value is ABSENT or value is None:
            return None
        if value not in options:
            allowed = ", ".join(str(option) for option in options)
            self.fail(key, f"must be one of {allowed}; got {show(value)}")
            return None
        return value

    def optional_utc_timestamp(self, key: str) -> str | None:
        """An instant given in UTC, returned as one fixed text: ISO 8601 ending in Z.

        Text such as `2026-11-02T00:00:00Z` or `2026-11-02T00:00:00+00:00` is accepted, and so
        is a datetime, because YAML reads an unquoted timestamp as one. A date alone, a time
        with no offset or an offset other than zero is refused, since which instant it meant
        would be a guess. Spellings of one instant give one text, so they give one fingerprint.
        """
        value = self._lookup(key, required=False)
        if value is ABSENT or value is None:
            return None
        moment = value
        if isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                moment = None
        if not isinstance(moment, datetime):
            self.fail(
                key,
                f"must be an ISO 8601 timestamp such as 2026-11-02T00:00:00Z, got {show(value)}",
            )
            return None
        if moment.utcoffset() is None:
            self.fail(
                key,
                f"must carry a UTC offset (Z, +00 or +00:00), got {show(value)}",
            )
            return None
        if moment.utcoffset() != timedelta(0):
            self.fail(key, f"must be in UTC (offset 0), got {show(value)}")
            return None
        return moment.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"

    def boolean(self, key: str, *, default: bool) -> bool:
        value = self._lookup(key, required=False)
        if value is ABSENT:
            return default
        if not isinstance(value, bool):
            self.fail(key, f"must be true or false, got {show(value)}")
            return default
        return value

    # -- numbers (bool is an int in Python and NaN defeats comparisons, so both are handled)

    def integer(self, key: str, *, ge: int) -> int:
        value = self._lookup(key, required=True)
        if value is ABSENT:
            return ge
        if isinstance(value, bool) or not isinstance(value, int):
            self.fail(key, f"must be an integer, got {show(value)}")
            return ge
        if value < ge:
            self.fail(key, f"must be >= {ge}, got {value}")
            return ge
        return value

    def number(self, key: str, *, gt: float | None = None, lt: float | None = None) -> float:
        value = self._lookup(key, required=True)
        if value is ABSENT:
            return 0.0
        number = self._check_finite(key, value)
        if number is None:
            return 0.0
        # Written as a positive test so NaN, which fails every comparison, is rejected.
        if not ((gt is None or number > gt) and (lt is None or number < lt)):
            bounds = " and ".join(
                part
                for part in (
                    f"> {gt:g}" if gt is not None else "",
                    f"< {lt:g}" if lt is not None else "",
                )
                if part
            )
            self.fail(key, f"must be {bounds}, got {show(value)}")
            return 0.0
        return number

    def optional_number(self, key: str) -> float | None:
        value = self._lookup(key, required=False)
        return None if value is ABSENT or value is None else self._check_finite(key, value)

    def _check_finite(self, key: str, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.fail(key, f"must be a finite number, got {show(value)}")
            return None
        try:
            number = float(value)
        except OverflowError:  # an int too large for a float
            number = math.inf
        if not math.isfinite(number):
            self.fail(key, f"must be a finite number, got {show(value)}")
            return None
        return number

    # -- nested structure

    def mapping(self, key: str, *, required: bool = True) -> Node:
        value = self._lookup(key, required=required)
        if not required and (value is ABSENT or value is None):
            return Node({}, self._at(key), self._violations)
        return self._child(key, value)

    def sequence(self, key: str, *, required: bool = True) -> list[Node]:
        value = self._lookup(key, required=required)
        if value is ABSENT or (value is None and not required):
            return []
        if not isinstance(value, list | tuple):
            self.fail(key, f"must be a list, got {show(value)}")
            return []
        return [self._child(f"{key}[{index}]", item) for index, item in enumerate(value)]

    def _child(self, key: str, value: Any) -> Node:
        if value is ABSENT:
            return Node(None, self._at(key), self._violations)
        if not isinstance(value, Mapping):
            self.fail(key, f"must be a mapping, got {show(value)}")
            return Node(None, self._at(key), self._violations)
        return Node(value, self._at(key), self._violations)
