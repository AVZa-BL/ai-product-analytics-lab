import copy
from dataclasses import fields

import pytest

from tests.propose_helpers import final_proposal, small_proposal
from tracewright.propose import proposal as p
from tracewright.propose.proposal import PROPOSAL_SCHEMA, Proposal, ProposalError


def violations(data) -> tuple[str, ...]:
    with pytest.raises(ProposalError) as caught:
        Proposal.from_dict(data)
    return caught.value.violations


def test_the_example_proposal_is_valid():
    proposal = Proposal.from_dict(final_proposal())
    assert len(proposal.new_events) == 6
    assert proposal.extended_events[0].name == "purchase_completed"


def test_to_dict_round_trips():
    data = final_proposal()
    assert Proposal.from_dict(data).to_dict() == data


def test_every_violation_is_listed():
    data = small_proposal()
    data["new_events"][0]["priority"] = "urgent"
    data["new_events"][0]["properties"][0]["type"] = "uuid"
    del data["new_events"][0]["rationale"]
    assert len(violations(data)) == 3


def test_unknown_fields_are_refused():
    data = small_proposal()
    data["extra"] = 1
    assert any("extra" in v for v in violations(data))


@pytest.mark.parametrize("key", ["required", "pii", "reuses_existing", "type"])
def test_property_flags_are_required(key):
    data = small_proposal()
    del data["new_events"][0]["properties"][1][key]
    assert any(v.endswith(f"{key}: is required") for v in violations(data))


def test_flags_must_be_booleans():
    data = small_proposal()
    data["new_events"][0]["properties"][1]["pii"] = "no"
    assert any("true or false" in v for v in violations(data))


def test_document_evidence_needs_a_name_and_a_quote():
    data = small_proposal()
    data["new_events"][0]["evidence"] = {"kind": "document", "document": "", "quote": ""}
    assert any("needs both" in v for v in violations(data))


def test_an_extended_event_must_add_something():
    data = small_proposal()
    data["extended_events"] = [
        {
            "name": "order_completed",
            "rationale": "r",
            "evidence": {"kind": "inferred", "document": "", "quote": ""},
            "add_properties": [],
        }
    ]
    assert any("at least one property" in v for v in violations(data))


def test_limits_are_enforced():
    data = small_proposal()
    data["new_events"][0]["description"] = "x" * (p.MAX_TEXT + 1)
    assert any("longer than" in v for v in violations(data))
    data = small_proposal()
    extra = small_proposal()["new_events"][0]["properties"][1]
    data["new_events"][0]["properties"] = [extra] * (p.MAX_PROPERTIES + 1)
    assert any("more than" in v for v in violations(data))


def test_not_an_object():
    assert violations([]) == ("the proposal must be a JSON object",)


def test_feature_id_must_be_an_identifier():
    data = small_proposal()
    data["feature"]["id"] = "Bad Id"
    assert any("feature.id" in v for v in violations(data))


# --- the schema the model is given must stay in step with the validator ---------------------


def _walk(schema, path="$"):
    yield path, schema
    if schema.get("type") == "object":
        for key, child in schema["properties"].items():
            yield from _walk(child, f"{path}.{key}")
    if schema.get("type") == "array":
        yield from _walk(schema["items"], f"{path}[]")


def test_the_schema_is_strict_everywhere():
    for path, node in _walk(PROPOSAL_SCHEMA):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False, path
            assert node["required"] == list(node["properties"]), path


def test_the_schema_has_the_same_fields_as_the_dataclasses():
    assert list(PROPOSAL_SCHEMA["properties"]) == [f.name for f in fields(Proposal)]
    event = PROPOSAL_SCHEMA["properties"]["new_events"]["items"]["properties"]
    assert list(event) == [f.name for f in fields(p.NewEvent)]
    prop = event["properties"]["items"]["properties"]
    assert list(prop) == [f.name for f in fields(p.ProposedProperty)]


def test_the_example_proposal_matches_the_schema_shape():
    data = final_proposal()
    assert set(data) == set(PROPOSAL_SCHEMA["properties"])
    assert copy.deepcopy(data) == data
