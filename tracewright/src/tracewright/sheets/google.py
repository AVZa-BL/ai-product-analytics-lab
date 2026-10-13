"""Reading a Google Sheet. The only module in Tracewright that talks to Google.

Two ways in, chosen by what the person has:

* **A sheet shared by link** ("anyone with the link can view") is read through its CSV export
  address. No account, no token, no dependency. One tab per request, chosen by the `gid` in the URL.
* **A private sheet** is read through the Google Sheets API with an OAuth access token that the
  person supplies in the environment variable `GOOGLE_SHEETS_ACCESS_TOKEN`. The token is never a
  command-line argument (it would land in shell history), never printed, and never sent anywhere
  but `sheets.googleapis.com`. This path can list tabs and read several.

Only `https://docs.google.com/spreadsheets/...` addresses are accepted, and the requests are built
here from the sheet's id, so a crafted address cannot point the tool at another server. Redirects
are followed only inside Google's own domains, and never when a token is attached.

Nothing here could be run against a real Google account while it was written. The request and
response shapes follow Google's published API as the author knew it; the tests check them against
shapes the author wrote down, not against Google (one probe with a made-up token confirmed only
that the API answers a bad token with HTTP 401 and an error message). The first real use is the
real test.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPResponse

from tracewright.sheets.table import Table, TableError, read_csv_text, table_from_rows

TOKEN_VARIABLE = "GOOGLE_SHEETS_ACCESS_TOKEN"
MAX_BYTES = 5_000_000
MAX_TABS = 50
TIMEOUT_SECONDS = 30

DOCS_BASE = "https://docs.google.com"
API_BASE = "https://sheets.googleapis.com"

_SHEET_URL = re.compile(
    r"https://docs\.google\.com/spreadsheets/d/(?P<id>[A-Za-z0-9_-]{10,})"
    r"(?:/[^?#\s]*)?(?:\?(?P<query>[^#\s]*))?(?:#(?P<fragment>\S*))?"
)
_GID = re.compile(r"(?:^|[&?])gid=(\d+)(?:&|$)")


class SheetError(TableError):
    """A Google Sheet cannot be read. The message says what to try."""


@dataclass(frozen=True, kw_only=True)
class SheetRef:
    sheet_id: str
    gid: int | None  # the tab named in the address, if any


@dataclass(frozen=True, kw_only=True)
class Response:
    status: int
    url: str  # the address finally answered, after redirects
    content_type: str
    body: bytes


Fetch = Callable[[str, "dict[str, str]", bool], Response]


def is_sheet_source(text: str) -> bool:
    """Whether a command-line source is a web address (any scheme) and so not a file path."""
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text))


def parse_sheet_url(url: str) -> SheetRef:
    """The sheet id and tab of a Google Sheets address. Raises SheetError for anything else."""
    match = _SHEET_URL.fullmatch(url.strip())
    if not match:
        raise SheetError(
            f"{url!r} is not a Google Sheets address. Use the https://docs.google.com/spreadsheets/"
            "d/<id>/... address from your browser's address bar (only that form is accepted)"
        )
    gid = None
    for part in (match.group("query"), match.group("fragment")):
        if part and (found := _GID.search(part)):
            try:
                gid = int(found.group(1))
            except ValueError as error:  # more digits than a number may have
                raise SheetError("the gid in the address is not a tab number") from error
            break
    return SheetRef(sheet_id=match.group("id"), gid=gid)


# --- the network ---------------------------------------------------------------------------


def _google_host(host: str | None) -> bool:
    return bool(host) and (
        host in ("docs.google.com", "accounts.google.com")
        or host.endswith(".google.com")
        or host.endswith(".googleusercontent.com")
    )


class _SameFamilyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a Google host over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or not _google_host(target.hostname):
            raise SheetError(
                f"Google redirected to {target.hostname!r}, which is not a Google address; "
                "stopping"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Used whenever a token is attached: a redirect would carry it to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def default_fetch(url: str, headers: dict[str, str], follow_redirects: bool) -> Response:
    """GET one address. Reads at most MAX_BYTES; never follows a redirect out of Google."""
    handler = _SameFamilyRedirects() if follow_redirects else _NoRedirects()
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as reply:
            return _read(reply, reply.geturl(), reply.status)
    except urllib.error.HTTPError as error:
        try:
            return _read(error, error.geturl(), error.code)
        finally:
            error.close()
    except SheetError:
        raise
    except http.client.HTTPException as error:
        # A malformed or cut-off answer (IncompleteRead, BadStatusLine, LineTooLong, ...).
        raise SheetError(
            f"Google's answer was cut off or malformed ({type(error).__name__}); nothing was "
            "read. Try again"
        ) from error
    except urllib.error.URLError as error:
        raise SheetError(f"could not reach Google: {error.reason}") from error
    except TimeoutError as error:
        raise SheetError(f"Google did not answer within {TIMEOUT_SECONDS} seconds") from error
    except OSError as error:
        raise SheetError(f"could not reach Google: {error}") from error


def _read(reply: HTTPResponse | urllib.error.HTTPError, url: str, status: int) -> Response:
    body = reply.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise SheetError(f"the sheet is larger than {MAX_BYTES:,} bytes; the limit is a safeguard")
    # read(n) returns what arrived without complaint when the server closes early, so a download
    # cut short would otherwise be parsed as a complete, shorter sheet.
    promised = reply.headers.get("Content-Length", "")
    if promised.isdigit() and len(body) < int(promised):
        raise SheetError(
            "the download was cut short before the whole sheet arrived; nothing was read. "
            "Try again"
        )
    return Response(
        status=status, url=url, content_type=reply.headers.get("Content-Type", ""), body=body
    )


# --- public sheets: the CSV export ---------------------------------------------------------


def read_public_tab(ref: SheetRef, header_row: int = 1, fetch: Fetch | None = None) -> Table:
    """One tab of a link-shared sheet, through its CSV export address."""
    fetch = fetch or default_fetch
    query = {"format": "csv"}
    if ref.gid is not None:
        query["gid"] = str(ref.gid)
    url = f"{DOCS_BASE}/spreadsheets/d/{ref.sheet_id}/export?{urllib.parse.urlencode(query)}"
    label = _label(ref.gid)
    reply = fetch(url, {"Accept": "text/csv"}, True)
    host = urllib.parse.urlsplit(reply.url).hostname
    if host == "accounts.google.com" or reply.status in (401, 403):
        raise SheetError(_not_shared(label))
    if reply.status == 404:
        raise SheetError(f"{label}: Google says there is no such sheet (404). Check the address")
    if reply.status != 200:
        raise SheetError(f"{label}: Google answered HTTP {reply.status}")
    kind = reply.content_type.split(";")[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml"):
        raise SheetError(_not_shared(label))
    try:
        text = reply.body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SheetError(f"{label}: the export is not valid UTF-8 (byte {error.start})") from error
    if not text.strip():
        raise SheetError(f"{label} is empty")
    return read_csv_text(text, label, header_row)


def _not_shared(label: str) -> str:
    return (
        f"{label}: Google asked for a sign-in, so the sheet is not shared by link. Either share "
        "it as 'Anyone with the link: Viewer', or set the environment variable "
        f"{TOKEN_VARIABLE} to an access token so the Sheets API can read it, or download the tab "
        "as CSV and pass the file"
    )


def _label(gid: int | None, title: str | None = None) -> str:
    if title is not None:
        return f"Google Sheet, tab {title!r}"
    return "Google Sheet" + (f", tab gid={gid}" if gid is not None else " (first tab)")


# --- private sheets: the Sheets API with a token -------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Tab:
    gid: int
    title: str
    index: int


def _api_get(path: str, token: str, fetch: Fetch | None) -> dict:
    fetch = fetch or default_fetch
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    reply = fetch(f"{API_BASE}{path}", headers, False)
    if reply.status != 200:
        raise SheetError(_api_error(reply))
    try:
        data = json.loads(reply.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise SheetError("the Sheets API answered with something that is not JSON") from error
    if not isinstance(data, dict):
        raise SheetError("the Sheets API answered with an unexpected shape")
    return data


def _api_error(reply: Response) -> str:
    detail = ""
    try:
        error = json.loads(reply.body.decode("utf-8")).get("error", {})
        detail = str(error.get("message", ""))[:300]
    except (UnicodeDecodeError, ValueError, AttributeError):
        pass
    advice = {
        401: "the access token was refused or has expired (they last about an hour); get a new "
        f"one and set {TOKEN_VARIABLE} again",
        403: "the token's account cannot read this sheet, the token lacks the "
        "https://www.googleapis.com/auth/spreadsheets.readonly scope, or the Google Sheets API "
        "is not enabled for the token's project",
        404: "no such sheet, or the token's account has no access to it",
        429: "Google is rate limiting; wait a minute and try again",
    }.get(reply.status, "")
    shown = f" Google said: {detail!r}." if detail else ""
    return f"the Sheets API answered HTTP {reply.status}: {advice}.{shown}".replace(": .", ".")


def list_tabs(ref: SheetRef, token: str, fetch: Fetch | None = None) -> list[Tab]:
    data = _api_get(
        f"/v4/spreadsheets/{ref.sheet_id}?fields=sheets.properties(sheetId,title,index)",
        token,
        fetch,
    )
    tabs = []
    for sheet in data.get("sheets", []):
        props = sheet.get("properties", {}) if isinstance(sheet, dict) else {}
        if isinstance(props.get("sheetId"), int) and isinstance(props.get("title"), str):
            tabs.append(
                Tab(gid=props["sheetId"], title=props["title"], index=int(props.get("index", 0)))
            )
    tabs.sort(key=lambda tab: tab.index)
    if not tabs:
        raise SheetError("the sheet has no tabs the API could list")
    return tabs


def read_api_tab(
    ref: SheetRef, tab: Tab, token: str, header_row: int = 1, fetch: Fetch | None = None
) -> Table:
    quoted = "'" + tab.title.replace("'", "''") + "'"
    path = (
        f"/v4/spreadsheets/{ref.sheet_id}/values/{urllib.parse.quote(quoted, safe='')}"
        "?majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE"
    )
    data = _api_get(path, token, fetch)
    values = data.get("values", [])
    if not isinstance(values, list) or not all(isinstance(row, list) for row in values):
        raise SheetError("the Sheets API returned values in an unexpected shape")
    if not values:
        raise SheetError(f"{_label(tab.gid, tab.title)} is empty")
    if header_row <= len(values):
        # The API leaves out trailing empty cells, so a column that has data but no header text
        # makes the header row shorter than a data row. Pad it, as a CSV export already is.
        below = values[header_row:]
        widest = max((len(row) for row in below), default=0)
        header = values[header_row - 1]
        values[header_row - 1] = header + [""] * (widest - len(header))
    return table_from_rows(_label(tab.gid, tab.title), values, header_row)


def choose_tabs(
    ref: SheetRef, tabs: list[Tab], names: list[str], all_tabs: bool
) -> tuple[list[Tab], list[str]]:
    """The tabs to read and notices for the person. Raises SheetError for an unknown name."""
    if all_tabs:
        if len(tabs) > MAX_TABS:
            raise SheetError(
                f"--all-tabs would read {len(tabs)} tabs; the limit is {MAX_TABS}. "
                "Name the ones you need with --tab NAME"
            )
        return tabs, []
    if names:
        chosen = []
        for name in names:
            exact = [t for t in tabs if t.title == name]
            folded = [t for t in tabs if t.title.casefold() == name.casefold()]
            match = exact or (folded if len(folded) == 1 else [])
            if not match:
                titles = [t.title for t in tabs]
                raise SheetError(f"no tab named {name!r}; the sheet has {titles}")
            chosen.append(match[0])
        return chosen, []
    if ref.gid is not None:
        match = [t for t in tabs if t.gid == ref.gid]
        if not match:
            raise SheetError(f"the address names tab gid={ref.gid}, which the sheet does not have")
        return match, []
    first = tabs[0]
    others = [t.title for t in tabs[1:]]
    notes = []
    if others:
        listed = others if len(others) <= 5 else [*others[:5], f"... and {len(others) - 5} more"]
        notes.append(
            f"read only the first tab {first.title!r}; not read: {listed}. "
            "Use --tab NAME or --all-tabs"
        )
    return [first], notes


def read_google_sheet(
    url: str,
    *,
    tabs: list[str] | None = None,
    all_tabs: bool = False,
    header_row: int = 1,
    token: str | None = None,
    fetch: Fetch | None = None,
) -> tuple[list[Table], list[str]]:
    """Read a sheet. Returns the tables and notices for the person.

    `token` defaults to the environment variable. With a token the API is used (tabs can be listed
    and chosen); without one, the sheet must be shared by link and exactly one tab is read.
    """
    ref = parse_sheet_url(url)
    token = token if token is not None else os.environ.get(TOKEN_VARIABLE, "").strip() or None
    plain = bool(token) and token.isascii() and token.isprintable() and token.split() == [token]
    if token and not plain:
        # Never echo the value: it may be a mis-paste of something else secret.
        raise SheetError(
            f"{TOKEN_VARIABLE} does not look like an access token: it has a space, a line break "
            "or a character outside plain ASCII. Set it to the bare token (no 'Bearer ', no quotes)"
        )
    if token:
        try:
            found = list_tabs(ref, token, fetch)
            chosen, notes = choose_tabs(ref, found, tabs or [], all_tabs)
            return [read_api_tab(ref, t, token, header_row, fetch) for t in chosen], notes
        except SheetError as error:
            # Belt and braces: no message may carry the token, even if Google echoed it back.
            if len(token) >= 6 and token in str(error):
                raise SheetError(str(error).replace(token, "[token]")) from None
            raise
    if tabs or all_tabs:
        raise SheetError(
            f"--tab and --all-tabs need the Sheets API, which needs {TOKEN_VARIABLE}. Without a "
            "token a link-shared sheet is read one tab at a time: pass each tab's address "
            "(with #gid=...) as its own source"
        )
    table = read_public_tab(ref, header_row, fetch)
    notes = []
    if ref.gid is None:
        notes.append("no #gid in the address, so the sheet's first tab was read")
    return [table], notes
