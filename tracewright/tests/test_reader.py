import pytest

from tests.propose_helpers import small_proposal
from tracewright.plan import PlanError, TrackingPlan
from tracewright.propose.proposal import Proposal, ProposalError

ESC = "\x1b"
BIDI = "‮"


def plan_with(raw_plan, **changes):
    raw_plan.update(changes)
    return TrackingPlan.from_dict(raw_plan)


@pytest.mark.parametrize(
    "bad", [f"title {ESC}]0;pwned\x07", f"abc{BIDI}def", "nul\x00byte", "c1\x9b"]
)
def test_control_and_direction_characters_in_plan_text_are_refused(raw_plan, bad):
    with pytest.raises(PlanError, match="control or direction-override"):
        plan_with(raw_plan, title=bad)


def test_tabs_and_line_breaks_are_allowed(raw_plan):
    assert plan_with(raw_plan, title="two\nlines\twith a tab").title.startswith("two")


def test_list_entries_are_checked_too(raw_plan):
    with pytest.raises(PlanError, match="control characters"):
        plan_with(raw_plan, identity_keys=[f"user{ESC}_id"])


def test_a_hostile_key_is_reported_escaped(raw_plan):
    raw_plan[f"bad{ESC}[2Jkey"] = 1
    with pytest.raises(PlanError) as caught:
        TrackingPlan.from_dict(raw_plan)
    message = str(caught.value)
    assert ESC not in message and "\\x1b" in message


def test_model_text_with_a_control_character_is_a_violation_not_silently_cleaned():
    data = small_proposal()
    data["new_events"][0]["rationale"] = f"because {ESC}]0;pwned\x07"
    with pytest.raises(ProposalError, match="control or direction-override"):
        Proposal.from_dict(data)


def test_list_text_from_the_model_is_checked(raw_plan):
    data = small_proposal()
    data["assumptions"] = [f"assume {BIDI}this"]
    with pytest.raises(ProposalError):
        Proposal.from_dict(data)
