import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.sheet_helpers import (
    SHEET_ID,
    URL,
    FakeGoogle,
    csv_reply,
    json_reply,
    tabs_reply,
)
from tracewright.sheets import google
from tracewright.sheets.google import (
    Response,
    SheetError,
    default_fetch,
    is_sheet_source,
    parse_sheet_url,
    read_google_sheet,
)

CSV = "Event,Property,Type\nlevel_done,player_id,string\n"
TOKEN = "ya29.A0-SECRET-TOKEN-VALUE"
EXPORT = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
API = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}"


# --- addresses ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "gid"),
    [
        (URL, None),
        (f"{URL}#gid=0", 0),
        (f"{URL}?gid=123#gid=5", 123),
        (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing&gid=77", 77),
        (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}", None),
        (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=4567890123", 4567890123),
    ],
)
def test_sheet_addresses(url, gid):
    ref = parse_sheet_url(url)
    assert ref.sheet_id == SHEET_ID and ref.gid == gid


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.google.com/spreadsheets/d/" + SHEET_ID,
        "https://evil.example/spreadsheets/d/" + SHEET_ID,
        "https://docs.google.com.evil.example/spreadsheets/d/" + SHEET_ID,
        "https://docs.google.com/document/d/" + SHEET_ID,
        "https://docs.google.com/spreadsheets/d/short",
        "https://user@docs.google.com/spreadsheets/d/" + SHEET_ID,
        "file:///etc/passwd",
        "https://docs.google.com/spreadsheets/d/" + SHEET_ID + "/../../x\nHost: evil",
    ],
)
def test_anything_but_a_google_sheets_address_is_refused(url):
    with pytest.raises(SheetError, match="not a Google Sheets address"):
        parse_sheet_url(url)


def test_a_source_is_a_web_address_when_it_has_a_scheme():
    assert is_sheet_source("https://x") and is_sheet_source("http://x") and is_sheet_source("file:///x")
    assert not is_sheet_source("plan.csv") and not is_sheet_source("C:\\sheets\\plan.csv")


# --- a sheet shared by link -------------------------------------------------------------------


def test_a_public_tab_is_read_from_the_export_address():
    fake = FakeGoogle({EXPORT: csv_reply(CSV, url=EXPORT)})
    tables, notes = read_google_sheet(f"{URL}#gid=42", fetch=fake)
    assert len(tables) == 1 and tables[0].header == ("Event", "Property", "Type")
    assert tables[0].rows[0] == (2, ("level_done", "player_id", "string"))
    url, headers, follow = fake.calls[0]
    assert url == f"{EXPORT}?format=csv&gid=42" and follow is True
    assert "Authorization" not in headers and notes == []


def test_without_a_gid_the_first_tab_is_read_and_the_person_is_told():
    fake = FakeGoogle({EXPORT: csv_reply(CSV)})
    _, notes = read_google_sheet(URL, fetch=fake)
    assert fake.calls[0][0] == f"{EXPORT}?format=csv"
    assert notes == ["no #gid in the address, so the sheet's first tab was read"]


def test_the_header_row_applies_to_a_public_tab():
    fake = FakeGoogle({EXPORT: csv_reply("Title\n\n" + CSV)})
    (table,), _ = read_google_sheet(URL, header_row=3, fetch=fake)
    assert table.header[0] == "Event" and table.rows[0][0] == 4


@pytest.mark.parametrize(
    "reply",
    [
        Response(status=200, url="https://accounts.google.com/ServiceLogin",
                 content_type="text/html", body=b"<html>"),
        Response(status=200, url=EXPORT, content_type="text/html; charset=utf-8", body=b"<html>"),
        Response(status=403, url=EXPORT, content_type="text/html", body=b""),
        Response(status=401, url=EXPORT, content_type="", body=b""),
    ],
)
def test_a_sheet_that_asks_for_a_sign_in_says_how_to_share_or_authorise(reply):
    with pytest.raises(SheetError) as caught:
        read_google_sheet(URL, fetch=FakeGoogle({EXPORT: reply}))
    message = str(caught.value)
    assert "not shared by link" in message and "GOOGLE_SHEETS_ACCESS_TOKEN" in message


