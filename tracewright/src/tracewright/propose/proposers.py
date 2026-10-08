"""The proposers: the real model call, and a replay of canned responses for offline use.

Both implement `propose(request, feedback) -> ProposerResponse` and nothing else, so the checks and
the repair loop never depend on which one produced the text.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from tracewright.propose.prompt import system_prompt, user_content
from tracewright.propose.proposal import PROPOSAL_SCHEMA
from tracewright.propose.request import (
    Feedback,
    ProposalRequest,
    ProposerError,
    ProposerResponse,
)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MAX_OUTPUT_TOKENS = 64_000


def _sdk() -> Any:
    try:
        import anthropic
    except ImportError as error:
        raise ProposerError(
            "the anthropic package is not installed; run: pip install 'tracewright[llm]'"
        ) from error
    return anthropic


class Proposer(Protocol):
    def propose(
        self, request: ProposalRequest, feedback: Feedback | None
    ) -> ProposerResponse: ...


class ReplayProposer:
    """Returns canned responses in order. No model is called.

    For tests, demos and CI. A replay file is a JSON object (one attempt) or a JSON list of
    objects (successive attempts, so a repair round can be shown).
    """

    def __init__(self, responses: Sequence[str | dict[str, Any]]) -> None:
        self._responses = [
            r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in responses
        ]
        self._next = 0

    @classmethod
    def from_file(cls, path: str | Path) -> ReplayProposer:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProposerError(f"{path}: cannot be read as a replay file: {error}") from error
        items = data if isinstance(data, list) else [data]
        if not items or not all(isinstance(item, dict) for item in items):
            raise ProposerError(f"{path}: a replay file is a JSON object or a list of objects")
        return cls(items)

    def propose(
        self, request: ProposalRequest, feedback: Feedback | None
    ) -> ProposerResponse:
        if self._next >= len(self._responses):
            raise ProposerError(
                f"the replay has only {len(self._responses)} response(s), but another was needed"
            )
        text = self._responses[self._next]
        self._next += 1
        return ProposerResponse(text=text, model="replay")


class AnthropicProposer:
    """Calls Claude through the official SDK, streaming, with a JSON-schema output.

    Credentials come from the environment the way the SDK resolves them (ANTHROPIC_API_KEY, or a
    profile from `ant auth login`); a key is never taken as an argument or written anywhere.
    The model has no tools. Thinking is left at the model's own setting (adaptive) and depth is
    controlled by `effort`.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = MAX_OUTPUT_TOKENS,
        client: Any = None,
    ) -> None:
        if effort not in EFFORTS:
            raise ProposerError(f"effort must be one of {list(EFFORTS)}, got {effort!r}")
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _sdk().Anthropic()
        return self._client

    def request_body(
        self, request: ProposalRequest, feedback: Feedback | None
    ) -> dict[str, Any]:
        """The exact arguments of the API call. Public so tests can inspect them."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt(),
            "messages": [{"role": "user", "content": user_content(request, feedback)}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA},
            },
        }

    def propose(
        self, request: ProposalRequest, feedback: Feedback | None
    ) -> ProposerResponse:
        anthropic = _sdk()
        client = self._get_client()
        body = self.request_body(request, feedback)
        try:
            with client.messages.stream(**body) as stream:
                message = stream.get_final_message()
        except TypeError as error:
            # With no credentials the SDK raises a bare TypeError at request time, not an API
            # error. Only that exact case is translated; any other TypeError is a bug and stays one.
            if "Could not resolve authentication method" not in str(error):
                raise
            raise ProposerError(
                "no credentials found. Set ANTHROPIC_API_KEY, or run `ant auth login`; "
                "or use --replay to work from a saved response without a model"
            ) from error
        except anthropic.AuthenticationError as error:
            raise ProposerError(
                "the API rejected the credentials (401). Set ANTHROPIC_API_KEY, or run "
                "`ant auth login`"
            ) from error
        except anthropic.PermissionDeniedError as error:
            raise ProposerError(f"the API denied this request (403): {error}") from error
        except anthropic.NotFoundError as error:
            raise ProposerError(
                f"model {self.model!r} was not found, or is not available to this account "
                f"(404): {error}"
            ) from error
        except anthropic.BadRequestError as error:
            raise ProposerError(f"the API rejected the request (400): {error}") from error
        except anthropic.RateLimitError as error:
            raise ProposerError(
                "rate limited (429) after the SDK's automatic retries; try again later"
            ) from error
        except anthropic.APIStatusError as error:
            raise ProposerError(
                f"the API returned an error (HTTP {error.status_code}): {error}"
            ) from error
        except anthropic.APIConnectionError as error:
            raise ProposerError(f"could not reach the API: {error}") from error
        return self._response(message)

    def _response(self, message: Any) -> ProposerResponse:
        # Always read stop_reason before content: a refusal or a truncation is not a proposal.
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProposerError(
                "the model declined to answer"
                + (f" (category: {category})" if category else "")
                + "; nothing was proposed"
            )
        if message.stop_reason == "max_tokens":
            raise ProposerError(
                f"the response hit the {self.max_tokens:,}-token output limit and is incomplete; "
                "split the document or propose the feature in parts"
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise ProposerError("the model returned no text")
        usage = message.usage
        counts = {
            name: getattr(usage, name)
            for name in ("input_tokens", "output_tokens")
            if isinstance(getattr(usage, name, None), int)
        }
        model = getattr(message, "model", self.model)
        return ProposerResponse(text=text, model=model, usage=counts)
