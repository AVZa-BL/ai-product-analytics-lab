import pytest

from tests.sheet_helpers import KW, example, table
from tracewright.importer import import_plan_tables
from tracewright.sheets.table import TableError


def run(text, *, header_row=1, **options):
    return import_plan_tables([table(text, header_row=header_row)], **KW, **options)


def events(result):
    return {e.name: e for e in result.plan.events}


def test_the_merged_cell_layout_needs_fill_down_and_then_reads_every_row():
    text = example("merged-cells.csv")
    with pytest.raises(TableError, match=r"row 3: the event column is empty.*--fill-down"):
        run(text)
    result = run(text, fill_down=True)
    shop = events(result)["shop_opened"]
    assert [p.name for p in shop.properties] == ["player_id", "entry_point", "contact_email"]
    assert shop.description == "The shop screen is opened" and shop.status == "active"
    props = {p.name: p for p in shop.properties}
    assert props["player_id"].required is True  # a tick
    assert props["contact_email"].pii is True and props["entry_point"].type == "enum"
    purchase = events(result)["purchase_made"]
    assert purchase.status == "planned" and purchase.trigger == "The store confirms the purchase"
    assert {p.name: p.type for p in purchase.properties}["price_minor"] == "integer"


def test_header_row_past_the_end_is_refused():
    with pytest.raises(TableError, match="--header-row 9 is past the end"):
        run("Event\na\n", header_row=9)


def test_type_and_status_words_can_be_added_from_the_command_line():
    text = "Event,Property,Type,Status\na_b,p,Currency,Blocked\n"
    with pytest.raises(TableError, match="--status-map"):  # the status is read before the type
        run(text)
    with pytest.raises(TableError, match="--type-map"):
        run(text, status_map={"blocked": "planned"})
    result = run(text, type_map={"currency": "string"}, status_map={"blocked": "planned"})
    assert events(result)["a_b"].status == "planned"


def test_blank_rows_and_ragged_rows_are_fine():
    text = "Event,Property,Type,Required\na_b,p\n\n,,,\na_b,q,integer\n"
    result = run(text)
    assert [(p.name, p.type) for p in events(result)["a_b"].properties] == [
        ("p", "string"), ("q", "integer")]


def test_a_no_break_space_in_a_cell_is_an_ordinary_space():
    result = run("Event,Property\nlevel\u00a0done,p\n")
    assert "level done" in events(result)


# --- never turn something that is not understood into a plausible plan entry ---------------------


@pytest.mark.parametrize("cell", ["-", "a, b"])
def test_a_property_cell_that_is_not_a_property_is_refused_with_its_row(cell):
    text = f"Event,Property\nlevel_done,player_id\nlevel_done,\"{cell}\"\n"
    with pytest.raises(TableError, match=r"row 3: .*property cell"):
        run(text)


def test_allowed_values_on_a_property_that_is_not_an_enum_are_refused_with_the_row():
    with pytest.raises(TableError, match=r"row 2: property 'p' has allowed values but its type is"):
        run("Event,Property,Type,Values\na_b,p,string,a|b\n")


@pytest.mark.parametrize("cell", ["[easy, normal, hard]", "easy, etc."])
def test_allowed_values_written_as_notation_are_refused_with_the_row(cell):
    with pytest.raises(TableError, match=r"row 2: allowed values of property 'p'.*notation"):
        run(f'Event,Property,Type,Values\na_b,p,enum,"{cell}"\n')


def test_banner_rows_are_reported_because_they_would_otherwise_become_events():
    text = ("Event,Property\n=== MONETISATION ===,\nshop_opened,player_id\n"
            "=== SOCIAL ===,\nlegend: x = required,\n")
    result = run(text)
    note = next(n for n in result.notes if "nothing else" in n)
    assert "'=== MONETISATION ==='" in note and "'=== SOCIAL ==='" in note
    assert "shop_opened" not in note and "remove its row" in note


def test_the_preview_marks_personal_data_and_caps_a_long_list():
    rows = "".join(f"a_b,p{i},string,,\n" for i in range(35))
    result = run("Event,Property,Type,Required,PII\n" + rows + "a_b,email,string,yes,yes\n")
    line = result.preview[0]
    assert line.endswith("... and 6 more") and "email" not in line  # past the 30th
    short = run("Event,Property,Type,Required,PII\na_b,email,string,yes,yes\n").preview[0]
    assert "email:string*!" in short


# --- choosing columns that headers cannot name --------------------------------------------------


def test_a_column_can_be_chosen_by_its_letter_when_two_headers_are_identical():
    text = "Event,Description,Property,Type,Description\na_b,about the event,p,string,about p\n"
    with pytest.raises(TableError) as caught:
        run(text)
    message = str(caught.value)
    assert "2 columns could be 'description'" in message
    assert "--map description=@B" in message and "the headers are identical" in message
    assert "--ignore-column @E" in message
    result = run(text, overrides={"description": "@E"}, ignore_columns=["@B"])
    assert events(result)["a_b"].properties[0].description == "about p"


def test_a_map_by_header_that_fits_two_columns_points_at_the_letter():
    expected = r"headers are the same. Pick one by its letter: --map type=@B"
    with pytest.raises(TableError, match=expected):
        run("Event,Kind,Kind\na,b,c\n", overrides={"type": "Kind"})


def test_a_recognised_column_can_be_switched_off():
    text = "Event,Property,Status\na_b,p,Blocked\n"
    with pytest.raises(TableError, match="unknown status"):
        run(text)
    assert events(run(text, ignore_columns=["Status"]))["a_b"].status == "active"


def test_a_column_letter_past_the_end_and_an_unknown_header_are_refused():
    for bad in ("@Z", "NoSuchHeader"):
        with pytest.raises(TableError, match="Columns found: A 'Event'"):
            run("Event\na\n", ignore_columns=[bad])


def test_a_mapped_column_cannot_also_be_switched_off():
    with pytest.raises(TableError, match="--ignore-column removes"):
        run("Event,Kind\na,b\n", overrides={"type": "Kind"}, ignore_columns=["Kind"])


def test_the_dry_run_line_says_what_a_bare_description_is_attached_to():
    result = run("Event,Property,Description\na_b,p,d\n")
    line = next(m for m in result.mapping if "description <-" in m)
    assert "a property's description" in line and "--map event_description=" in line
    with_event = run("Event,Event Description,Property,Description\na_b,e,p,d\n")
    assert not any("a property's description" in m for m in with_event.mapping)
