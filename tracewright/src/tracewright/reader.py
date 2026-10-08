"""A strict reader for plain mappings, shared by tracking plans and model proposals.

Reading never raises on the first problem: each violation is recorded with its path and the
caller raises once at the end, so a person fixing a file sees every problem in one run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


class Node:
    """A mapping being read: collects violations with their path and tracks unread keys."""

    def __init__(self, data: Mapping[str, Any], path: str, violations: list[str]) -> None:
        self.data = data
        self.path = path
        self.violations = violations
        self._seen: set[str] = set()

    def at(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def fail(self, key: str, message: str) -> None:
        self.violations.append(f"{self.at(key)}: {message}")

    def get(self, key: str, *, required: bool) -> Any:
        self._seen.add(key)
        value = self.data.get(key)
        if value is None and required:
            self.fail(key, "is required")
        return value

    def text(
        self, key: str, *, required: bool = True, allow_empty: bool = False
    ) -> str | None:
        value = self.get(key, required=required)
        if value is None:
            return None
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            self.fail(key, f"must be non-empty text, got {value!r}")
            return None
        return value.strip()

    def identifier(self, key: str) -> str | None:
        value = self.text(key)
        if value is not None and not _ID_PATTERN.fullmatch(value):
            self.fail(key, f"must use only a-z, 0-9 and _, got {value!r}")
            return None
        return value

    def boolean(self, key: str, *, default: bool) -> bool:
        value = self.get(key, required=False)
        if value is None:
            return default
        if not isinstance(value, bool):
            self.fail(key, f"must be true or false, got {value!r}")
            return default
        return value

    def choice(self, key: str, options: tuple[str, ...], *, default: str) -> str:
        value = self.get(key, required=False)
        if value is None:
            return default
        if value not in options:
            self.fail(key, f"must be one of {list(options)}, got {value!r}")
            return default
        return value

    def mapping(self, key: str, *, required: bool = True) -> Node | None:
        value = self.get(key, required=required)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            self.fail(key, f"must be an object, got {value!r}")
            return None
        return Node(value, self.at(key), self.violations)

    def require_keys(self, *keys: str) -> None:
        """Record "is required" for each key that is absent (a value of null counts as absent)."""
        for key in keys:
            if self.data.get(key) is None:
                self.fail(key, "is required")

    def items(self, key: str, *, required: bool = True) -> list[Node]:
        value = self.get(key, required=required)
        if value is None:
            return []
        if not isinstance(value, list) or (required and not value):
            self.fail(key, "must be a non-empty list" if required else "must be a list")
            return []
        nodes = []
        for index, item in enumerate(value):
            path = f"{self.at(key)}[{index}]"
            if isinstance(item, Mapping):
                nodes.append(Node(item, path, self.violations))
            else:
                self.violations.append(f"{path}: must be a mapping of fields, got {item!r}")
        return nodes

    def strings(
        self, key: str, *, required: bool, allow_empty: bool = False
    ) -> tuple[str, ...] | None:
        value = self.get(key, required=required)
        if value is None:
            return None
        ok = isinstance(value, list) and (allow_empty or value) and all(
            isinstance(item, str) and item.strip() for item in value
        )
        if not ok:
            kind = "a list of text" if allow_empty else "a non-empty list of text"
            self.fail(key, f"must be {kind}, got {value!r}")
            return None
        return tuple(item.strip() for item in value)

    def reject_unknown(self) -> None:
        for key in self.data:
            if key not in self._seen:
                self.fail(str(key), "is not a known field")
