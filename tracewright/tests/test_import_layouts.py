import pytest

from tests.sheet_helpers import KW, example, table
from tracewright.importer import import_plan_tables
from tracewright.review import review_plan
from tracewright.sheets.table import TableError


def run(text, *, header_row=1, **options):
    return import_plan_tables([table(text, header_row=header_row)], **KW, **options)


def events(result):
    return {e.name: e for e in result.plan.events}


def test_the_flat_layout_with_repeated_event_names():
    result = run(example("flat-rows.csv"), ignore_other_columns=True)
    level = events(result)["level_completed"]
    assert (level.description, level.trigger, level.owner, level.status) == (
        "A player finishes a level", "The result screen is shown", "progression", "active")
    props = {p.name: p for p in level.properties}
    assert list(props) == ["player_id", "level_id", "stars", "difficulty"]
    assert props["stars"].type == "integer" and props["stars"].required is False  # "int", "No"
    assert props["level_id"].required is True  # "Yes"
    # "easy | normal | hard" in the cell
    assert props["difficulty"].allowed_values == ("easy", "normal", "hard")
    assert events(result)["shop_opened"].status == "planned"  # "To do"


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


def test_both_layouts_give_plans_the_review_rules_accept_without_a_blocker():
    for name, options in (("flat-rows.csv", {"ignore_other_columns": True}),
                          ("merged-cells.csv", {"fill_down": True})):
        review = review_plan(run(example(name), **options).plan)
        assert not review.blocking_rule_ids, (name, review.findings)


def test_the_mapping_is_reported_so_a_person_can_check_it():
    result = run(example("flat-rows.csv"), ignore_other_columns=True)
    text = "\n".join(result.mapping)
    assert "event <- column A 'Tracking Call'" in text
    assert "type <- column C 'Data Type'" in text and "ignored: J 'Jira', K 'Notes'" in text


def test_row_numbers_are_the_rows_the_spreadsheet_shows():
    text = "Spec v3\n\nupdated today\nEvent,Property,Type\na_b,p,string\na_b,q,colour\n"
    with pytest.raises(TableError, match="row 6: unknown type 'colour'"):
        run(text, header_row=4)
    with pytest.raises(TableError, match="no column looks like the event name"):
        run(text)  # without --header-row the first row is taken as the header
    assert [p.name for p in events(run(text.replace("colour", "string"), header_row=4)
                                   )["a_b"].properties] == ["p", "q"]


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


def test_an_event_with_no_properties_is_kept():
    result = run("Event,Description\nlogin_failed,A login is refused\n")
    assert events(result)["login_failed"].properties == ()


def test_event_level_columns_must_agree_across_rows():
    text = "Event,Property,Owner\na_b,p,ann\na_b,q,bob\n"
    with pytest.raises(TableError, match="row 3: owner of event 'a_b' is 'bob', but an earlier"):
        run(text)


def test_several_tables_are_merged_and_errors_name_the_table():
    first = table("Event,Property\na_b,p\n", label="Sheet one")
    second = table("Event,Property,Type\nc_d,q,colour\n", label="Sheet two")
    with pytest.raises(TableError, match="Sheet two, row 2: unknown type 'colour'"):
        import_plan_tables([first, second], **KW)
    ok = table("Event,Property,Type\nc_d,q,string\n", label="Sheet two")
    assert set(events(import_plan_tables([first, ok], **KW))) == {"a_b", "c_d"}


def test_the_same_event_in_two_tables_is_one_event_and_a_repeated_property_is_caught():
    first = table("Event,Property\na_b,p\n", label="One")
    second = table("Event,Property\na_b,q\na_b,p\n", label="Two")
    with pytest.raises(TableError, match="Two, row 3: property 'p' of event 'a_b' is already"):
        import_plan_tables([first, second], **KW)


