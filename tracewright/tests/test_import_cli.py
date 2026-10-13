import json

import pytest

from tests.propose_helpers import prop
from tests.sheet_helpers import (
    SHEET_ID,
    SHEETS,
    URL,
    FakeGoogle,
    csv_reply,
    example,
    json_reply,
    tabs_reply,
)
from tracewright.cli import main
from tracewright.loader import load_plan

ARGS = ["--id", "game_core", "--title", "Game core", "--identity-key", "player_id"]
FLAT = str(SHEETS / "flat-rows.csv")
MERGED = str(SHEETS / "merged-cells.csv")
EXPORT = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
API = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"
TOKEN = "ya29.CLI-SECRET-TOKEN"


@pytest.fixture
def google(monkeypatch):
    """Replace the network with a fake, and make sure nothing else can be reached."""
    fake = FakeGoogle()
    monkeypatch.setattr("tracewright.sheets.google.default_fetch", fake)
    return fake


def run(capsys, *args):
    code = main(["import-plan", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


# --- files -------------------------------------------------------------------------------------


def test_a_real_looking_sheet_is_refused_at_first_with_the_way_forward(capsys):
    code, out, err = run(capsys, FLAT, *ARGS)
    assert code == 2 and out == ""
    assert "fit no meaning: J 'Jira', K 'Notes'" in err
    assert "--ignore-other-columns" in err and "--map NAME=HEADER" in err


def test_dry_run_shows_how_every_column_was_read_and_writes_nothing(capsys, tmp_path):
    out_file = tmp_path / "plan.yaml"
    code, out, err = run(capsys, FLAT, *ARGS, "--ignore-other-columns", "--dry-run",
                         "--out", str(out_file))
    assert code == 0 and not out_file.exists()
    assert "event <- column A 'Tracking Call'" in err and "ignored: J 'Jira', K 'Notes'" in err
    assert "dry run: would import 2 events, 6 properties; nothing written" in out


def test_the_flat_sheet_becomes_a_plan_that_reviews(capsys, tmp_path):
    plan_file = tmp_path / "plan.yaml"
    code, _, err = run(capsys, FLAT, *ARGS, "--ignore-other-columns", "--out", str(plan_file))
    assert code == 0 and "read 2 events, 6 properties" in err
    plan = load_plan(plan_file)
    assert [e.name for e in plan.events] == ["level_completed", "shop_opened"]
    assert main(["review-plan", str(plan_file)]) == 0


def test_the_merged_cell_sheet_needs_fill_down(capsys, tmp_path):
    code, _, err = run(capsys, MERGED, *ARGS)
    assert code == 2 and "--fill-down" in err
    plan_file = tmp_path / "plan.yaml"
    assert run(capsys, MERGED, *ARGS, "--fill-down", "--out", str(plan_file))[0] == 0
    assert {p.name for e in load_plan(plan_file).events for p in e.properties} >= {"contact_email"}


def test_map_names_a_column_the_aliases_would_not_find(capsys, tmp_path):
    csv = tmp_path / "signals.csv"
    csv.write_text("Signal,Arg,Kind\nlevel_done,player_id,string\n", encoding="utf-8")
    code, _, err = run(capsys, str(csv), *ARGS)
    assert code == 2 and "no column looks like the event name" in err
    code, out, err = run(capsys, str(csv), *ARGS, "--map", "event=Signal", "--map",
                         "property=Arg", "--map", "type=Kind")
    assert code == 0 and "event <- column A 'Signal'" in err and "level_done" in out


def test_bad_options_are_usage_errors_not_crashes(capsys):
    for bad in (["--map", "colour=Name"], ["--map", "oops"], ["--type-map", "Currency=money"],
                ["--status-map", "Blocked"], ["--header-row", "0"]):
        code, _, err = run(capsys, FLAT, *ARGS, "--ignore-other-columns", *bad)
        assert code == 2 and "Traceback" not in err, bad


def test_tab_options_are_for_google_sheets_only(capsys):
    code, _, err = run(capsys, FLAT, *ARGS, "--tab", "Events")
    assert code == 2 and "are for Google Sheets" in err


def test_a_plan_level_problem_is_reported_by_field(capsys):
    code, _, err = run(capsys, FLAT, "--id", "Bad Id", "--title", "T",
                       "--identity-key", "player_id", "--ignore-other-columns")
    assert code == 2 and "id:" in err and "is not a valid tracking plan" in err


# --- Google Sheets addresses ----------------------------------------------------------------------


def test_a_public_sheet_is_read_and_imported(capsys, google):
    google.routes[EXPORT] = csv_reply(example("merged-cells.csv"), url=EXPORT)
    code, out, err = run(capsys, f"{URL}#gid=0", *ARGS, "--fill-down")
    assert code == 0 and "shop_opened" in out
    assert "Google Sheet, tab gid=0" in err and "event <- column A 'Event Name'" in err
    assert google.calls[0][0] == f"{EXPORT}?format=csv&gid=0"


def test_a_private_sheet_is_read_with_the_token_from_the_environment(capsys, google, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", TOKEN)
    rows = [r.split(",") for r in "Event,Property,Type\nlevel_done,player_id,string\n".splitlines()]
    google.routes[f"{API}?fields="] = tabs_reply("Events", "Notes")
    google.routes[f"{API}/values/"] = json_reply({"values": rows})
    code, out, err = run(capsys, URL, *ARGS)
    assert code == 0 and "level_done" in out
    assert "read only the first tab 'Events'" in err
    assert TOKEN not in out and TOKEN not in err


def test_several_sources_are_merged(capsys, google, monkeypatch):
    google.routes[EXPORT] = csv_reply("Event,Property\nshop_opened,item_id\n")
    code, out, _ = run(capsys, FLAT, URL, *ARGS, "--ignore-other-columns")
    assert code == 0 and out.count("- name: shop_opened") == 1  # merged into one event
    assert "name: item_id" in out and "- name: level_completed" in out
    # ...and a property both sources declare is caught, with the source named
    google.routes[EXPORT] = csv_reply("Event,Property\nshop_opened,player_id\n")
    code, _, err = run(capsys, FLAT, URL, *ARGS, "--ignore-other-columns")
    assert code == 2 and "Google Sheet (first tab), row 2: property 'player_id'" in err


def test_google_failures_are_exit_2_with_advice_and_never_a_traceback(capsys, google):
    google.routes[EXPORT] = csv_reply("", status=403)
    code, _, err = run(capsys, URL, *ARGS)
    assert code == 2 and "not shared by link" in err and "GOOGLE_SHEETS_ACCESS_TOKEN" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("source", ["http://docs.google.com/spreadsheets/d/" + SHEET_ID,
                                    "file:///etc/passwd", "https://example.com/sheet.csv",
                                    "ftp://x/y.csv"])
def test_other_addresses_are_refused_without_any_request(capsys, google, source):
    code, _, err = run(capsys, source, *ARGS)
    assert code == 2 and "not a Google Sheets address" in err and google.calls == []


def test_an_expired_token_says_so_and_does_not_print_it(capsys, google, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", TOKEN)
    google.routes[API] = json_reply({"error": {"message": f"Invalid token {TOKEN}"}}, status=401)
    code, _, err = run(capsys, URL, *ARGS)
    assert code == 2 and "expired" in err and TOKEN not in err


# --- the whole chain: a sheet, a plan, a proposal ---------------------------------------------


def test_sheet_to_plan_to_proposal(capsys, google, tmp_path):
    """The workflow this was built for, with the model replaced by a saved answer."""
    google.routes[EXPORT] = csv_reply(example("merged-cells.csv"))
    plan_file = tmp_path / "plan.yaml"
    assert run(capsys, f"{URL}#gid=0", *ARGS, "--fill-down", "--out", str(plan_file))[0] == 0

    gdd = tmp_path / "gdd.md"
    gdd.write_text("Players can redeem a daily gift from the shop screen.\n", encoding="utf-8")
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({
        "feature": {"id": "daily_gift", "name": "Daily gift", "summary": "A gift in the shop."},
        "identity_keys": [],
        "new_events": [{
            "name": "daily_gift_redeemed", "description": "A player redeems the gift.",
            "trigger": "The server confirms the redemption.", "priority": "must",
            "rationale": "Measures redemption.",
            "evidence": {"kind": "document", "document": "gdd.md",
                         "quote": "Players can redeem a daily gift from the shop screen."},
            "properties": [prop("player_id", required=True, reuses_existing=True)],
        }],
        "extended_events": [], "reused_events": [{"name": "shop_opened", "rationale": "Entry."}],
        "metrics": [{"name": "gift_use", "definition": "Redemptions per shop open.",
                     "events": ["daily_gift_redeemed", "shop_opened"], "rationale": "Adoption."}],
        "not_tracked": [], "assumptions": [], "open_questions": [],
    }), encoding="utf-8")
    out_dir = tmp_path / "out"
    code = main(["propose", "--doc", str(gdd), "--plan", str(plan_file), "--replay", str(replay),
                 "--owner", "game-analytics", "--out", str(out_dir)])
    capsys.readouterr()
    assert code == 0
    merged = load_plan(out_dir / "merged-plan.yaml")
    names = {e.name for e in merged.events}
    assert {"shop_opened", "purchase_made", "daily_gift_redeemed"} <= names


# --- what the dry run shows, and the ways out ---------------------------------------------------


def test_dry_run_shows_how_each_event_and_property_was_read(capsys):
    code, out, _ = run(capsys, FLAT, *ARGS, "--ignore-other-columns", "--dry-run")
    assert code == 0
    assert "how the cells were read (name:type, * required, ! personal data):" in out
    assert "  level_completed (active): player_id:string*, level_id:string*, stars:integer," in out
    assert "difficulty:enum[easy|normal|hard]" in out
    assert "  shop_opened (planned):" in out  # "To do" read as planned


def test_a_list_type_stops_the_import_and_a_dry_run_shows_the_same_problem(capsys, tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text("Event,Property,Type\nlevel_done,item_ids,string[]\n", encoding="utf-8")
    for extra in ([], ["--dry-run"]):
        code, _, err = run(capsys, str(sheet), *ARGS, *extra)
        assert code == 2 and "row 2: 'string[]' is a list" in err and "--type-map" in err
    code, out, _ = run(capsys, str(sheet), *ARGS, "--type-map", "string[]=string", "--dry-run")
    assert code == 0 and "item_ids:string" in out


def test_notes_about_status_and_banner_rows_reach_the_person(capsys, tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text(
        "Event,Property,Status\n=== MONETISATION ===,,\nshop_opened,player_id,To do\n"
        "shop_closed,player_id,\n", encoding="utf-8")
    code, _, err = run(capsys, str(sheet), *ARGS, "--dry-run")
    assert code == 0
    assert "status: no status cell for 2 event(s): '=== MONETISATION ===', 'shop_closed'" in err
    assert "have no properties and nothing else: '=== MONETISATION ==='" in err


def test_ignore_column_and_a_column_letter_work_from_the_command_line(capsys, tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text(
        "Event,Description,Property,Type,Description\na_b,about event,p,string,about p\n",
        encoding="utf-8")
    code, _, err = run(capsys, str(sheet), *ARGS)
    assert code == 2 and "--map description=@B" in err and "--ignore-column @E" in err
    code, out, _ = run(
        capsys, str(sheet), *ARGS, "--map", "description=@E", "--ignore-column", "@B"
    )
    assert code == 0 and "description: about p" in out


def test_a_malformed_token_is_a_clear_error_and_never_shown(capsys, google, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "ya29.SECRET\nSECOND-LINE")
    code, out, err = run(capsys, URL, *ARGS)
    assert code == 2 and "does not look like an access token" in err
    assert "SECRET" not in out + err and "Traceback" not in err and google.calls == []
