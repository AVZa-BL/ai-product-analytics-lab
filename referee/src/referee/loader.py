"""Read an experiment spec from a YAML file.

PyYAML on its own is too forgiving for a pre-registered spec. A repeated key silently keeps
its last value, an unquoted `null:` (the name of a hypothesis field) becomes a null key,
`on:` and `yes:` become booleans, and aliases and merge keys copy values around unseen. This
module reads with `SafeLoader` (no arbitrary objects) and refuses each of those with a
message that names the file, the line and what to write instead. Whether the result is a valid
spec is `ExperimentSpec.from_dict`'s question, not this module's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from referee.spec import ExperimentSpec


class LoadError(ValueError):
    """The file could not be read, or is not YAML that Referee accepts for a spec.

    The message already names the source and, where known, the line and column.
    """


def _where(source: str, mark: yaml.Mark | None) -> str:
    if mark is None:
        return source
    return f"{source}:{mark.line + 1}:{mark.column + 1}"


class _SpecLoader(yaml.SafeLoader):
    """SafeLoader that refuses what would silently change a spec's meaning."""

    def __init__(self, stream: str, source: str) -> None:
        super().__init__(stream)
        self.source = source

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node | None:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise LoadError(
                f"{_where(self.source, event.start_mark)}: alias *{event.anchor} is not allowed "
                "in a spec; write the value out where it is used"
            )
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        first_line: dict[str, int] = {}
        for key_node, _ in node.value:
            where = _where(self.source, key_node.start_mark)
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise LoadError(f"{where}: merge keys (<<) are not allowed in a spec")
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str):
                raise LoadError(f"{where}: {_not_text(key_node, key)}")
            if key in first_line:
                raise LoadError(
                    f"{where}: duplicate key {key!r} (first given on line {first_line[key]})"
                )
            first_line[key] = key_node.start_mark.line + 1
        return super().construct_mapping(node, deep=deep)


def _not_text(key_node: yaml.Node, key: object) -> str:
    if not isinstance(key_node, yaml.ScalarNode):
        return "a key must be text, not a list or a mapping"
    written = key_node.value
    if key is None:
        return (
            f"key {written!r} is read by YAML as null, not as text; "
            'if you mean the field called null, quote it: "null":'
        )
    if isinstance(key, bool):
        return (
            f"key {written!r} is read by YAML as {str(key).lower()}, not as text; "
            f'quote it: "{written}":'
        )
    return f'key {written!r} is not text; quote it: "{written}":'


def _problem(source: str, error: yaml.YAMLError) -> str:
    if isinstance(error, yaml.MarkedYAMLError):
        problem = error.problem or "invalid YAML"
        if error.context:
            joiner = ", " if problem.startswith("but ") else ": "
            problem = f"{error.context}{joiner}{problem}"
        return f"{_where(source, error.problem_mark)}: {problem}"
    return f"{source}: {str(error).splitlines()[0]}"


def parse_spec(text: str, *, source: str = "<string>") -> ExperimentSpec:
    """Parse YAML text and validate it as a spec.

    Raises LoadError for text YAML or this module rejects (including a timestamp that cannot
    exist), and SpecError, listing every violation, for a mapping that is not a valid spec.
    """

    try:
        # Building the loader already checks the text for control characters.
        data = _SpecLoader(text, source).get_single_data()
    except LoadError:
        raise
    except yaml.YAMLError as error:
        raise LoadError(_problem(source, error)) from error
    except ValueError as error:
        # PyYAML builds a timestamp while it constructs the document and raises a bare
        # ValueError for one that cannot exist (2026-02-30, hour 24, an offset of 24 hours).
        raise LoadError(f"{source}: {error}; if this is meant as text, quote it") from error
    return ExperimentSpec.from_dict(data)


def load_spec(path: str | Path) -> ExperimentSpec:
    """Read, parse and validate the spec file at `path`."""
    source = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise LoadError(f"{source}: not valid UTF-8 (at byte offset {error.start})") from error
    except OSError as error:
        raise LoadError(f"{source}: cannot be read: {error.strerror or error}") from error
    return parse_spec(text, source=source)