def test_a_missing_sheet_and_other_failures():
    with pytest.raises(SheetError, match="no such sheet"):
        read_google_sheet(URL, fetch=FakeGoogle({EXPORT: csv_reply("", status=404)}))
    with pytest.raises(SheetError, match="HTTP 500"):
        read_google_sheet(URL, fetch=FakeGoogle({EXPORT: csv_reply("", status=500)}))


def test_an_export_that_is_not_utf8_is_refused():
    reply = Response(status=200, url=EXPORT, content_type="text/csv", body=b"\xff\xfe\x00")
    with pytest.raises(SheetError, match="not valid UTF-8"):
        read_google_sheet(URL, fetch=FakeGoogle({EXPORT: reply}))


def test_tab_options_need_the_api_and_the_message_says_what_to_do_instead():
    for options in ({"tabs": ["Events"]}, {"all_tabs": True}):
        with pytest.raises(SheetError, match="each tab's address"):
            read_google_sheet(URL, fetch=FakeGoogle(), **options)


# --- a private sheet, through the API ----------------------------------------------------------


def api_fake(values, *titles):
    return FakeGoogle({
        f"{API}?fields=": tabs_reply(*titles),
        f"{API}/values/": json_reply({"range": "x", "majorDimension": "ROWS", "values": values}),
    })


def test_the_api_path_reads_the_first_tab_and_lists_the_others(monkeypatch):
    fake = api_fake([["Event", "Property"], ["a_b", "p"]], "Events", "Notes")
    (table,), notes = read_google_sheet(URL, token=TOKEN, fetch=fake)
    assert table.header == ("Event", "Property") and table.rows == ((2, ("a_b", "p")),)
    assert table.label == "Google Sheet, tab 'Events'"
    assert any("read only the first tab 'Events'" in n and "Notes" in n for n in notes)


def test_the_requests_have_the_shape_the_api_documents():
    fake = api_fake([["Event"]], "Events")
    read_google_sheet(URL, token=TOKEN, fetch=fake)
    (tabs_url, tabs_headers, tabs_follow), (values_url, _, values_follow) = fake.calls
    assert tabs_url == f"{API}?fields=sheets.properties(sheetId,title,index)"
    assert tabs_headers["Authorization"] == f"Bearer {TOKEN}"
    assert values_url.startswith(f"{API}/values/%27Events%27?majorDimension=ROWS")
    assert tabs_follow is False and values_follow is False  # a token never follows a redirect


def test_a_tab_title_with_an_apostrophe_or_slash_is_quoted_and_encoded():
    fake = api_fake([["Event"]], "Tom's / Events")
    read_google_sheet(URL, token=TOKEN, fetch=fake)
    assert "/values/%27Tom%27%27s%20%2F%20Events%27?" in fake.calls[1][0]


def test_rows_the_api_returns_short_are_fine():
    fake = api_fake([["Event", "Property", "Type"], ["a_b"], [], ["c_d", "q", "string"]], "T")
    (table,), _ = read_google_sheet(URL, token=TOKEN, fetch=fake)
    assert table.rows == ((2, ("a_b",)), (3, ()), (4, ("c_d", "q", "string")))


def test_a_sheet_with_no_values_gives_a_clear_error_not_a_crash():
    fake = FakeGoogle({f"{API}?fields=": tabs_reply("T"), f"{API}/values/": json_reply({})})
    with pytest.raises(SheetError, match="tab 'T' is empty"):
        read_google_sheet(URL, token=TOKEN, fetch=fake)


