import json

import pytest

from tests.propose_helpers import example_request, final_proposal, small_proposal
from tracewright.propose.request import ProposerResponse
from tracewright.propose.run import MAX_FEEDBACK_LINES, run_proposal


class Recording:
    """A proposer that returns canned text and remembers what it was asked."""

    def __init__(self, *texts):
        self.texts = list(texts)
        self.feedback = []

    def propose(self, request, feedback):
        self.feedback.append(feedback)
        return ProposerResponse(text=self.texts.pop(0), model="fake")


def dumps(data):
    return json.dumps(data)


def test_text_that_is_not_json_is_repaired():
    proposer = Recording("Sure! Here is the plan:", dumps(final_proposal()))
    result = run_proposal(example_request(), proposer)
    assert result.status == "ok"
    assert "not valid JSON" in proposer.feedback[1].problems[0]


def test_json_that_is_not_a_proposal_is_repaired():
    proposer = Recording(dumps({"feature": 1}), dumps(final_proposal()))
    result = run_proposal(example_request(), proposer)
    assert result.status == "ok" and proposer.feedback[1].problems[0].startswith("[SCHEMA]")


def test_a_proposal_that_never_parses_is_unresolved():
    result = run_proposal(example_request(), Recording("x", "y", "z"))
    assert result.status == "unresolved" and result.final.proposal is None


def test_feedback_is_capped_and_says_what_was_cut():
    data = small_proposal()
    data["reused_events"] = [
        {"name": f"ghost_{i}", "rationale": "r"} for i in range(MAX_FEEDBACK_LINES + 20)
    ]
    proposer = Recording(dumps(data), dumps(data))
    run_proposal(example_request(), proposer, max_repairs=1)
    lines = proposer.feedback[1].problems
    assert len(lines) == MAX_FEEDBACK_LINES + 1 and "more problems" in lines[-1]


def test_negative_repairs_are_refused():
    with pytest.raises(ValueError):
        run_proposal(example_request(), Recording("{}"), max_repairs=-1)


