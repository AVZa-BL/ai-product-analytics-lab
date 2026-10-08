import json

import pytest

from tests.propose_helpers import example_request, final_proposal, replay_attempts, small_proposal
from tracewright.propose.proposers import ReplayProposer
from tracewright.propose.request import ProposalRequest, ProposerError, ProposerResponse
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


def test_a_clean_first_attempt_is_not_repaired():
    proposer = Recording(dumps(final_proposal()))
    result = run_proposal(example_request(), proposer)
    assert result.status == "ok" and result.repairs == 0 and proposer.feedback == [None]


def test_a_failing_attempt_is_sent_back_with_its_problems():
    first, final = replay_attempts()
    proposer = Recording(dumps(first), dumps(final))
    result = run_proposal(example_request(), proposer)
    assert result.status == "ok" and result.repairs == 1
    feedback = proposer.feedback[1]
    assert json.loads(feedback.previous_text) == first
    joined = "\n".join(feedback.problems)
    assert "COLLISION" in joined and "EVIDENCE_QUOTE" in joined and "SCH-001" in joined


def test_repairs_stop_at_the_limit_and_the_result_is_unresolved():
    first = replay_attempts()[0]
    proposer = Recording(dumps(first), dumps(first), dumps(first))
    result = run_proposal(example_request(), proposer, max_repairs=2)
    assert result.status == "unresolved" and len(result.attempts) == 3


def test_zero_repairs_means_one_attempt():
    proposer = Recording(dumps(replay_attempts()[0]))
    result = run_proposal(example_request(), proposer, max_repairs=0)
    assert len(result.attempts) == 1 and result.status == "unresolved"


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


def test_an_unreachable_model_propagates():
    class Down:
        def propose(self, request, feedback):
            raise ProposerError("down")

    with pytest.raises(ProposerError, match="down"):
        run_proposal(example_request(), Down())


def test_a_replay_that_runs_out_is_an_error_not_a_hang():
    with pytest.raises(ProposerError, match="only 1 response"):
        run_proposal(example_request(), ReplayProposer([replay_attempts()[0]]))


def test_negative_repairs_are_refused():
    with pytest.raises(ValueError):
        run_proposal(example_request(), Recording("{}"), max_repairs=-1)


def test_the_proposer_is_called_with_the_request_unchanged():
    seen = []

    class Spy:
        def propose(self, request, feedback):
            seen.append(request)
            return ProposerResponse(text=dumps(final_proposal()))

    request = example_request()
    run_proposal(request, Spy())
    assert seen == [request] and isinstance(seen[0], ProposalRequest)


def test_each_attempt_is_reported_as_it_finishes():
    first, final = replay_attempts()
    seen = []
    proposer = Recording(dumps(first), dumps(final))
    result = run_proposal(
        example_request(),
        proposer,
        on_attempt=lambda a: seen.append((a.number, len(a.feedback_sent))),
    )
    assert seen == [(1, 4), (2, 0)] and result.status == "ok"


def test_a_failed_repair_round_says_what_was_completed_and_lost():
    first = replay_attempts()[0]
    seen = []

    class FailsSecond:
        def __init__(self):
            self.calls = 0

        def propose(self, request, feedback):
            self.calls += 1
            if self.calls == 2:
                raise ProposerError("the API returned an error (HTTP 529)")
            usage = {"input_tokens": 9000, "output_tokens": 4000}
            return ProposerResponse(text=dumps(first), usage=usage)

    with pytest.raises(ProposerError) as caught:
        run_proposal(example_request(), FailsSecond(), on_attempt=seen.append)
    message = str(caught.value)
    assert "repair round 1 failed after 1 completed attempt(s)" in message
    assert "discarded" in message and "HTTP 529" in message
    assert len(seen) == 1  # the first attempt was reported before the second failed


def test_a_failure_on_the_first_call_is_not_wrapped():
    class Down:
        def propose(self, request, feedback):
            raise ProposerError("no credentials")

    with pytest.raises(ProposerError) as caught:
        run_proposal(example_request(), Down())
    assert str(caught.value) == "no credentials"
