"""The real Anthropic SDK, against a mocked HTTP transport: no network, no credentials.

These tests run the SDK's own request building, streaming parser and error classes, so what is
checked is how Tracewright uses the SDK, not how it uses a stand-in for it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from tests.propose_helpers import example_request, final_proposal
from tracewright.propose.proposal import PROPOSAL_SCHEMA, Proposal
from tracewright.propose.proposers import DEFAULT_EFFORT, DEFAULT_MODEL, AnthropicProposer
from tracewright.propose.request import ProposerError


def sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def message_events(text: str, *, stop_reason: str = "end_turn", model: str = "claude-opus-5-5"):
    return [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1", "type": "message", "role": "assistant", "model": model,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 1200, "output_tokens": 1},
                },
            },
        ),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 345}}),
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
    return lambda request: httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=sse(events)
    )


def error(status: int, kind: str, message: str = "nope"):
    body = {"type": "error", "error": {"type": kind, "message": message}}
    return lambda request: httpx2.Response(status, json=body)


def test_a_successful_call_returns_the_text_and_usage():
    text = json.dumps(final_proposal())
    response = make(ok(message_events(text))).propose(example_request(), None)
    assert response.text == text
    assert Proposal.from_dict(json.loads(response.text))
    assert response.model == "claude-opus-5-5"
    assert response.usage == {"input_tokens": 1200, "output_tokens": 345}


def test_the_request_has_the_shape_the_api_expects():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return ok(message_events("{}"))(request)

    make(handler).propose(example_request(), None)
    body = seen["body"]
    assert seen["url"].endswith("/v1/messages")
    assert body["model"] == DEFAULT_MODEL == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["max_tokens"] == 64_000
    assert body["output_config"]["effort"] == DEFAULT_EFFORT
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": PROPOSAL_SCHEMA}
    assert "Tracewright" in body["system"]
    # Settings the current models reject must not be sent.
    for removed in ("temperature", "top_p", "top_k", "tools", "tool_choice", "thinking"):
        assert removed not in body
    content = body["messages"][0]["content"]
    assert body["messages"][0]["role"] == "user" and len(body["messages"]) == 1
    assert any("Alliance Treasure Hunt" in b.get("text", "") for b in content)


def test_model_and_effort_are_passed_through():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok(message_events("{}"))(request)

    make(handler, model="claude-sonnet-5-5", effort="max").propose(example_request(), None)
    assert seen["body"]["model"] == "claude-sonnet-5-5"
    assert seen["body"]["output_config"]["effort"] == "max"


def test_an_unknown_effort_is_refused_before_any_call():
    with pytest.raises(ProposerError, match="effort"):
        AnthropicProposer(effort="extreme")


def test_a_refusal_is_an_error_not_a_proposal():
    with pytest.raises(ProposerError, match="declined"):
        make(ok(message_events("", stop_reason="refusal"))).propose(example_request(), None)


def test_a_truncated_response_is_an_error():
    with pytest.raises(ProposerError, match="output limit"):
        make(ok(message_events('{"feature": {', stop_reason="max_tokens"))).propose(
            example_request(), None
        )


def test_an_empty_response_is_an_error():
    with pytest.raises(ProposerError, match="no text"):
        make(ok(message_events("   "))).propose(example_request(), None)


@pytest.mark.parametrize(
    ("status", "kind", "expected"),
    [
        (401, "authentication_error", "credentials"),
        (403, "permission_error", "denied"),
        (404, "not_found_error", "not found"),
        (400, "invalid_request_error", "rejected the request"),
        (429, "rate_limit_error", "rate limited"),
        (500, "api_error", "HTTP 500"),
    ],
)
def test_api_errors_become_actionable_messages(status, kind, expected):
    with pytest.raises(ProposerError, match=expected):
        make(error(status, kind)).propose(example_request(), None)


def test_a_connection_failure_is_reported():
    def handler(request):
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ProposerError, match="could not reach the API"):
        make(handler).propose(example_request(), None)


def test_a_refusal_reports_its_category_when_the_api_gives_one():
    proposer = AnthropicProposer(client=object())
    message = SimpleNamespace(
        stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[]
    )
    with pytest.raises(ProposerError, match="cyber"):
        proposer._response(message)


def test_no_credentials_means_a_clear_error_not_a_crash(monkeypatch):
    # The transport fails the test if it is ever reached: with no credentials the SDK must stop
    # before sending anything, and if credentials do exist on this machine nothing real is called.
    def unreachable(request):
        pytest.fail("a request was sent")

    monkeypatch.setenv("HOME", "/nonexistent")
    client = anthropic.Anthropic(
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(unreachable)),
    )
    with pytest.raises(ProposerError, match="no credentials"):
        AnthropicProposer(client=client).propose(example_request(), None)


def test_an_unrelated_type_error_is_not_mistaken_for_missing_credentials():
    class Broken:
        class messages:  # noqa: N801
            @staticmethod
            def stream(**kwargs):
                raise TypeError("something else is wrong")

    with pytest.raises(TypeError, match="something else"):
        AnthropicProposer(client=Broken()).propose(example_request(), None)


# --- repair feedback and the shapes of real responses -------------------------------------------


def test_repair_feedback_reaches_the_request_the_sdk_sends():
    from tracewright.propose.request import Feedback

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok(message_events("{}"))(request)

    feedback = Feedback(previous_text='{"PREV": "MARK"}', problems=("[X] PROBLEM-MARK",))
    make(handler).propose(example_request(), feedback)
    sent = json.dumps(seen["body"]["messages"])
    assert "PREV" in sent and "PROBLEM-MARK" in sent
    assert "PROBLEM-MARK" not in json.dumps(
        AnthropicProposer(client=object()).request_body(example_request(), None)["messages"]
    )


def test_request_body_carries_feedback_without_an_http_round_trip():
    from tracewright.propose.request import Feedback

    body = AnthropicProposer(client=object()).request_body(
        example_request(), Feedback(previous_text="PREV-MARK", problems=("[X] prob-MARK",))
    )
    sent = json.dumps(body["messages"])
    assert "PREV-MARK" in sent and "prob-MARK" in sent


def test_a_thinking_block_before_the_text_is_ignored_and_text_blocks_are_joined():
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "thinking", "thinking": "",
                                                   "signature": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "thinking_delta", "thinking": "hmm"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "signature_delta", "signature": "sig"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "text_delta", "text": '{"a":'}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "text_delta", "text": " 1}"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 9}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    response = make(ok(events)).propose(example_request(), None)
    assert response.text == '{"a": 1}' and "hmm" not in response.text


@pytest.mark.parametrize(
    "stop_reason", ["model_context_window_exceeded", "pause_turn", "stop_sequence", "tool_use"]
)
def test_only_a_finished_answer_is_accepted(stop_reason):
    with pytest.raises(ProposerError, match="not a finished answer"):
        make(ok(message_events("{}", stop_reason=stop_reason))).propose(example_request(), None)


def test_a_context_window_cutoff_names_the_cause():
    with pytest.raises(ProposerError, match="context window"):
        make(ok(message_events("{", stop_reason="model_context_window_exceeded"))).propose(
            example_request(), None
        )


def test_a_stream_that_ends_without_a_stop_reason_is_not_a_proposal():
    events = [e for e in message_events("{}") if e[0] not in ("message_delta", "message_stop")]
    with pytest.raises(ProposerError, match="not a finished answer"):
        make(ok(events)).propose(example_request(), None)


@pytest.mark.parametrize(
    "failure",
    [httpx2.ReadError, httpx2.RemoteProtocolError, httpx2.ReadTimeout, httpx2.ConnectError],
)
def test_a_connection_that_drops_mid_stream_is_reported_not_a_crash(failure):
    class Dropping(httpx2.SyncByteStream):
        def __iter__(self):
            yield sse(message_events("{")[:3])
            raise failure("connection lost")

    def handler(request):
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Dropping()
        )

    with pytest.raises(ProposerError, match="connection failed while the response was arriving"):
        make(handler).propose(example_request(), None)


def test_a_missing_credential_profile_is_an_error_with_a_message_not_a_crash(monkeypatch):
    # No client is injected, so the proposer builds the SDK client itself, which is where a
    # selected-but-missing profile fails. Nothing is sent: the failure is before any request.
    monkeypatch.setenv("ANTHROPIC_PROFILE", "no-such-profile")
    with pytest.raises(ProposerError, match="Anthropic SDK reported an error"):
        AnthropicProposer().propose(example_request(), None)


def test_the_install_hint_names_a_command_that_works_from_the_checkout(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProposerError, match=r"pip install -e '\.\[llm\]'"):
        AnthropicProposer().propose(example_request(), None)
