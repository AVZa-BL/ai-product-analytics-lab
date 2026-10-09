"""The rule framework and the review runner: how rules become a review."""

from typing import Any

import pytest

from referee.findings import Finding
from referee.review import review_design
from referee.rules import ALL_RULES, Escalation, ReviewContext, Rule
from referee.spec import ExperimentSpec

# Design section 8: the IDs and default severities the catalogue promises.
CATALOGUE_SEVERITY = {
    "HYP-001": "blocker",
    "HYP-002": "warning",
    "HYP-003": "warning",
    "HYP-004": "warning",
    "HYP-005": "warning",
    "DES-001": "blocker",
    "DES-002": "warning",
    "DES-003": "warning",
    "DES-004": "info",
    "DES-005": "warning",
    "DES-006": "warning",
    "DES-007": "blocker",
    "DES-008": "warning",
    "PRO-001": "blocker",
    "PRO-002": "warning",
    "PRO-003": "warning",
    "PRO-004": "info",
}


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


@pytest.fixture
def clean_spec(clean_raw_spec: dict) -> ExperimentSpec:
    return ExperimentSpec.from_dict(clean_raw_spec)


# --- Rule ------------------------------------------------------------------------------


def test_a_rule_that_finds_nothing_yields_no_finding(context: ReviewContext) -> None:
    assert make_rule(check=lambda _: None).evaluate(context) is None


def test_a_rule_that_finds_something_yields_a_finding_carrying_its_own_text(
    context: ReviewContext,
) -> None:
    rule = make_rule(severity="blocker", references=("A reference",))

    finding = rule.evaluate(context)

    assert finding == Finding(
        rule_id="TST-001",
        severity="blocker",
        title="A test rule",
        evidence={"seen": "hybrid_offer_page_2026_10"},
        why_it_matters="Because.",
        remediation="Fix it.",
        references=("A reference",),
    )


def test_an_empty_evidence_dict_still_counts_as_a_finding(context: ReviewContext) -> None:
    """Only None means "fine"; a rule with nothing to add still fired."""
    assert make_rule(check=lambda _: {}).evaluate(context) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "TST1"},
        {"severity": "fatal"},
        {"title": ""},
        {"fires_when": ""},
        {"fires_when": "  "},
        {"fires_when": None},
        {"remediation": " "},
        {"references": []},
    ],
    ids=[
        "id",
        "severity",
        "title",
        "fires_when empty",
        "fires_when blank",
        "fires_when missing",
        "remediation",
        "references",
    ],
)
def test_a_malformed_rule_fails_when_it_is_defined_not_when_it_first_fires(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        make_rule(check=lambda _: None, **overrides)


# --- The catalogue ---------------------------------------------------------------------


def test_the_catalogue_holds_exactly_the_promised_rules_with_their_severities() -> None:
    assert {rule.id: rule.severity for rule in ALL_RULES} == CATALOGUE_SEVERITY


def test_rule_ids_are_unique() -> None:
    ids = [rule.id for rule in ALL_RULES]

    assert len(ids) == len(set(ids))


# --- review_design ---------------------------------------------------------------------


def test_a_spec_no_rule_objects_to_gets_a_clean_proceed(clean_spec: ExperimentSpec) -> None:
    review = review_design(clean_spec)

    assert review.findings == ()
    assert review.recommendation == "proceed"


def test_the_review_names_the_spec_it_reviewed(clean_spec: ExperimentSpec) -> None:
    assert review_design(clean_spec).spec_id == "hybrid_offer_page_2026_10"


def test_a_spec_without_a_procedure_is_told_to_revise(clean_raw_spec: dict) -> None:
    del clean_raw_spec["procedure"]

    review = review_design(ExperimentSpec.from_dict(clean_raw_spec))

    assert [f.rule_id for f in review.findings] == ["PRO-001", "PRO-002", "PRO-004"]
    assert review.blocking_rule_ids == ("PRO-001",)
    assert review.recommendation == "revise"


def test_the_same_spec_gives_the_same_review(raw_spec: dict) -> None:
    """The section 6 example has findings of every severity, so this is not vacuous."""
    spec = ExperimentSpec.from_dict(raw_spec)

    assert review_design(spec) == review_design(spec)


def test_the_result_does_not_depend_on_the_order_rules_run_in(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)

    assert review_design(spec, rules=tuple(reversed(ALL_RULES))) == review_design(spec)


def test_a_review_runs_exactly_the_rules_it_is_given(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)
    only_salt = [rule for rule in ALL_RULES if rule.id == "PRO-004"]

    assert [f.rule_id for f in review_design(spec, rules=only_salt).findings] == ["PRO-004"]


def test_a_review_leaves_the_spec_untouched(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)
    before = ExperimentSpec.from_dict(raw_spec)

    review_design(spec)

    assert spec == before


# --- A rule whose finding can be more serious than its default --------------------------------


def _escalating(**overrides: Any) -> Rule:
    escalation = Escalation(
        to="blocker",
        when="the evidence says severe.",
        applies=lambda evidence: bool(evidence.get("severe")),
    )
    return make_rule(escalation=escalation, **overrides)


def test_a_finding_has_the_default_severity_unless_the_evidence_escalates_it() -> None:
    rule = _escalating()

    assert rule.finding({"severe": False}).severity == "warning"
    assert rule.finding({}).severity == "warning"
    assert rule.finding({"severe": True}).severity == "blocker"


def test_an_escalation_is_decided_for_each_finding(context: ReviewContext) -> None:
    quiet = _escalating(check=lambda c: {"severe": False})
    severe = _escalating(check=lambda c: {"severe": True})

    assert quiet.evaluate(context).severity == "warning"
    assert severe.evaluate(context).severity == "blocker"
    assert severe.severity == "warning"  # the rule's own severity is the default


def test_a_rule_without_an_escalation_never_changes_severity() -> None:
    assert make_rule().escalation is None
    assert make_rule().finding({"severe": True}).severity == "warning"


@pytest.mark.parametrize(
    ("severity", "to"), [("warning", "warning"), ("blocker", "warning"), ("warning", "info")]
)
def test_an_escalation_must_go_to_a_more_serious_severity(severity: str, to: str) -> None:
    escalation = Escalation(to=to, when="never.", applies=lambda evidence: True)

    with pytest.raises(ValueError, match="not more serious"):
        make_rule(severity=severity, escalation=escalation)


def test_an_escalation_must_say_when_it_applies() -> None:
    escalation = Escalation(to="blocker", when="  ", applies=lambda evidence: True)

    with pytest.raises(ValueError, match="must say when it applies"):
        make_rule(escalation=escalation)


def test_an_escalated_finding_makes_a_design_review_revise(clean_spec: ExperimentSpec) -> None:
    severe = _escalating(check=lambda c: {"severe": True})

    assert review_design(clean_spec, rules=[severe]).recommendation == "revise"
    quiet = _escalating(check=lambda c: {"severe": False})
    assert review_design(clean_spec, rules=[quiet]).recommendation == "proceed"


def test_an_escalation_to_a_severity_that_does_not_exist_is_a_value_error() -> None:
    escalation = Escalation(to="critical", when="never.", applies=lambda evidence: False)

    with pytest.raises(ValueError, match="severity must be one of"):
        make_rule(escalation=escalation)
