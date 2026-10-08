"""The propose-check-repair loop.

One attempt is a model call, a parse against the proposal schema, and the deterministic checks.
If the checks find something the model can fix, the attempt and its problems go back to the model
for another go, up to `max_repairs` times. What is left after that is reported as it is: the loop
never edits a proposal itself and never hides a problem to make the result look clean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from tracewright.propose.check import CheckResult, check_proposal, repair_feedback
from tracewright.propose.proposal import Proposal, ProposalError
from tracewright.propose.proposers import Proposer
from tracewright.propose.request import (
    Feedback,
    ProposalRequest,
    ProposerResponse,
)

MAX_FEEDBACK_LINES = 40


@dataclass(frozen=True, kw_only=True)
class Attempt:
    number: int
    response: ProposerResponse
    proposal: Proposal | None
    parse_problems: tuple[str, ...]  # not JSON, or not a valid proposal
    check: CheckResult | None
    feedback_sent: tuple[str, ...]  # what this attempt's problems told the next one


@dataclass(frozen=True, kw_only=True)
class ProposalResult:
    request: ProposalRequest
    owner: str | None
    attempts: tuple[Attempt, ...]

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]

    @property
    def repairs(self) -> int:
        return len(self.attempts) - 1

    @property
    def status(self) -> str:
        """"ok" when nothing blocks, "unresolved" when the last attempt still has a blocker."""
        final = self.final
        if final.proposal is None or final.parse_problems or final.check is None:
            return "unresolved"
        return "unresolved" if final.check.blocking else "ok"


def parse_response(text: str) -> tuple[Proposal | None, tuple[str, ...]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return None, (f"the response is not valid JSON ({error})",)
    try:
        return Proposal.from_dict(data), ()
    except ProposalError as error:
        return None, error.violations


def run_proposal(
    request: ProposalRequest,
    proposer: Proposer,
    *,
    max_repairs: int = 2,
    owner: str | None = None,
) -> ProposalResult:
    """Propose, check and repair. Raises ProposerError if the model cannot be reached."""
    if max_repairs < 0:
        raise ValueError("max_repairs must be 0 or more")
    attempts: list[Attempt] = []
    feedback: Feedback | None = None
    for number in range(1, max_repairs + 2):
        response = proposer.propose(request, feedback)
        proposal, parse_problems = parse_response(response.text)
        check = None
        if proposal is not None:
            check = check_proposal(proposal, request.plan, request.documents, owner=owner)
            problems = repair_feedback(check)
        else:
            problems = [f"[SCHEMA] {violation}" for violation in parse_problems]
        if len(problems) > MAX_FEEDBACK_LINES:
            extra = len(problems) - MAX_FEEDBACK_LINES
            problems = problems[:MAX_FEEDBACK_LINES] + [
                f"... and {extra} more problems of the same kinds; fix the pattern, not just these"
            ]
        attempts.append(
            Attempt(
                number=number,
                response=response,
                proposal=proposal,
                parse_problems=parse_problems,
                check=check,
                feedback_sent=tuple(problems),
            )
        )
        if not problems:
            break
        feedback = Feedback(previous_text=response.text, problems=tuple(problems))
    return ProposalResult(request=request, owner=owner, attempts=tuple(attempts))
