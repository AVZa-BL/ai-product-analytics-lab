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


def test_an_invalid_plan_is_a_plan_error_listing_everything(tmp_path):
    with pytest.raises(PlanError):
        import_plan_csv(csv(tmp_path, "a_b,p,uuid,,,,,,,\n"), **{**KW, "plan_id": "Bad Id"})


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
