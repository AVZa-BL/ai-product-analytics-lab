import pytest

from tests.propose_helpers import ROOT
from tracewright.cli import main
from tracewright.importer import CsvImportError, import_plan_csv
from tracewright.loader import parse_plan, render_plan_yaml
from tracewright.plan import PlanError

KW = {"plan_id": "p", "title": "P", "identity_keys": ["player_id"]}
HEADER = "event,property,type,required,pii,allowed_values,description,trigger,owner,status\n"


def csv(tmp_path, body, header=HEADER):
    path = tmp_path / "t.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def test_the_example_csv_imports_and_reviews_clean():
    plan = import_plan_csv(ROOT / "examples" / "current-tracking.csv", **KW)
    assert [e.name for e in plan.events] == ["level_completed", "shop_opened"]
    level = plan.events[0]
    assert level.owner == "progression-analytics" and level.trigger
    difficulty = next(p for p in level.properties if p.name == "difficulty")
    assert difficulty.type == "enum" and difficulty.allowed_values == ("easy", "normal", "hard")


def test_rows_of_one_event_are_merged(tmp_path):
    path = csv(tmp_path, "a_b,player_id,string,true,,,,,,\na_b,x_y,integer,,,,,,,\n")
    plan = import_plan_csv(path, **KW)
    assert len(plan.events) == 1
    assert [p.name for p in plan.events[0].properties] == ["player_id", "x_y"]


def test_flags_accept_common_spellings(tmp_path):
    path = csv(tmp_path, "a_b,player_id,string,YES,No,,,,,\n")
    prop = import_plan_csv(path, **KW).events[0].properties[0]
    assert prop.required is True and prop.pii is False


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("a_b,p,string,maybe,,,,,,\n", "row 2: required must be true or false"),
        (",p,string,,,,,,,\n", "row 2: the event column is empty"),
        ("a_b,,,,,,,t1,,\na_b,p,string,,,,,t2,,\n", "row 3: trigger of event 'a_b' is 't2'"),
        ("", "no events found"),
    ],
)
def test_bad_rows_are_refused_with_a_row_number(tmp_path, body, message):
    with pytest.raises(CsvImportError, match=message):
        import_plan_csv(csv(tmp_path, body), **KW)


def test_header_problems(tmp_path):
    with pytest.raises(CsvImportError, match="'event' column"):
        import_plan_csv(csv(tmp_path, "x\n", header="name\n"), **KW)
    with pytest.raises(CsvImportError, match="unknown column"):
        import_plan_csv(csv(tmp_path, "a,b\n", header="event,colour\n"), **KW)


def test_a_plan_level_problem_is_a_plan_error_listing_everything(tmp_path):
    with pytest.raises(PlanError) as caught:
        import_plan_csv(
            csv(tmp_path, "a_b,p,string,,,,,,,\n"), **{**KW, "plan_id": "Bad Id", "title": "  "}
        )
    assert len(caught.value.violations) == 2


def test_unreadable_files(tmp_path):
    with pytest.raises(CsvImportError, match="cannot be read"):
        import_plan_csv(tmp_path / "nope.csv", **KW)
    binary = tmp_path / "b.csv"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(CsvImportError, match="UTF-8"):
        import_plan_csv(binary, **KW)


def test_yaml_written_by_the_importer_reads_back_to_the_same_plan():
    plan = import_plan_csv(ROOT / "examples" / "current-tracking.csv", **KW)
    assert parse_plan(render_plan_yaml(plan)).sha256() == plan.sha256()


def test_the_command_writes_a_file_and_the_file_reviews(tmp_path, capsys):
    out = tmp_path / "plan.yaml"
    code = main(
        ["import-plan", str(ROOT / "examples" / "current-tracking.csv"), "--id", "puzzle_core",
         "--title", "Puzzle", "--identity-key", "player_id", "--owner", "ga", "--out", str(out)]
    )
    assert code == 0 and main(["review-plan", str(out)]) == 0
    assert "Findings: none" in capsys.readouterr().out