def test_the_token_comes_from_the_environment_variable(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", f"  {TOKEN}\n")
    fake = api_fake([["Event"]], "T")
    read_google_sheet(URL, fetch=fake)
    assert fake.calls[0][1]["Authorization"] == f"Bearer {TOKEN}"


def test_an_empty_variable_means_no_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "   ")
    fake = FakeGoogle({EXPORT: csv_reply(CSV)})
    read_google_sheet(URL, fetch=fake)
    assert fake.calls[0][0].startswith(EXPORT)


@pytest.mark.parametrize(
    ("names", "all_tabs", "gid", "expected"),
    [
        ([], True, None, ["Events", "Notes", "Old"]),
        (["Notes"], False, None, ["Notes"]),
        (["notes"], False, None, ["Notes"]),
        (["Old", "Events"], False, None, ["Old", "Events"]),
        ([], False, 101, ["Notes"]),
    ],
)
def test_tab_selection(names, all_tabs, gid, expected):
    fake = api_fake([["Event"]], "Events", "Notes", "Old")
    url = URL + (f"#gid={gid}" if gid is not None else "")
    tables, _ = read_google_sheet(url, tabs=names, all_tabs=all_tabs, token=TOKEN, fetch=fake)
    assert [t.label for t in tables] == [f"Google Sheet, tab {e!r}" for e in expected]


def test_an_unknown_tab_lists_the_tabs_the_sheet_has():
    expected = r"no tab named 'Nope'; the sheet has \['Events', 'Notes'\]"
    with pytest.raises(SheetError, match=expected):
        read_google_sheet(URL, tabs=["Nope"], token=TOKEN, fetch=api_fake([], "Events", "Notes"))
    with pytest.raises(SheetError, match="gid=999"):
        read_google_sheet(f"{URL}#gid=999", token=TOKEN, fetch=api_fake([], "Events"))


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "expired"), (403, "spreadsheets.readonly"), (404, "no access"), (429, "rate limiting"),
     (500, "HTTP 500")],
)
def test_api_errors_say_what_to_try_and_never_show_the_token(status, expected):
    body = {"error": {"code": status, "message": "The caller does not have permission"}}
    fake = FakeGoogle({API: json_reply(body, status=status)})
    with pytest.raises(SheetError) as caught:
        read_google_sheet(URL, token=TOKEN, fetch=fake)
    message = str(caught.value)
    assert expected in message and TOKEN not in message
    if status == 403:
        assert "does not have permission" in message


def test_an_api_answer_that_is_not_json_or_has_the_wrong_shape():
    for reply in (Response(status=200, url="", content_type="text/html", body=b"<html>"),
                  json_reply([1, 2]), json_reply({"sheets": []})):
        with pytest.raises(SheetError):
            read_google_sheet(URL, token=TOKEN, fetch=FakeGoogle({API: reply}))
    bad_values = FakeGoogle({f"{API}?fields=": tabs_reply("T"),
                             f"{API}/values/": json_reply({"values": ["not a row"]})})
    with pytest.raises(SheetError, match="unexpected shape"):
        read_google_sheet(URL, token=TOKEN, fetch=bad_values)


def many_tabs_fake(count):
    titles = [f"T{i}" for i in range(count)]
    return FakeGoogle({f"{API}?fields=": tabs_reply(*titles),
                       f"{API}/values/": json_reply({"values": [["Event"]]})})


def test_all_tabs_over_the_limit_is_refused_and_says_to_name_the_ones_needed():
    with pytest.raises(SheetError, match=r"--all-tabs would read 51 tabs; the limit is 50.*--tab"):
        read_google_sheet(URL, all_tabs=True, token=TOKEN, fetch=many_tabs_fake(51))


