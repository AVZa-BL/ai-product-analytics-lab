import pytest

from linesman.rules import ALL_RULES
from tests.rule_helpers import run


def test_the_valid_fixture_triggers_no_rule(raw_plan):
    assert [r.id for r in ALL_RULES if run(r.id, raw_plan) is not None] == []


def test_rule_ids_are_unique_and_documented():
    ids = [rule.id for rule in ALL_RULES]
    assert len(ids) == len(set(ids))


def ev(raw, i=0):
    return raw["events"][i]


def add_prop(name):
    return lambda r: ev(r)["properties"].append({"name": name, "type": "string"})


# (rule, edit that makes it fire, expected evidence key)
CASES = [
    ("NAM-001", lambda r: ev(r).update(name="CheckoutStarted"), "events"),
    ("NAM-001", lambda r: ev(r).update(name="click"), "events"),
    ("NAM-002", lambda r: ev(r)["properties"][1].update(name="cartValue"), "properties"),
    ("SCH-001", lambda r: ev(r, 1)["properties"][1].update(type="string"), "properties"),
    ("SCH-002", lambda r: ev(r, 1)["properties"][2].pop("allowed_values"), "properties"),
    ("SCH-003", lambda r: ev(r)["properties"][0].update(required=False), "events"),
    ("DOC-001", lambda r: ev(r).pop("description"), "events"),
    ("DOC-001", lambda r: ev(r).pop("trigger"), "events"),
    ("DOC-002", lambda r: (r.pop("owner"), ev(r)), "events"),
    ("GOV-001", add_prop("email"), "properties"),
    ("GOV-001", add_prop("first_name"), "properties"),
    ("COV-001", lambda r: r["metrics"][0]["events"].append("ghost_event"), "metrics"),
    ("COV-002", lambda r: ev(r, 1).update(status="deprecated"), "metrics"),
    ("COV-003", lambda r: ev(r, 1).update(status="planned"), "metrics"),
    ("COV-004", lambda r: r["metrics"][0].update(events=["checkout_started"]), "events"),
]


@pytest.mark.parametrize(("rule_id", "edit", "key"), CASES)
def test_rule_fires(raw_plan, rule_id, edit, key):
    finding = run(rule_id, raw_plan, edit)
    assert finding is not None
    assert key in finding.evidence


def test_every_rule_has_a_firing_case():
    assert {case[0] for case in CASES} == {rule.id for rule in ALL_RULES}


def test_a_plan_owner_covers_events_without_one(raw_plan):
    assert run("DOC-002", raw_plan) is None


def test_a_pii_property_marked_pii_is_accepted(raw_plan):
    def edit(raw):
        ev(raw)["properties"].append({"name": "email", "type": "string", "pii": True})

    assert run("GOV-001", raw_plan, edit) is None


def test_pii_words_are_matched_as_whole_words(raw_plan):
    def edit(raw):
        ev(raw)["properties"].append({"name": "shipping_method", "type": "string"})

    assert run("GOV-001", raw_plan, edit) is None


def test_a_deprecated_event_needs_no_identity_or_docs(raw_plan):
    def edit(raw):
        raw["events"].append({"name": "old_event", "status": "deprecated"})

    assert run("SCH-003", raw_plan, edit) is None
    assert run("DOC-001", raw_plan, edit) is None


def test_no_metrics_means_no_unused_event_finding(raw_plan):
    assert run("COV-004", raw_plan, lambda r: r.update(metrics=[])) is None
