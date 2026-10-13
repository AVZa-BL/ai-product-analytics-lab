"""Helpers shared by the tests that read spreadsheets."""

from __future__ import annotations

import json
from pathlib import Path

from tracewright.sheets.google import Response
from tracewright.sheets.table import Table, read_csv_text

SHEETS = Path(__file__).resolve().parent.parent / "examples" / "google-sheets"
SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-aBcD"
URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
KW = {"plan_id": "p", "title": "P", "identity_keys": ["player_id"]}


def table(text: str, *, header_row: int = 1, label: str = "sheet") -> Table:
    return read_csv_text(text, label, header_row)


def example(name: str) -> str:
    return (SHEETS / name).read_text(encoding="utf-8")


class FakeGoogle:
    """A stand-in for the network: answers by address and records every request."""

    def __init__(self, routes: dict[str, Response] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, dict[str, str], bool]] = []

    def __call__(self, url: str, headers: dict[str, str], follow_redirects: bool) -> Response:
        self.calls.append((url, dict(headers), follow_redirects))
        for prefix, reply in self.routes.items():
            if url.startswith(prefix):
                return reply
        raise AssertionError(f"unexpected request to {url}")


def csv_reply(text: str, *, url: str = "", status: int = 200) -> Response:
    return Response(status=status, url=url, content_type="text/csv; charset=utf-8",
                    body=text.encode("utf-8"))


def json_reply(data: object, *, status: int = 200) -> Response:
    return Response(status=status, url="", content_type="application/json; charset=UTF-8",
                    body=json.dumps(data).encode("utf-8"))


def tabs_reply(*titles: str) -> Response:
    return json_reply({"sheets": [
        {"properties": {"sheetId": 100 + i, "title": t, "index": i}} for i, t in enumerate(titles)
    ]})