def test_a_sheet_with_many_tabs_is_fine_when_one_is_named_or_the_first_is_wanted():
    fake = many_tabs_fake(60)
    (named,), _ = read_google_sheet(URL, tabs=["T7"], token=TOKEN, fetch=fake)
    assert named.label == "Google Sheet, tab 'T7'"
    (by_gid,), _ = read_google_sheet(f"{URL}#gid=107", token=TOKEN, fetch=many_tabs_fake(60))
    assert by_gid.label == "Google Sheet, tab 'T7'"
    (first,), notes = read_google_sheet(URL, token=TOKEN, fetch=many_tabs_fake(60))
    assert first.label == "Google Sheet, tab 'T0'" and "and 54 more" in notes[0]


def test_a_header_row_shorter_than_a_data_row_is_padded_on_the_api_path():
    # The API leaves out trailing empty cells, so a column with data but no header text makes the
    # header shorter than a data row. A CSV export is rectangular; the API path must match it.
    fake = api_fake([["Event", "Property", "Type"], ["a_b", "p", "string", "a note"]], "T")
    (table,), _ = read_google_sheet(URL, token=TOKEN, fetch=fake)
    assert table.header == ("Event", "Property", "Type", "")
    assert table.rows == ((2, ("a_b", "p", "string", "a note")),)


def test_padding_uses_only_rows_below_the_header():
    wide_title = ["a", "b", "c", "d", "e", "f"]
    fake = api_fake([wide_title, ["Event", "Property"], ["a_b", "p"]], "T")
    (table,), _ = read_google_sheet(URL, header_row=2, token=TOKEN, fetch=fake)
    assert table.header == ("Event", "Property")


def test_an_empty_link_shared_tab_says_it_is_empty_not_that_the_header_row_is_wrong():
    with pytest.raises(SheetError, match="is empty"):
        read_google_sheet(URL, fetch=FakeGoogle({EXPORT: csv_reply("\n  \n")}))


def test_a_gid_with_absurdly_many_digits_is_a_clear_error():
    with pytest.raises(SheetError, match="not a tab number"):
        parse_sheet_url(f"{URL}#gid={'9' * 5000}")


# --- the token is checked before it is used, and the check never shows it -----------------------


@pytest.mark.parametrize(
    "bad",
    ["ya29.line\nbreak", "ya29.line\rbreak", "has space", "Bearer ya29.abc",
     "\u201cya29.quoted\u201d", "ya29.\u200bzero-width", "tab\there"],
)
def test_a_token_that_cannot_be_a_token_is_refused_without_echoing_it(bad, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", bad)
    fake = FakeGoogle()
    with pytest.raises(SheetError) as caught:
        read_google_sheet(URL, fetch=fake)
    message = str(caught.value)
    assert "does not look like an access token" in message
    assert bad not in message and "ya29" not in message  # the value is never shown
    assert fake.calls == []  # nothing was sent


def test_a_realistic_token_is_accepted():
    fake = api_fake([["Event"]], "T")
    realistic = "ya29.a0AfH6SMB-x_y.z~1/2+3=ABCdef"
    read_google_sheet(URL, token=realistic, fetch=fake)
    assert fake.calls[0][1]["Authorization"] == f"Bearer {realistic}"


# --- the real network code, against a server on this machine ----------------------------------


class Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *args):  # noqa: D401 - silence the test server
        pass

    def do_GET(self):  # noqa: N802
        Handler.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
        if self.path.startswith("/redirect-out"):
            self.send_response(302)
            self.send_header("Location", "https://evil.example/steal")
            self.end_headers()
        elif self.path.startswith("/redirect-http"):
            self.send_response(302)
            self.send_header("Location", "http://docs.google.com/x")
            self.end_headers()
        elif self.path.startswith("/big"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            self.wfile.write(b"x" * (google.MAX_BYTES + 10))
        elif self.path.startswith("/short"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"Event\na\n")  # promises 100 bytes, sends 8, closes
        elif self.path.startswith("/chunk-cut"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"5\r\nEvent\r\n20\r\nonly part of this chunk")  # then closes
        elif self.path.startswith("/denied"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "nope"}}')
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Event\na\n")


