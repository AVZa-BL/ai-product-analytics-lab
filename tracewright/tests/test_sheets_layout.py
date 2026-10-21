import pytest

from tests.sheet_helpers import table
from tracewright.sheets.layout import parse_overrides, resolve_layout
from tracewright.sheets.table import TableError, column_letter


def layout(text, **kw):
    t = table(text)
    return t, resolve_layout(t, **kw)


def test_two_columns_that_could_be_one_meaning_are_an_error_not_a_coin_toss():
    with pytest.raises(TableError) as caught:
        layout("Event,Type,Data Type\na,b,c\n")
    message = str(caught.value)
    assert "2 columns could be 'type'" in message and "B 'Type'" in message
    assert "C 'Data Type'" in message and "--map type=HEADER" in message


def test_two_meanings_cannot_share_one_column():
    with pytest.raises(TableError, match="two meanings at the same column"):
        layout("Event,Kind\na,b\n", overrides={"type": "Kind", "property": "Kind"})


def test_titles_above_the_header_are_diagnosed():
    with pytest.raises(TableError, match="header row is empty"):
        resolve_layout(table(",,\nTracking spec,,\n"))


def test_data_under_a_column_with_no_header_is_not_ignored_silently():
    with pytest.raises(TableError, match="no header"):
        layout("Event,,Type\na,secret,string\n")
    # an entirely empty headerless column is harmless
    layout("Event,,Type\na,,string\n")


@pytest.mark.parametrize(("index", "letter"), [(26, "AA")])
def test_column_letters(index, letter):
    assert column_letter(index) == letter


def test_overrides_are_parsed_and_checked():
    assert parse_overrides(["type=Data Type", "event = Name "]) == {
        "type": "Data Type", "event": "Name"}
    for bad in ("type", "type=", "=Name", "colour=Name"):
        with pytest.raises(TableError):
            parse_overrides([bad])
    with pytest.raises(TableError, match="twice"):
        parse_overrides(["type=A", "type=B"])


def test_the_committed_column_list_is_what_the_code_generates():
    from pathlib import Path

    from tracewright.sheets.docs import render

    doc = Path(__file__).resolve().parent.parent / "docs" / "column-names.md"
    assert doc.read_text(encoding="utf-8") == render(), (
        "docs/column-names.md has drifted. From tracewright/, run: "
        "python -m tracewright.sheets.docs > docs/column-names.md"
    )
