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
