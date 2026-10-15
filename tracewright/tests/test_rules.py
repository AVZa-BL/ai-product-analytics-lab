import pytest

from tests.rule_helpers import run


def ev(raw, i=0):
    return raw["events"][i]


def add_prop(name):
    return lambda r: ev(r)["properties"].append({"name": name, "type": "string"})


# (rule, edit that makes it fire, expected evidence key)
CASES = [
    ("SCH-003", lambda r: ev(r)["properties"][0].update(required=False), "events"),
    ("DOC-001", lambda r: ev(r).pop("description"), "events"),
]


@pytest.mark.parametrize(("rule_id", "edit", "key"), CASES)
def test_rule_fires(raw_plan, rule_id, edit, key):
    finding = run(rule_id, raw_plan, edit)
    assert finding is not None
    assert key in finding.evidence


@pytest.mark.parametrize(
    "name",
    ["IP", "IPAddress", "phoneNumber", "SSN", "firstName",
     "fullname", "firstname", "DOB", "BirthDate", "birthday", "passportNumber"],
)
def test_gov_001_sees_camel_case_and_joined_spellings(raw_plan, name):
    assert run("GOV-001", raw_plan, add_prop(name)) is not None


