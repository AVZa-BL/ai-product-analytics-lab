"""The words people write in cells, mapped to the values a plan allows.

Every mapping here is a plain table you can read. A word that is not in the table is refused with
the list of words that are, never guessed, because a wrong guess becomes a wrong type in a plan
that people then trust. Callers can add words (`--type-map`, `--status-map`).
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def key(text: str) -> str:
    """A header or word reduced to lower-case letters and digits: 'Event Name*' -> 'eventname'."""
    return _NON_WORD.sub("", text.casefold())


TYPE_WORDS: dict[str, str] = {
    **dict.fromkeys(
        ("string", "str", "text", "varchar", "char", "uuid", "guid", "id", "url", "uri"), "string"
    ),
    **dict.fromkeys(
        ("integer", "int", "long", "bigint", "smallint", "int32", "int64", "uint", "count"),
        "integer",
    ),
    **dict.fromkeys(
        ("number", "float", "double", "decimal", "numeric", "real", "float32", "float64"), "number"
    ),
    **dict.fromkeys(("boolean", "bool", "flag"), "boolean"),
    **dict.fromkeys(
        ("timestamp", "datetime", "date", "time", "iso8601", "datetimeoffset", "utc"), "timestamp"
    ),
    **dict.fromkeys(("enum", "enumeration", "select", "choice", "category", "oneof"), "enum"),
}
# Types a plan cannot express. They are refused with a reason, not stored as a wrong type.
UNSUPPORTED_TYPE_WORDS = frozenset(
    {"array", "list", "object", "json", "map", "dict", "dictionary", "set", "struct", "any"}
)

STATUS_WORDS: dict[str, str] = {
    **dict.fromkeys(
        ("active", "live", "implemented", "done", "released", "shipped", "production", "prod"),
        "active",
    ),
    **dict.fromkeys(
        ("planned", "todo", "backlog", "inprogress", "wip", "proposed", "draft", "notimplemented"),
        "planned",
    ),
    **dict.fromkeys(
        ("deprecated", "removed", "retired", "obsolete", "legacy", "toremove", "sunset"),
        "deprecated",
    ),
}

_TRUE = frozenset(
    {"true", "t", "yes", "y", "1", "x", "required", "mandatory", "✓", "✔", "☑"}
)
_FALSE = frozenset({"false", "f", "no", "n", "0", "optional", "-", "✗", "✘", "☐"})

_PARENTHETICAL = re.compile(r"\s*[\(\[].*$")
VALUE_SEPARATORS = re.compile(r"[|;,\n]")


def flag(text: str) -> bool | None:
    """True or False for a recognised word, None for an empty cell, ValueError otherwise."""
    word = text.strip().casefold()
    if not word:
        return None
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    raise ValueError(word)


def property_type(text: str, extra: dict[str, str] | None = None) -> str:
    """A plan type for the words in a type cell. Raises ValueError with the reason."""
    cleaned = _PARENTHETICAL.sub("", text).strip()
    word = key(cleaned)
    table = {**TYPE_WORDS, **{key(k): v for k, v in (extra or {}).items()}}
    if word in table:
        return table[word]
    if word in UNSUPPORTED_TYPE_WORDS:
        raise ValueError(
            f"{text!r} cannot be expressed in a plan (it has no lists or objects). Record it as "
            "a string with --type-map, or describe the items in separate properties"
        )
    raise ValueError(f"unknown type {text!r}")


def status(text: str, extra: dict[str, str] | None = None) -> str:
    """A plan status for the words in a status cell. Raises ValueError for an unknown word."""
    word = key(text)
    table = {**STATUS_WORDS, **{key(k): v for k, v in (extra or {}).items()}}
    if word in table:
        return table[word]
    raise ValueError(f"unknown status {text!r}")


def split_values(text: str) -> list[str]:
    """Allowed values written in one cell, separated by | ; , or line breaks."""
    return [part.strip() for part in VALUE_SEPARATORS.split(text) if part.strip()]
