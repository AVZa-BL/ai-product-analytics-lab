"""Running results rules over an export, and the verdict words (design section 21.3)."""

from typing import Any

import pytest
from results_helpers import Row, build_data, results_spec

from referee.findings import DesignReview, Finding, ResultsReview
from referee.results import ResultsContext, ResultsError
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
        (("warning", "info"), "caution"),
        (("blocker",), "invalid"),
        (("blocker", "warning", "info"), "invalid"),
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


def test_the_words_are_not_the_design_reviews() -> None:
    assert not hasattr(DesignReview, "verdict") and not hasattr(ResultsReview, "recommendation")


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


def test_a_rule_may_raise_one_finding_at_most() -> None:
    with pytest.raises(ValueError, match=r"repeated: \['RES-001'\]"):
        ResultsReview(
            spec_id="s",
            experiment_id="e",
            rules_run=("RES-001",),
            findings=(_finding("RES-001", "info"), _finding("RES-001", "warning")),
        )


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


def test_the_rules_are_given_the_context_and_the_review_names_what_ran(spec, data) -> None:
    seen: list[ResultsContext] = []

    def check(context: ResultsContext) -> dict[str, Any]:
        seen.append(context)
        return {"players": len(context.players), "analysed": len(context.analysed)}

    rule = Rule(
        id="RES-001",
        severity="blocker",
        title="t",
        fires_when="always",
        why_it_matters="w",
        remediation="r",
        references=(),
        check=check,
    )
    quiet = _rule("RES-002", "warning", None)

    review = review_results(spec, data, rules=[rule, quiet])

    assert len(seen) == 1 and isinstance(seen[0], ResultsContext)
    assert (review.spec_id, review.experiment_id) == (spec.id, "e1")
    assert review.rules_run == ("RES-001", "RES-002")  # the quiet rule ran and found nothing
    assert [(f.rule_id, f.evidence) for f in review.findings] == [
        ("RES-001", {"players": 3, "analysed": 2})
    ]
    assert review.verdict == "invalid"


def test_with_no_rules_the_verdict_is_clear_and_says_nothing_was_checked(spec, data) -> None:
    review = review_results(spec, data, rules=[])

    assert review.verdict == "clear" and review.rules_run == () and review.findings == ()


def test_the_same_spec_and_data_give_the_same_review(spec, data) -> None:
    rules = [_rule("RES-003", "warning", {"n": 1}), _rule("RES-001", "blocker", {"n": 2})]

    assert review_results(spec, data, rules=rules) == review_results(spec, data, rules=rules)


def test_the_order_the_rules_are_given_in_does_not_change_the_review(spec, data) -> None:
    rules = [_rule("RES-003", "warning", {"n": 1}), _rule("RES-001", "blocker", {"n": 2})]

    assert review_results(spec, data, rules=rules) == review_results(spec, data, rules=rules[::-1])


def test_two_rules_with_one_id_cannot_both_run(spec, data) -> None:
    with pytest.raises(ValueError, match="repeated"):
        review_results(
            spec, data, rules=[_rule("RES-001", "info", None), _rule("RES-001", "info", None)]
        )


def test_data_that_cannot_be_read_against_the_spec_is_refused_before_any_rule_runs(spec) -> None:
    called = []
    rule = Rule(
        id="RES-001",
        severity="info",
        title="t",
        fires_when="always",
        why_it_matters="w",
        remediation="r",
        references=(),
        check=lambda context: called.append(1),
    )

    with pytest.raises(ResultsError):
        review_results(spec, build_data([Row("p1", "variant_z")]), rules=[rule])

    assert called == []


def test_the_default_rules_are_the_results_rules_and_not_the_design_rules(spec, data) -> None:
    review = review_results(spec, data)

    assert review.rules_run == tuple(sorted(rule.id for rule in RESULTS_RULES))
    assert not {r.id for r in RESULTS_RULES} & {r.id for r in ALL_RULES}
    assert all(rule.id.startswith("RES-") for rule in RESULTS_RULES)