@pytest.fixture
def server():
    Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    thread.join(timeout=5)


def test_a_normal_answer_is_read(server):
    reply = default_fetch(f"{server}/ok", {"Accept": "text/csv"}, True)
    assert (reply.status, reply.body) == (200, b"Event\na\n")
    assert reply.content_type.startswith("text/csv")


def test_an_error_status_is_returned_not_raised(server):
    reply = default_fetch(f"{server}/denied", {}, False)
    assert reply.status == 403 and b"nope" in reply.body


def test_a_redirect_out_of_google_is_refused(server):
    with pytest.raises(SheetError, match="not a Google address"):
        default_fetch(f"{server}/redirect-out", {}, True)
    with pytest.raises(SheetError, match="not a Google address"):
        default_fetch(f"{server}/redirect-http", {}, True)


def test_with_a_token_no_redirect_is_followed_so_it_cannot_travel(server):
    reply = default_fetch(f"{server}/redirect-out", {"Authorization": f"Bearer {TOKEN}"}, False)
    assert reply.status == 302
    assert [s["path"] for s in Handler.seen] == ["/redirect-out"]  # only the first request was made


def test_an_answer_larger_than_the_limit_is_refused(server):
    with pytest.raises(SheetError, match="larger than"):
        default_fetch(f"{server}/big", {}, True)


def test_a_connection_that_cannot_be_made_is_a_clear_error():
    with pytest.raises(SheetError, match="could not reach Google"):
        default_fetch("http://127.0.0.1:9/", {}, True)  # nothing listens on the discard port


@pytest.mark.parametrize(
    ("target", "allowed"),
    [
        ("https://docs.google.com/spreadsheets/d/x/export", True),
        ("https://doc-0k-9c-sheets.googleusercontent.com/export/abc", True),
        ("https://accounts.google.com/ServiceLogin", True),
        ("https://evil.example/x", False),
        ("http://docs.google.com/x", False),
        ("https://docs.google.com.evil.example/x", False),
        ("https://notgoogle.com/x", False),
        ("https://google.com.evil.example/x", False),
    ],
)
def test_the_redirect_policy(target, allowed):
    handler = google._SameFamilyRedirects()
    request = urllib.request.Request("https://docs.google.com/start")
    headers = {}
    if allowed:
        assert handler.redirect_request(request, None, 302, "Found", headers, target) is not None
    else:
        with pytest.raises(SheetError):
            handler.redirect_request(request, None, 302, "Found", headers, target)


def test_the_token_is_never_in_an_error_message_for_any_failure():
    messages = []
    for reply in (json_reply({"error": {"message": "x"}}, status=401),
                  json_reply({"error": {"message": f"bad token {TOKEN}"}}, status=403),
                  json_reply("x", status=200)):
        try:
            read_google_sheet(URL, token=TOKEN, fetch=FakeGoogle({API: reply}))
        except SheetError as error:
            messages.append(str(error))
    assert len(messages) == 3 and not any(TOKEN in m for m in messages)
    assert "[token]" in messages[1]  # Google echoed it; it was scrubbed


def test_a_download_cut_short_is_not_taken_for_the_whole_sheet(server):
    with pytest.raises(SheetError, match="cut short"):
        default_fetch(f"{server}/short", {}, True)


def test_a_malformed_or_cut_off_answer_is_a_clear_error_not_a_traceback(server):
    with pytest.raises(SheetError, match="cut off or malformed"):
        default_fetch(f"{server}/chunk-cut", {}, True)


def test_the_token_is_sent_with_a_token_request_and_with_no_other(server):
    default_fetch(f"{server}/ok", {"Authorization": f"Bearer {TOKEN}"}, False)
    default_fetch(f"{server}/ok", {"Accept": "text/csv"}, True)
    assert [seen["auth"] for seen in Handler.seen] == [f"Bearer {TOKEN}", None]
