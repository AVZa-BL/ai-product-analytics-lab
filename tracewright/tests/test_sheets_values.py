import pytest

from tracewright.sheets import values


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("string", "string"), ("String", "string"), ("TEXT", "string"), ("varchar(255)", "string"),
        ("uuid", "string"), ("int", "integer"), ("Integer", "integer"), ("bigint", "integer"),
        ("Int64", "integer"), ("float", "number"), ("Decimal", "number"), ("number", "number"),
        ("bool", "boolean"), ("Boolean", "boolean"), ("datetime", "timestamp"),
        ("Timestamp", "timestamp"), ("date", "timestamp"), ("ISO 8601", "timestamp"),
        ("enum", "enum"), ("Enumeration", "enum"), ("string (max 50)", "string"),
        ("integer [0-3]", "integer"),
    ],
)
def test_type_words(text, expected):
    assert values.property_type(text) == expected


@pytest.mark.parametrize("text", ["array", "List", "object", "JSON", "map"])
def test_types_a_plan_cannot_express_are_refused_with_the_reason(text):
    with pytest.raises(ValueError, match="cannot be expressed in a plan"):
        values.property_type(text)


def test_an_unknown_type_is_refused_not_guessed():
    with pytest.raises(ValueError, match="unknown type 'currency'"):
        values.property_type("currency")


def test_extra_type_words_can_be_added_and_override():
    assert values.property_type("Currency", {"currency": "string"}) == "string"
    assert values.property_type("count", {"count": "number"}) == "number"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Live", "active"), ("implemented", "active"), ("Done", "active"), ("To do", "planned"),
     ("In Progress", "planned"), ("WIP", "planned"), ("Deprecated", "deprecated"),
     ("to remove", "deprecated"), ("Not implemented", "planned")],
)
def test_status_words(text, expected):
    assert values.status(text) == expected


def test_an_unknown_status_is_refused():
    with pytest.raises(ValueError, match="unknown status 'Blocked'"):
        values.status("Blocked")
    assert values.status("Blocked", {"blocked": "planned"}) == "planned"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Yes", True), ("y", True), ("TRUE", True), ("1", True), ("✓", True), ("x", True),
     ("Required", True), ("No", False), ("FALSE", False), ("0", False), ("Optional", False),
     ("-", False), ("", None), ("  ", None)],
)
def test_flags(text, expected):
    assert values.flag(text) is expected


def test_a_flag_that_means_nothing_is_refused():
    with pytest.raises(ValueError):
        values.flag("maybe")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("a|b|c", ["a", "b", "c"]), ("a | b ; c", ["a", "b", "c"]), ("a, b", ["a", "b"]),
     ("a\nb\n", ["a", "b"]), ("", []), (" | ", [])],
)
def test_allowed_values_may_be_separated_several_ways(text, expected):
    assert values.split_values(text) == expected


@pytest.mark.parametrize("header", ["Event Name*", "event_name", "EVENT NAME", " event-name "])
def test_headers_are_compared_without_case_space_or_punctuation(header):
    assert values.key(header) == "eventname"


@pytest.mark.parametrize(
    "text",
    ["string[]", "int[]", "String []", "uuid[]", "number[][]", "List<string>", "Array<int>"],
)
def test_list_notation_is_refused_not_read_as_a_scalar(text):
    with pytest.raises(ValueError, match="is a list, and a plan has no lists"):
        values.property_type(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("integer [0-3]", "integer"), ("int[5]", "integer"), ("string (max 50)", "string")],
)
def test_a_length_or_range_after_the_type_is_still_ignored(text, expected):
    assert values.property_type(text) == expected


def test_a_refused_notation_can_be_accepted_on_purpose_and_matches_the_cell_exactly():
    assert values.property_type("string[]", {"string[]": "string"}) == "string"
    assert values.property_type("int[]", {"INT[]": "string"}) == "string"
    with pytest.raises(ValueError):  # a different notation is still refused
        values.property_type("bool[]", {"string[]": "string"})


@pytest.mark.parametrize("text", ["enum (menu | level_end | push)", "Enum [a, b]"])
def test_an_enum_that_lists_its_values_in_the_type_cell_is_refused(text):
    with pytest.raises(ValueError, match="allowed-values column"):
        values.property_type(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("\u2705", True), ("\u2714\ufe0f", True), ("\u2611\ufe0f", True), ("\u274c", False),
     ("\u2612", False), ("\u2716", None)],
)
def test_the_usual_tick_emoji(text, expected):
    if expected is None:  # a heavy multiplication X looks too much like a bare 'x' (= yes)
        with pytest.raises(ValueError):
            values.flag(text)
    else:
        assert values.flag(text) is expected


@pytest.mark.parametrize(
    "text",
    ["[easy, normal, hard]", "easy (default) | normal", "easy, hard, etc.", "easy | normal | ...",
     '"a", "b"', "'a' | 'b'", "{a} | {b}"],
)
def test_allowed_values_written_as_notation_are_refused(text):
    with pytest.raises(ValueError, match="looks like notation"):
        values.split_values(text)


@pytest.mark.parametrize(
    "text",
    ["N/A", "n/a", "-", "\u2014", "none", "None", "TBD", "(none)", "no properties",
     "player_id (string)", "a, b", "a; b", "a | b", "level_id\nitem_id"],
)
def test_a_property_cell_that_is_not_one_property_name_is_refused(text):
    assert values.property_name_problem(text)


@pytest.mark.parametrize("text", ["player_id", "Level ID", "level.id", "item-count", "price_minor"])
def test_ordinary_property_names_pass(text):
    assert values.property_name_problem(text) is None
