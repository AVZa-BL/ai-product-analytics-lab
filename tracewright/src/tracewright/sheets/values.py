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
    {
        "true", "t", "yes", "y", "1", "x", "required", "mandatory",
        "\u2713", "\u2714", "\u2611", "\u2705",
    }
)
_FALSE = frozenset(
    {
        "false", "f", "no", "n", "0", "optional", "-",
        "\u2717", "\u2718", "\u2610", "\u2612", "\u274c",
    }
)
# The emoji variation selector and the zero-width joiner follow many ticks (a heavy tick that is
# drawn as an emoji): they are dropped before a word is looked up.
_INVISIBLE = {ord("\ufe0f"): None, ord("\u200d"): None}

# A unit or a length after the type ("string (max 50)", "integer [0-3]") is ignored. Empty
# brackets and angle brackets are list notation, which is refused, not ignored.
_QUALIFIER = re.compile(r"\s*(?:\(.*|\[[^\]]+\].*)$")
_LIST_NOTATION = re.compile(r"\[\s*\]\s*$|<.*>")
VALUE_SEPARATORS = re.compile(r"[|;,\n]")

# What a cell holds when a person means "nothing here": not a property name.
PLACEHOLDER_WORDS = frozenset(
    {"-", "--", "\u2013", "\u2014", "n/a", "na", "n.a.", "none", "null", "nil", "tbd", "(none)",
     "no properties", "no parameters", "no params"}
)
_LIST_MARKS = re.compile(r"[,;|\n(]")
_NOTATION = re.compile(r"[\[\](){}]")
_QUOTES = "\"'\u2018\u2019\u201c\u201d"
_ELLIPSES = frozenset({"etc", "etc.", "...", "\u2026"})


def flag(text: str) -> bool | None:
    """True or False for a recognised word, None for an empty cell, ValueError otherwise."""
    word = text.translate(_INVISIBLE).strip().casefold()
    if not word:
        return None
    if word in _TRUE:
        return True
    if word in _FALSE:
        return False
    raise ValueError(word)


def property_type(text: str, extra: dict[str, str] | None = None) -> str:
    """A plan type for the words in a type cell. Raises ValueError with the reason."""
    raw = text.strip()
    # A word added by the person is matched on the cell exactly first, so a notation that is
    # otherwise refused ('string[]') can be accepted on purpose with --type-map 'string[]=string'.
    exact = {k.strip().casefold(): v for k, v in (extra or {}).items()}
    if raw.casefold() in exact:
        return exact[raw.casefold()]
    if _LIST_NOTATION.search(raw):
        raise ValueError(
            f"{text!r} is a list, and a plan has no lists. Describe the items in separate "
            f"properties, or record it as a string on purpose with --type-map '{raw}=string'"
        )
    cleaned = _QUALIFIER.sub("", raw).strip()
    word = key(cleaned)
    table = {**TYPE_WORDS, **{key(k): v for k, v in (extra or {}).items()}}
    if word in table:
        if table[word] == "enum" and cleaned != raw:
            raise ValueError(
                f"{text!r} lists the values of an enum in the type cell. Put the values in the "
                "allowed-values column and write just 'enum' here"
            )
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
    """Allowed values written in one cell, separated by | ; , or line breaks.

    A part that is clearly notation and not a value (brackets, quotation marks, 'etc.') is
    refused with ValueError, because storing it would put the notation into the plan.
    """
    parts = [part.strip() for part in VALUE_SEPARATORS.split(text) if part.strip()]
    for part in parts:
        if _NOTATION.search(part) or part.casefold() in _ELLIPSES or part[0] in _QUOTES or (
            part[-1] in _QUOTES
        ):
            raise ValueError(
                f"{part!r} looks like notation, not a value (brackets, quotation marks or "
                "'etc.'). A comma, bar, semicolon or line break always separates values, so "
                "write the plain values with one of those between them"
            )
    return parts


def property_name_problem(text: str) -> str | None:
    """Why a property cell cannot be a property name, or None when it can."""
    if text.strip().casefold() in PLACEHOLDER_WORDS:
        return (
            f"the property cell is {text!r}, which is not a property name. Leave it empty if "
            "this row describes the event, or if the event has no properties"
        )
    if _LIST_MARKS.search(text):
        return (
            f"the property cell {text!r} looks like a list of properties or a name with a "
            "type; a property goes on a row of its own, with the type in the type column"
        )
    return None
