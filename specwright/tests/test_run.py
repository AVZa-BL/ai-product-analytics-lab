"""The draft-check-repair loop: what goes back, how often, and when it stops."""

from __future__ import annotations

import json

import pytest

from specwright.proposers import ReplayProposer
from specwright.request import DraftRequest, Feedback, ProposerError, ProposerResponse
from specwright.run import run_draft
from tests.helpers import SHOP, claim, documents, replay, shop_draft


class Scripted:
    """A proposer that gives the same text every time and keeps what it was asked."""

    def __init__(self, text: str) -> None:
        self.text, self.feedbacks = text, []

    def propose(self, request: DraftRequest, feedback: Feedback | None) -> ProposerResponse:
        self.feedbacks.append(feedback)
        return ProposerResponse(text=self.text, model="scripted")


def request(brief: str = SHOP, owner: str | None = None) -> DraftRequest:
    return DraftRequest(documents=documents(brief), owner=owner)


def bad_draft() -> str:
    data = shop_draft()
    claim(data, "design.alpha")["evidence"]["quote"] = "Nothing like this is in the brief."
    return json.dumps(data)


def test_the_blockers_go_back_to_the_model_and_the_repaired_draft_is_ok() -> None:
    proposer = ReplayProposer(replay("01-shop-banner.repair"))
    seen = []
    result = run_draft(request(), proposer, on_attempt=seen.append)

    first, second = result.attempts
    assert (result.status, result.repairs, [a.number for a in seen]) == ("ok", 1, [1, 2])
    sent = [line.split("]")[0] + "]" for line in first.feedback_sent]
    assert sorted(set(sent)) == ["[FIELD_OMITTED]", "[NUMBER_NOT_IN_QUOTE]", "[QUOTE_NOT_FOUND]"]
    assert second.feedback_sent == ()


def test_the_repair_request_carries_the_previous_response_and_the_problems() -> None:
    proposer = Scripted(bad_draft())

    run_draft(request(), proposer, max_repairs=1)

    assert proposer.feedbacks[0] is None
    again = proposer.feedbacks[1]
    assert again.previous_text == proposer.text and again.problems
    assert any(line.startswith("[QUOTE_NOT_FOUND] design.alpha:") for line in again.problems)


@pytest.mark.parametrize("max_repairs", [0, 1, 2, 5])
def test_a_draft_that_is_never_fixed_gets_at_most_the_repairs_asked_for(max_repairs: int) -> None:
    proposer = Scripted(bad_draft())

    result = run_draft(request(), proposer, max_repairs=max_repairs)

    assert len(result.attempts) == len(proposer.feedbacks) == max_repairs + 1
    assert result.status == "unresolved"  # reported as it is, never hidden


@pytest.mark.parametrize("max_repairs", [-1, 6])
def test_a_number_of_repairs_outside_zero_to_five_is_refused(max_repairs: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 5"):
        run_draft(request(), Scripted("{}"), max_repairs=max_repairs)


@pytest.mark.parametrize(
    ("brief", "status"),
    [
        ("04-ambiguous-numbers", "needs_answers"),
        ("03-missing-baseline", "needs_answers"),
        ("02-infeasible-niche-event", "infeasible"),
    ],
)
def test_a_draft_that_only_needs_answers_or_is_infeasible_is_not_sent_back(
    brief: str, status: str
) -> None:
    proposer = Scripted(json.dumps(replay(brief)))

    result = run_draft(request(brief), proposer)

    assert (result.status, len(result.attempts), result.final.feedback_sent) == (status, 1, ())


def test_a_response_that_is_not_json_goes_back_as_a_schema_problem() -> None:
    proposer = ReplayProposer(["I would be happy to help!", shop_draft()])

    result = run_draft(request(), proposer)

    assert result.attempts[0].draft is None
    assert result.attempts[0].feedback_sent[0].startswith("[SCHEMA] the response is not valid JSON")
    assert result.status == "ok"


def test_a_long_list_of_problems_is_cut_and_says_so() -> None:
    data = shop_draft()
    for i in range(1, 12):  # eleven guardrails with a name and nothing else: five omissions each
        data["claims"].append(
            {
                "path": f"guardrails[{i}].name",
                "value": f"g{i}",
                "evidence": {"kind": "inferred", "document": "", "quote": "", "note": ""},
            }
        )
    proposer = Scripted(json.dumps(data))

    result = run_draft(request(), proposer, max_repairs=0)

    sent = result.final.feedback_sent
    assert len(sent) == 41 and "more problems of the same kinds" in sent[-1]


def test_a_failure_in_a_repair_round_says_how_many_attempts_are_discarded() -> None:
    proposer = ReplayProposer([bad_draft()])

    with pytest.raises(ProposerError, match=r"repair round 1 failed after 1 completed attempt"):
        run_draft(request(), proposer)


def test_a_failure_in_the_first_attempt_is_raised_as_it_is() -> None:
    with pytest.raises(ProposerError, match="only 0 response"):
        run_draft(request(), ReplayProposer([]))
