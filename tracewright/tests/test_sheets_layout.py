import pytest

from tests.sheet_helpers import example, table
from tracewright.sheets.layout import ALIASES, CANONICAL, parse_overrides, resolve_layout
from tracewright.sheets.table import TableError, column_letter


def layout(text, **kw):
    t = table(text)
    return t, resolve_layout(t, **kw)


def test_every_alias_belongs_to_one_meaning_and_every_meaning_has_aliases():
    assert set(ALIASES) == set(CANONICAL)
    spellings = [a for aliases in ALIASES.values() for a in aliases]
    assert len(spellings) == len(set(spellings))


def test_the_flat_example_is_understood():
    t, lay = layout(example("flat-rows.csv"), ignore_other_columns=True)
    read = {name: t.header[i] for name, i in lay.columns.items()}
    assert read == {
        "event": "Tracking Call", "property": "Parameter", "type": "Data Type",
        "required": "Mandatory?", "allowed_values": "Allowed Values", "description": "Description",
        "trigger": "Fires when", "owner": "Team", "status": "Implementation Status",
    }
    assert [t.header[i] for i in lay.ignored] == ["Jira", "Notes"]


def test_the_merged_cell_example_separates_event_and_property_descriptions():
    t, lay = layout(example("merged-cells.csv"))
    assert t.header[lay.columns["event_description"]] == "Event description"
    assert t.header[lay.columns["description"]] == "Property description"
    assert t.header[lay.columns["allowed_values"]] == "Possible values"
    assert not lay.ignored


def test_columns_that_fit_no_meaning_are_refused_by_default_with_a_way_out():
    with pytest.raises(TableError) as caught:
        layout(example("flat-rows.csv"))
    message = str(caught.value)
    assert "K 'Jira'" not in message and "J 'Jira'" in message and "K 'Notes'" in message
    assert "--ignore-other-columns" in message and "--map NAME=HEADER" in message


def test_two_columns_that_could_be_one_meaning_are_an_error_not_a_coin_toss():
    with pytest.raises(TableError) as caught:
        layout("Event,Type,Data Type\na,b,c\n")
    message = str(caught.value)
    assert "2 columns could be 'type'" in message and "B 'Type'" in message
    assert "C 'Data Type'" in message and "--map type=HEADER" in message


def test_an_explicit_map_settles_it_and_beats_the_aliases():
    t, lay = layout("Event,Type,Data Type\na,b,c\n", overrides={"type": "Data Type"},
                    ignore_other_columns=True)
    assert lay.columns["type"] == 2
    assert [t.header[i] for i in lay.ignored] == ["Type"]


def test_a_map_to_a_column_that_does_not_exist_lists_the_columns():
    with pytest.raises(TableError, match=r"no such column. Columns found: A 'Event', B 'Kind'"):
        layout("Event,Kind\na,b\n", overrides={"type": "Data Type"})


def test_a_map_that_fits_two_columns_is_refused():
    with pytest.raises(TableError, match="more than one column"):
        layout("Event,Kind,Kind\na,b,c\n", overrides={"type": "Kind"})


def test_two_meanings_cannot_share_one_column():
    with pytest.raises(TableError, match="two meanings at the same column"):
        layout("Event,Kind\na,b\n", overrides={"type": "Kind", "property": "Kind"})


def test_no_event_column_says_where_to_look():
    with pytest.raises(TableError) as caught:
        layout("Name,Type\na,b\n")
    message = str(caught.value)
    assert "no column looks like the event name" in message
    assert "A 'Name', B 'Type'" in message
    assert "--map event=HEADER" in message and "--header-row N" in message


def test_titles_above_the_header_are_diagnosed():
    with pytest.raises(TableError, match="header row is empty"):
        resolve_layout(table(",,\nTracking spec,,\n"))


def test_a_semicolon_file_is_recognised():
    with pytest.raises(TableError, match="comma-separated"):
        layout("event;property;type\na;b;c\n")


def test_data_under_a_column_with_no_header_is_not_ignored_silently():
    with pytest.raises(TableError, match="no header"):
        layout("Event,,Type\na,secret,string\n")
    # an entirely empty headerless column is harmless
    layout("Event,,Type\na,,string\n")


def test_unrelated_extra_columns_can_be_set_aside_explicitly():
    t, lay = layout("Event,Reviewer\na,bob\n", ignore_other_columns=True)
    assert [t.header[i] for i in lay.ignored] == ["Reviewer"]


def test_the_description_lines_tell_a_person_what_was_read():
    t, lay = layout("Event Name,Parameter,Notes\na,b,c\n", ignore_other_columns=True)
    assert lay.describe(t) == [
        "event <- column A 'Event Name'", "property <- column B 'Parameter'",
        "ignored: C 'Notes'",
    ]


@pytest.mark.parametrize(
    ("index", "letter"), [(0, "A"), (25, "Z"), (26, "AA"), (51, "AZ"), (702, "AAA")]
)
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
