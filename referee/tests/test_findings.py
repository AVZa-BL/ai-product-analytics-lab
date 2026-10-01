"""Finding and DesignReview: what a rule may emit and how a review orders it."""

import itertools
from typing import Any

import pytest

from referee.findings import DesignReview, Finding


def make_finding(**overrides: Any) -> Finding:
    fields: dict[str, Any] = {
        "rule_id": "DES-001",
        "severity": "blocker",
        "title": "Not enough traffic",
        "evidence": {"required_total": 389_060},
        "why_it_matters": "An underpowered test cannot tell an effect from noise.",
        "remediation": "Run longer or accept a larger minimum detectable effect.",
        "references": ("Kohavi, Tang, Xu (2020)",),
    }
    return Finding(**{**fields, **overrides})


def review_of(*findings: Finding) -> DesignReview:
    return DesignReview(spec_id="offer_page_test", findings=findings)


# --- Finding ---------------------------------------------------------------------------


def test_a_well_formed_finding_is_accepted_and_keeps_its_fields() -> None:
    finding = make_finding()

    assert finding.rule_id == "DES-001"
    assert finding.severity == "blocker"
    assert finding.evidence == {"required_total": 389_060}
    assert finding.references == ("Kohavi, Tang, Xu (2020)",)


def test_a_finding_is_hashable_although_its_evidence_is_a_dict() -> None:
    first, second = make_finding(), make_finding()

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_evidence_still_takes_part_in_equality() -> None:
    assert make_finding(evidence={"n": 1}) != make_finding(evidence={"n": 2})


def test_a_finding_is_frozen() -> None:
    with pytest.raises(AttributeError):
        make_finding().severity = "info"


@pytest.mark.parametrize("rule_id", ["DES-001", "HYP-005", "PRO-004", "ABC-999"])
def test_rule_ids_of_the_documented_shape_are_accepted(rule_id: str) -> None:
    assert make_finding(rule_id=rule_id).rule_id == rule_id


@pytest.mark.parametrize(
    "rule_id",
    ["", "DES1", "DES-01", "DES-0001", "des-001", "DE-001", "DESI-001", " DES-001", "DES-001\n", 1],
    ids=repr,
)
def test_a_malformed_rule_id_is_rejected(rule_id: object) -> None:
    with pytest.raises(ValueError, match="rule_id must look like 'DES-001'"):
        make_finding(rule_id=rule_id)


@pytest.mark.parametrize("severity", ["error", "BLOCKER", "", None, 1])
def test_an_unknown_severity_is_rejected(severity: object) -> None:
    with pytest.raises(ValueError, match="severity must be one of"):
        make_finding(severity=severity)


@pytest.mark.parametrize("name", ["title", "why_it_matters", "remediation"])
@pytest.mark.parametrize("value", ["", "   ", None, 5], ids=repr)
def test_the_prose_fields_must_be_non_empty_strings(name: str, value: object) -> None:
    with pytest.raises(ValueError, match=f"{name} must be a non-empty string"):
        make_finding(**{name: value})


@pytest.mark.parametrize("references", [["a"], "a", ("a", 1), None], ids=repr)
def test_references_must_be_a_tuple_of_strings(references: object) -> None:
    with pytest.raises(ValueError, match="references must be a tuple of strings"):
        make_finding(references=references)


def test_a_finding_may_cite_nothing() -> None:
    assert make_finding(references=()).references == ()


# --- DesignReview ----------------------------------------------------------------------


def test_findings_are_ordered_by_severity_then_rule_id() -> None:
    review = review_of(
        make_finding(rule_id="PRO-004", severity="info"),
        make_finding(rule_id="HYP-002", severity="warning"),
        make_finding(rule_id="DES-007", severity="blocker"),
        make_finding(rule_id="DES-002", severity="warning"),
        make_finding(rule_id="DES-001", severity="blocker"),
        make_finding(rule_id="DES-004", severity="info"),
    )

    assert [(f.severity, f.rule_id) for f in review.findings] == [
        ("blocker", "DES-001"),
        ("blocker", "DES-007"),
        ("warning", "DES-002"),
        ("warning", "HYP-002"),
        ("info", "DES-004"),
        ("info", "PRO-004"),
    ]


def test_the_order_does_not_depend_on_the_order_rules_ran() -> None:
    findings = [
        make_finding(rule_id="PRO-001", severity="blocker"),
        make_finding(rule_id="DES-003", severity="warning"),
        make_finding(rule_id="HYP-001", severity="blocker"),
        make_finding(rule_id="PRO-004", severity="info"),
    ]

    orderings = {review_of(*p).findings for p in itertools.permutations(findings)}

    assert len(orderings) == 1


def test_findings_are_a_tuple_even_when_given_a_list() -> None:
    review = DesignReview(spec_id="x", findings=[make_finding()])

    assert isinstance(review.findings, tuple)


def test_blocking_rule_ids_lists_only_blockers_in_order() -> None:
    review = review_of(
        make_finding(rule_id="PRO-001", severity="blocker"),
        make_finding(rule_id="DES-002", severity="warning"),
        make_finding(rule_id="DES-001", severity="blocker"),
        make_finding(rule_id="DES-004", severity="info"),
    )

    assert review.blocking_rule_ids == ("DES-001", "PRO-001")


def test_any_blocker_means_revise() -> None:
    assert review_of(make_finding(severity="blocker")).recommendation == "revise"


def test_a_blocker_among_lesser_findings_still_means_revise() -> None:
    review = review_of(
        make_finding(rule_id="DES-002", severity="warning"),
        make_finding(rule_id="DES-004", severity="info"),
        make_finding(rule_id="PRO-001", severity="blocker"),
    )

    assert review.recommendation == "revise"


def test_warnings_and_notes_alone_mean_proceed() -> None:
    review = review_of(
        make_finding(rule_id="DES-002", severity="warning"),
        make_finding(rule_id="DES-004", severity="info"),
    )

    assert review.recommendation == "proceed"
    assert review.blocking_rule_ids == ()


def test_a_review_with_no_findings_means_proceed() -> None:
    review = review_of()

    assert review.findings == ()
    assert review.recommendation == "proceed"
    assert review.blocking_rule_ids == ()


def test_a_rule_may_raise_one_finding_at_most() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['DES-001'\]"):
        review_of(make_finding(), make_finding(evidence={"other": 1}))


def test_a_review_is_frozen_and_hashable() -> None:
    review = review_of(make_finding())

    assert hash(review) == hash(review_of(make_finding()))
    with pytest.raises(AttributeError):
        review.spec_id = "other"
