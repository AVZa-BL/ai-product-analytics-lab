import pytest

from tracewright.sheets import values


def test_an_unknown_status_is_refused():
    with pytest.raises(ValueError, match="unknown status 'Blocked'"):
        values.status("Blocked")
    assert values.status("Blocked", {"blocked": "planned"}) == "planned"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("y", True), ("1", True), ("x", True), ("Required", True), ("0", False),
     ("Optional", False), ("-", False)],
)
def test_flags(text, expected):
    assert values.flag(text) is expected


def test_a_refused_notation_can_be_accepted_on_purpose_and_matches_the_cell_exactly():
    assert values.property_type("string[]", {"string[]": "string"}) == "string"
    assert values.property_type("int[]", {"INT[]": "string"}) == "string"
    with pytest.raises(ValueError):  # a different notation is still refused
        values.property_type("bool[]", {"string[]": "string"})


@pytest.mark.parametrize("text", ["Enum [a, b]"])
def test_an_enum_that_lists_its_values_in_the_type_cell_is_refused(text):
    with pytest.raises(ValueError, match="allowed-values column"):
        values.property_type(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("\u2705", True), ("\u2714\ufe0f", True), ("\u2611\ufe0f", True), ("\u274c", False),
     ("\u2612", False)],
)
def test_the_usual_tick_emoji(text, expected):
    if expected is None:  # a heavy multiplication X looks too much like a bare 'x' (= yes)
        with pytest.raises(ValueError):
            values.flag(text)
    else:
        assert values.flag(text) is expected


@pytest.mark.parametrize(
    "text",
    ["easy | normal | ..."],
)
def test_allowed_values_written_as_notation_are_refused(text):
    with pytest.raises(ValueError, match="looks like notation"):
        values.split_values(text)


