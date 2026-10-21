"""The rule framework and the review runner: how rules become a review."""

from typing import Any

import pytest

from referee.rules import Escalation, ReviewContext, Rule
from referee.spec import ExperimentSpec


def make_rule(**overrides: Any) -> Rule:
    fields: dict[str, Any] = {
        "id": "TST-001",
        "severity": "warning",
        "title": "A test rule",
        "fires_when": "Always, in a test.",
        "why_it_matters": "Because.",
        "remediation": "Fix it.",
        "references": (),
        "check": lambda context: {"seen": context.spec.id},
    }
    return Rule(**{**fields, **overrides})


@pytest.fixture
def context(raw_spec: dict) -> ReviewContext:
    return ReviewContext.of(ExperimentSpec.from_dict(raw_spec))


# --- Rule ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "TST1"},
        {"fires_when": "  "},
    ],
    ids=[
        "id",
        "fires_when blank",
    ],
)
def test_a_malformed_rule_fails_when_it_is_defined_not_when_it_first_fires(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        make_rule(check=lambda _: None, **overrides)


# --- The catalogue ---------------------------------------------------------------------


# --- review_design ---------------------------------------------------------------------


# --- A rule whose finding can be more serious than its default --------------------------------


@pytest.mark.parametrize(("severity", "to"), [("warning", "warning")])
def test_an_escalation_must_go_to_a_more_serious_severity(severity: str, to: str) -> None:
    escalation = Escalation(to=to, when="never.", applies=lambda evidence: True)

    with pytest.raises(ValueError, match="not more serious"):
        make_rule(severity=severity, escalation=escalation)


def test_an_escalation_must_say_when_it_applies() -> None:
    escalation = Escalation(to="blocker", when="  ", applies=lambda evidence: True)

    with pytest.raises(ValueError, match="must say when it applies"):
        make_rule(escalation=escalation)


def test_an_escalation_to_a_severity_that_does_not_exist_is_a_value_error() -> None:
    escalation = Escalation(to="critical", when="never.", applies=lambda evidence: False)

    with pytest.raises(ValueError, match="severity must be one of"):
        make_rule(escalation=escalation)
