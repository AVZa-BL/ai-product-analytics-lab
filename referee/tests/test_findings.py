"""Finding and DesignReview: what a rule may emit and how a review orders it."""

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


def test_a_rule_may_raise_one_finding_at_most() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['DES-001'\]"):
        review_of(make_finding(), make_finding(evidence={"other": 1}))


def test_a_review_is_frozen_and_hashable() -> None:
    review = review_of(make_finding())

    assert hash(review) == hash(review_of(make_finding()))
    with pytest.raises(AttributeError):
        review.spec_id = "other"