def test_blank_rows_and_ragged_rows_are_fine():
    text = "Event,Property,Type,Required\na_b,p\n\n,,,\na_b,q,integer\n"
    result = run(text)
    assert [(p.name, p.type) for p in events(result)["a_b"].properties] == [
        ("p", "string"), ("q", "integer")]


def test_no_events_below_the_header_is_an_error():
    with pytest.raises(TableError, match="no events found"):
        run("Event,Property\n")


def test_names_are_kept_exactly_as_written_and_not_tidied():
    result = run("Event,Property\nLevel Completed,Player ID\n")
    event = events(result)["Level Completed"]
    assert event.properties[0].name == "Player ID"  # NAM-001/NAM-002 will say so; we do not guess


def test_a_no_break_space_in_a_cell_is_an_ordinary_space():
    result = run("Event,Property\nlevel\u00a0done,p\n")
    assert "level done" in events(result)


# --- never turn something that is not understood into a plausible plan entry ---------------------


@pytest.mark.parametrize("cell", ["N/A", "-", "none", "TBD", "player_id (string)", "a, b"])
def test_a_property_cell_that_is_not_a_property_is_refused_with_its_row(cell):
    text = f"Event,Property\nlevel_done,player_id\nlevel_done,\"{cell}\"\n"
    with pytest.raises(TableError, match=r"row 3: .*property cell"):
        run(text)


@pytest.mark.parametrize("cell", ["string[]", "int[]", "List<string>"])
def test_a_list_type_is_refused_with_its_row(cell):
    with pytest.raises(TableError, match=r"row 2: .*is a list"):
        run(f"Event,Property,Type\na_b,p,{cell}\n")


def test_allowed_values_on_a_property_that_is_not_an_enum_are_refused_with_the_row():
    with pytest.raises(TableError, match=r"row 2: property 'p' has allowed values but its type is"):
        run("Event,Property,Type,Values\na_b,p,string,a|b\n")


@pytest.mark.parametrize("cell", ["[easy, normal, hard]", "easy (default) | hard", "easy, etc."])
def test_allowed_values_written_as_notation_are_refused_with_the_row(cell):
    with pytest.raises(TableError, match=r"row 2: allowed values of property 'p'.*notation"):
        run(f'Event,Property,Type,Values\na_b,p,enum,"{cell}"\n')


def test_an_enum_with_its_values_in_the_type_cell_is_refused_with_the_row():
    with pytest.raises(TableError, match=r"row 2: .*allowed-values column"):
        run("Event,Property,Type\na_b,p,enum (a | b)\n")


def test_a_status_merged_over_several_events_is_reported_not_silent():
    text = ("Event,Property,Status\nshop_opened,a,To do\nshop_closed,b,\npurchase_made,c,\n")
    result = run(text)
    note = next(n for n in result.notes if n.startswith("status:"))
    assert "shop_closed" in note and "purchase_made" in note and "shop_opened" not in note
    assert "--fill-down fills the event name only" in note
    assert events(result)["shop_closed"].status == "active"  # the plan default, and said so


def test_no_status_note_when_there_is_no_status_column():
    assert not [n for n in run("Event,Property\na_b,p\n").notes if n.startswith("status:")]


def test_banner_rows_are_reported_because_they_would_otherwise_become_events():
    text = ("Event,Property\n=== MONETISATION ===,\nshop_opened,player_id\n"
            "=== SOCIAL ===,\nlegend: x = required,\n")
    result = run(text)
    note = next(n for n in result.notes if "nothing else" in n)
    assert "'=== MONETISATION ==='" in note and "'=== SOCIAL ==='" in note
    assert "shop_opened" not in note and "remove its row" in note


def test_the_preview_shows_every_event_with_the_types_that_were_read():
    result = run(example("flat-rows.csv"), ignore_other_columns=True)
    start = "  level_completed (active): player_id:string*, level_id:string*, stars:integer, "
    assert result.preview[0].startswith(start)
    assert "difficulty:enum[easy|normal|hard]" in result.preview[0]
    assert result.preview[1].startswith("  shop_opened (planned):")


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
