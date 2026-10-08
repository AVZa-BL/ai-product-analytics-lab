"""Read a tracking plan from a YAML file.

PyYAML on its own is too forgiving for a contract. A repeated key silently keeps its last
value, `on:` and `yes:` become booleans, and aliases and merge keys copy values around unseen.
This module reads with `SafeLoader` (no arbitrary objects) and refuses each of those with a
message that names the file and the line. Whether the result is a valid plan is
`TrackingPlan.from_dict`'s question, not this module's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from linesman.plan import TrackingPlan


class LoadError(ValueError):
    """The file could not be read, or is not YAML that Linesman accepts for a plan."""


def _where(source: str, mark: yaml.Mark | None) -> str:
    return source if mark is None else f"{source}:{mark.line + 1}:{mark.column + 1}"


class _PlanLoader(yaml.SafeLoader):
    """SafeLoader that refuses what would silently change a plan's meaning."""

    def __init__(self, stream: str, source: str) -> None:
        super().__init__(stream)
        self.source = source

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node | None:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise LoadError(
                f"{_where(self.source, event.start_mark)}: alias *{event.anchor} is not allowed "
                "in a plan; write the value out where it is used"
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        first_line: dict[str, int] = {}
        for key_node, _ in node.value:
            where = _where(self.source, key_node.start_mark)
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise LoadError(f"{where}: merge keys (<<) are not allowed in a plan")
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str):
                written = getattr(key_node, "value", key_node)
                raise LoadError(
                    f'{where}: key {written!r} is read by YAML as {key!r}, not as text; '
                    f'quote it: "{written}":'
                )
            if key in first_line:
                raise LoadError(
                    f"{where}: duplicate key {key!r} (first given on line {first_line[key]})"
                )
            first_line[key] = key_node.start_mark.line + 1
        return super().construct_mapping(node, deep=deep)


def _problem(source: str, error: yaml.YAMLError) -> str:
    if isinstance(error, yaml.MarkedYAMLError):
        problem = error.problem or "invalid YAML"
        if error.context:
            problem = f"{error.context}: {problem}"
        return f"{_where(source, error.problem_mark)}: {problem}"
    return f"{source}: {str(error).splitlines()[0]}"


def parse_plan(text: str, *, source: str = "<string>") -> TrackingPlan:
    """Parse YAML text and validate it as a plan.

    Raises LoadError for YAML this module rejects, and PlanError, listing every violation,
    for a mapping that is not a valid plan.
    """
    try:
        data = _PlanLoader(text, source).get_single_data()
    except yaml.YAMLError as error:
        raise LoadError(_problem(source, error)) from error
    return TrackingPlan.from_dict(data)


def load_plan(path: str | Path) -> TrackingPlan:
    """Read, parse and validate the plan file at `path`."""
    source = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise LoadError(f"{source}: not valid UTF-8 (at byte offset {error.start})") from error
    except OSError as error:
        raise LoadError(f"{source}: cannot be read: {error.strerror or error}") from error
    return parse_plan(text, source=source)
