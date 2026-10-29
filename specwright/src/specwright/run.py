"""The draft-check-repair loop.

One attempt is a model call, a parse against the draft schema, and the deterministic checks. If the
checks find a blocker the model can fix, the attempt and its problems go back to the model for
another go, up to `max_repairs` times. What is left after that is reported as it is: the loop never
edits a draft itself and never hides a problem to make the result look clean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from specwright.check import CheckResult, Status, check_draft, repair_feedback
from specwright.draft import Draft, DraftError
from specwright.proposers import Proposer
from specwright.request import DraftRequest, Feedback, ProposerError, ProposerResponse

MAX_FEEDBACK_LINES = 40
MAX_REPAIRS_LIMIT = 5


@dataclass(frozen=True, kw_only=True)
class Attempt:
    number: int
    response: ProposerResponse
    draft: Draft | None
    parse_problems: tuple[str, ...]  # not JSON, or not a valid draft
    check: CheckResult | None
    feedback_sent: tuple[str, ...]  # what this attempt's problems told the next one


@dataclass(frozen=True, kw_only=True)
class DraftResult:
    request: DraftRequest
    attempts: tuple[Attempt, ...]

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]

    @property
    def repairs(self) -> int:
        return len(self.attempts) - 1

    @property
    def status(self) -> Status:
        final = self.final
        if final.draft is None or final.parse_problems or final.check is None:
            return "unresolved"
        return final.check.status


def run_draft(
    request: DraftRequest,
    proposer: Proposer,
    *,
    max_repairs: int = 2,
    on_attempt: Callable[[Attempt], None] | None = None,
) -> DraftResult:
    """Draft, check and repair. Raises ProposerError if the model cannot be reached.

    `on_attempt` is called as each attempt finishes, so a caller can show progress and spent
    tokens even if a later round fails.
    """
    if not 0 <= max_repairs <= MAX_REPAIRS_LIMIT:
        raise ValueError(f"max_repairs must be between 0 and {MAX_REPAIRS_LIMIT}")
    attempts: list[Attempt] = []
    feedback: Feedback | None = None
    for number in range(1, max_repairs + 2):
        try:
            response = proposer.propose(request, feedback)
        except ProposerError as error:
            if not attempts:
                raise
            raise ProposerError(
                f"repair round {number - 1} failed after {len(attempts)} completed attempt(s), "
                f"whose results are discarded: {error}"
            ) from error
        draft, parse_problems, check = None, (), None
        try:
            draft = Draft.from_json(response.text)
        except DraftError as error:
            parse_problems = error.violations
        if draft is not None:
            check = check_draft(draft, request.documents, owner=request.owner)
            problems = repair_feedback(check)
        else:
            problems = [f"[SCHEMA] {violation}" for violation in parse_problems]
        if len(problems) > MAX_FEEDBACK_LINES:
            extra = len(problems) - MAX_FEEDBACK_LINES
            problems = problems[:MAX_FEEDBACK_LINES] + [
                f"... and {extra} more problems of the same kinds; fix the pattern, not just these"
            ]
        attempt = Attempt(
            number=number,
            response=response,
            draft=draft,
            parse_problems=parse_problems,
            check=check,
            feedback_sent=tuple(problems),
        )
        attempts.append(attempt)
        if on_attempt is not None:
            on_attempt(attempt)
        if not problems:
            break
        feedback = Feedback(previous_text=response.text, problems=tuple(problems))
    return DraftResult(request=request, attempts=tuple(attempts))
