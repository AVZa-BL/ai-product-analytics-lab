"""What is asked of a proposer, and what comes back. Shared by every proposer."""

from __future__ import annotations

from dataclasses import dataclass

from tracewright.plan import TrackingPlan
from tracewright.propose.documents import Document


@dataclass(frozen=True, kw_only=True)
class ProposalRequest:
    documents: tuple[Document, ...]
    plan: TrackingPlan | None


@dataclass(frozen=True, kw_only=True)
class Feedback:
    """A previous attempt and what was wrong with it, for a repair round."""

    previous_text: str
    problems: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ProposerResponse:
    text: str
    model: str | None = None
    usage: dict[str, int] | None = None


class ProposerError(RuntimeError):
    """The proposer could not produce a response (credentials, network, refusal, truncation)."""
