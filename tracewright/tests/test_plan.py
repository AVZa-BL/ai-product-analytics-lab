import copy

import pytest

from tracewright.plan import PlanError, TrackingPlan


def violations(raw: dict) -> tuple[str, ...]:
    with pytest.raises(PlanError) as caught:
        TrackingPlan.from_dict(raw)
    return caught.value.violations


def test_a_valid_plan_loads(raw_plan):
    plan = TrackingPlan.from_dict(raw_plan)
    assert plan.id == "checkout_funnel"
    assert [event.name for event in plan.events] == ["checkout_started", "order_completed"]


def test_status_defaults_to_active(raw_plan):
    assert TrackingPlan.from_dict(raw_plan).events[0].status == "active"


def test_every_violation_is_listed_not_only_the_first(raw_plan):
    raw_plan["id"] = "Bad Id"
    raw_plan["events"][0]["status"] = "retired"
    raw_plan["events"][1]["properties"][0]["type"] = "uuid"
    assert len(violations(raw_plan)) == 3


@pytest.mark.parametrize("field", ["id", "title", "identity_keys", "events"])
def test_required_fields(raw_plan, field):
    del raw_plan[field]
    assert any(v.startswith(f"{field}:") for v in violations(raw_plan))


def test_unknown_fields_are_refused(raw_plan):
    raw_plan["events"][0]["colour"] = "red"
    assert any("colour" in v and "not a known field" in v for v in violations(raw_plan))


def test_wrong_version_is_refused(raw_plan):
    raw_plan["tracewright_plan_version"] = 2
    assert any("tracewright_plan_version" in v for v in violations(raw_plan))


def test_duplicate_event_and_property_names_are_refused(raw_plan):
    raw_plan["events"].append(copy.deepcopy(raw_plan["events"][0]))
    raw_plan["events"][1]["properties"].append({"name": "user_id", "type": "string"})
    found = violations(raw_plan)
    assert any("declared more than once" in v for v in found)
    assert any("declared twice" in v for v in found)


def test_allowed_values_need_an_enum(raw_plan):
    raw_plan["events"][0]["properties"][1]["allowed_values"] = ["a"]
    assert any("only meaningful when type is enum" in v for v in violations(raw_plan))


def test_a_plan_that_is_not_a_mapping_is_refused():
    assert violations([]) == ("the plan must be a mapping of fields",)  # type: ignore[arg-type]


def test_the_fingerprint_ignores_key_order(raw_plan):
    reordered = dict(reversed(list(raw_plan.items())))
    assert TrackingPlan.from_dict(raw_plan).sha256() == TrackingPlan.from_dict(reordered).sha256()


def test_the_fingerprint_changes_with_content(raw_plan):
    first = TrackingPlan.from_dict(raw_plan).sha256()
    raw_plan["title"] = "Another title"
    assert TrackingPlan.from_dict(raw_plan).sha256() != first