def test_the_command_reports_problems_as_exit_2(tmp_path, capsys):
    path = csv(tmp_path, "a_b,p,string,maybe,,,,,,\n")
    code = main(["import-plan", str(path), "--id", "p", "--title", "T", "--identity-key", "p"])
    assert code == 2 and "row 2" in capsys.readouterr().err


# --- row-level problems carry the row number ----------------------------------------------------


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("a_b,p,uuid,,,,,,,\n", r"row 2: type must be one of .*got 'uuid'"),
        ("a_b,p,int,,,,,,,\n", r"row 2: type must be one of .*got 'int'"),
        ("a_b,p,string,,,,,,,\na_b,q,string,,,,,,,\na_b,p,string,,,,,,,\n",
         r"row 4: property 'p' of event 'a_b' is already declared on row 2"),
        ("a_b,,string,,,,,,,\n", r"row 2: the property cell is empty.*\['type'\]"),
        ("a_b,,,true,,,,,,\n", r"row 2: the property cell is empty.*\['required'\]"),
        ("a_b,,,,,,First,,,\na_b,,,,,,Second,,,\n", r"row 3: event 'a_b' already has a different"),
    ],
)
def test_row_level_problems_name_the_row(tmp_path, body, message):
    with pytest.raises(CsvImportError, match=message):
        import_plan_csv(csv(tmp_path, body), **KW)


def test_a_row_wider_than_the_header_is_refused_not_a_crash(tmp_path):
    path = csv(tmp_path, ",,,,,,,,,,extra\n")  # the case that used to raise AttributeError
    with pytest.raises(CsvImportError, match="row 2: has 11 cells but the header has 10"):
        import_plan_csv(path, **KW)


def test_an_unquoted_comma_in_a_value_is_caught_instead_of_shifting_the_columns(tmp_path):
    path = csv(tmp_path, "a_b,mode,string,,,,Mode, easy or hard,,,\n")
    with pytest.raises(CsvImportError, match="put a value that contains a comma in double quotes"):
        import_plan_csv(path, **KW)


def test_a_semicolon_delimited_file_gets_a_hint(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("event;property;type\na_b;p;string\n", encoding="utf-8")
    with pytest.raises(CsvImportError, match="comma-separated") as caught:
        import_plan_csv(path, **KW)
    assert "event;property;type" in str(caught.value)


def test_a_header_without_event_shows_what_was_found(tmp_path):
    with pytest.raises(CsvImportError, match=r"found \['event name', 'type'\]"):
        import_plan_csv(csv(tmp_path, "x,y\n", header="Event Name,Type\n"), **KW)


def test_an_oversized_file_is_refused_before_it_is_read(tmp_path, monkeypatch):
    from tracewright import importer

    path = csv(tmp_path, "a_b,p,string,,,,,,,\n")
    monkeypatch.setattr(importer, "MAX_BYTES", 10)
    read = []
    monkeypatch.setattr(type(path), "read_bytes", lambda self: read.append(self) or b"")
    with pytest.raises(CsvImportError, match="the limit is 10"):
        import_plan_csv(path, **KW)
    assert not read  # the size came from stat(), not from reading the whole file


# --- the command refuses to overwrite ------------------------------------------------------------


def test_the_command_will_not_overwrite_without_force(tmp_path, capsys):
    out = tmp_path / "plan.yaml"
    out.write_text("my hand-written metric work")
    args = ["import-plan", str(ROOT / "examples" / "current-tracking.csv"), "--id", "p",
            "--title", "T", "--identity-key", "player_id", "--out", str(out)]
    assert main(args) == 2
    assert out.read_text() == "my hand-written metric work"
    assert "already exists" in capsys.readouterr().err
    assert main([*args, "--force"]) == 0
    assert out.read_text().startswith("tracewright_plan_version")
