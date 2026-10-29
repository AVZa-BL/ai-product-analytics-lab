"""The real Anthropic SDK, against a mocked HTTP transport: no network, no credentials.

These tests run the SDK's own request building, streaming parser and error classes, so what is
checked is how Specwright uses the SDK, not how it uses a stand-in for it. The model path has
never been run against the real API: that the API accepts the request (above all the output
schema) is not verified.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from specwright.draft import Draft
from specwright.proposers import DEFAULT_EFFORT, DEFAULT_MODEL, DRAFT_SCHEMA, AnthropicProposer
from specwright.request import DraftRequest, ProposerError
from tests.helpers import SHOP, documents, replay


def request() -> DraftRequest:
    return DraftRequest(documents=documents(SHOP))


def sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def message_events(text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5"):
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 1},
    }
    return [
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 345},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]


def make(handler, **kw) -> AnthropicProposer:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProposer(client=client, **kw)


def ok(events):
    return lambda req: httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=sse(events)
    )


def error(status: int, kind: str):
    body = {"type": "error", "error": {"type": kind, "message": "nope"}}
    return lambda req: httpx2.Response(status, json=body)


def test_a_successful_call_returns_the_text_the_model_and_the_usage() -> None:
    text = json.dumps(replay(SHOP))

    response = make(ok(message_events(text))).propose(request(), None)

    assert response.text == text and Draft.from_json(response.text)
    assert (response.model, response.usage) == (
        "claude-opus-5-5",
        {"input_tokens": 1200, "output_tokens": 345},
    )


def test_the_request_has_the_shape_the_api_expects_and_sends_nothing_the_models_reject() -> None:
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return ok(message_events("{}"))(req)

    make(handler).propose(request(), None)

    body = seen["body"]
    assert seen["url"].endswith("/v1/messages") and body["stream"] is True
    assert body["model"] == DEFAULT_MODEL and body["output_config"]["effort"] == DEFAULT_EFFORT
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": DRAFT_SCHEMA}
    assert "Specwright" in body["system"]
    for removed in ("temperature", "top_p", "top_k", "tools", "tool_choice", "thinking"):
        assert removed not in body  # no tools: the output is only ever parsed and checked
    assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
    assert any("Frontier Forge" in b.get("text", "") for b in body["messages"][0]["content"])


def test_model_and_effort_are_passed_through_and_an_unknown_effort_is_refused() -> None:
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return ok(message_events("{}"))(req)

    make(handler, model="claude-sonnet-5-5", effort="max").propose(request(), None)
    assert (seen["body"]["model"], seen["body"]["output_config"]["effort"]) == (
        "claude-sonnet-5-5",
        "max",
    )
    with pytest.raises(ProposerError, match="effort"):
        AnthropicProposer(effort="extreme")


@pytest.mark.parametrize(
    ("events", "message"),
    [
        (message_events('{"claims": [', stop_reason="max_tokens"), "output limit"),
        (message_events("   "), "no text"),
        (message_events("{", stop_reason="model_context_window_exceeded"), "context window"),
    ],
)
def test_an_unfinished_or_empty_response_is_an_error_and_never_a_draft(
    events, message: str
) -> None:
    with pytest.raises(ProposerError, match=message):
        make(ok(events)).propose(request(), None)


@pytest.mark.parametrize(
    ("status", "kind", "expected"),
    [
        (400, "invalid_request_error", "rejected the request"),
        (401, "authentication_error", "rejected the credentials"),
        (403, "permission_error", "denied"),
        (404, "not_found_error", "not found"),
        (429, "rate_limit_error", "rate limited"),
        (500, "api_error", "HTTP 500"),
    ],
)
def test_api_errors_become_actionable_messages(status: int, kind: str, expected: str) -> None:
    with pytest.raises(ProposerError, match=expected):
        make(error(status, kind)).propose(request(), None)


def test_a_connection_failure_before_and_during_the_response_is_reported() -> None:
    def refused(req):
        raise httpx2.ConnectError("no route", request=req)

    class Dropping(httpx2.SyncByteStream):
        def __iter__(self):
            yield sse(message_events("{")[:3])
            raise httpx2.ConnectError("connection lost")

    def drops(req):
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Dropping()
        )

    with pytest.raises(ProposerError, match="could not reach the API"):
        make(refused).propose(request(), None)
    with pytest.raises(ProposerError, match="connection failed while the response was arriving"):
        make(drops).propose(request(), None)


def test_a_refusal_reports_its_category_when_the_api_gives_one() -> None:
    message = SimpleNamespace(
        stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[]
    )

    with pytest.raises(ProposerError, match="cyber"):
        AnthropicProposer(client=object())._response(message)


def test_without_credentials_or_without_the_sdk_the_error_says_what_to_do(monkeypatch) -> None:
    with pytest.raises(ProposerError, match="no credentials found"):
        AnthropicProposer().propose(request(), None)

    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProposerError, match=r"pip install -e '\.\[llm\]'"):
        AnthropicProposer().propose(request(), None)
