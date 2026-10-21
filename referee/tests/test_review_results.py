"""Running results rules over an export, and the verdict words (design section 21.3)."""

from typing import Any

import pytest
from results_helpers import Row, build_data, results_spec

from referee.findings import Finding, ResultsReview
from referee.results import ResultsContext
from referee.review import review_results
from referee.rules import ALL_RULES, RESULTS_RULES, Rule


def _rule(rule_id: str, severity: str, found: dict[str, Any] | None) -> Rule[ResultsContext]:
    return Rule(
        id=rule_id,
        severity=severity,
        title=f"{rule_id} title",
        fires_when="always, in this test",
        why_it_matters="because",
        remediation="do something",
        references=(),
        check=lambda context: found,
    )


def _finding(rule_id: str, severity: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title="t",
        evidence={},
        why_it_matters="w",
        remediation="r",
        references=(),
    )


@pytest.fixture
def spec(raw_spec: dict):
    return results_spec(raw_spec)


@pytest.fixture
def data():
    return build_data([Row("p1"), Row("p2", "variant_b"), Row("p3", exposed_at=None)])


# --- The verdict words ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severities", "verdict"),
    [
        ((), "clear"),
        (("info",), "clear"),
        (("warning",), "caution"),
    ],
)
def test_the_verdict_follows_from_the_worst_finding(
    severities: tuple[str, ...], verdict: str
) -> None:
    findings = tuple(_finding(f"RES-0{i + 1:02d}", s) for i, s in enumerate(severities))
    review = ResultsReview(
        spec_id="s",
        experiment_id="e",
        rules_run=tuple(f.rule_id for f in findings),
        findings=findings,
    )

    assert review.verdict == verdict
    assert review.blocking_rule_ids == tuple(
        f.rule_id for f in review.findings if f.severity == "blocker"
    )


def test_findings_are_in_report_order_and_the_rules_that_ran_are_sorted() -> None:
    findings = (
        _finding("RES-009", "info"),
        _finding("RES-004", "blocker"),
        _finding("RES-002", "warning"),
    )

    review = ResultsReview(
        spec_id="s",
        experiment_id="e",
        rules_run=("RES-009", "RES-001", "RES-004", "RES-002"),
        findings=findings,
    )

    assert [f.rule_id for f in review.findings] == ["RES-004", "RES-002", "RES-009"]
    assert review.rules_run == ("RES-001", "RES-002", "RES-004", "RES-009")


def test_a_finding_from_a_rule_that_did_not_run_is_a_bug() -> None:
    with pytest.raises(ValueError, match=r"did not run: \['RES-002'\]"):
        ResultsReview(
            spec_id="s",
            experiment_id="e",
            rules_run=("RES-001",),
            findings=(_finding("RES-002", "info"),),
        )


def test_a_rule_that_ran_twice_is_a_bug() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['RES-001'\]"):
        ResultsReview(spec_id="s", experiment_id="e", rules_run=("RES-001", "RES-001"), findings=())


# --- The driver -----------------------------------------------------------------------------


def test_the_default_rules_are_the_results_rules_and_not_the_design_rules(spec, data) -> None:
    review = review_results(spec, data)

    assert review.rules_run == tuple(sorted(rule.id for rule in RESULTS_RULES))
    assert not {r.id for r in RESULTS_RULES} & {r.id for r in ALL_RULES}
    assert all(rule.id.startswith("RES-") for rule in RESULTS_RULES)


# --- What the review says about the players it left out ---------------------------------------


