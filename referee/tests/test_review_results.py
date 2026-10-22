"""Running results rules over an export, and the verdict words (design section 21.3)."""

from typing import Any

import pytest
from results_helpers import Row, at, build_data, crowd, results_spec

from referee.findings import Finding, ResultsReview
from referee.results import ResultsContext
from referee.review import origin_sensitivity, review_context, review_results
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


# --- Origin sensitivity (design section 21.8) -----------------------------------------------


def _origin_rule(fires: str, calls: list[object]) -> Rule[ResultsContext]:
    """A rule whose result depends on nothing but the origin: `fires` is when it fires."""
    when = {
        "three_days_earlier_or_more": lambda origin: origin <= at(-3),
        "only_at_the_actual_origin": lambda origin: origin >= at(0),
        "never": lambda origin: False,
    }[fires]

    def check(context: ResultsContext) -> dict[str, Any] | None:
        calls.append(context.origin)
        return {"origin": context.origin.isoformat()} if when(context.origin) else None

    return Rule(
        id="RES-901",
        severity="warning",
        title="t",
        fires_when="w",
        why_it_matters="because",
        remediation="do something",
        references=(),
        check=check,
    )


@pytest.mark.parametrize(
    ("fires", "same", "appear", "disappear", "verdict"),
    [
        ("never", [True] * 6, [[]] * 6, [[]] * 6, ["clear"] * 6),
        (
            "three_days_earlier_or_more",
            [True, True, False, False, False, False],
            [[], [], *[["RES-901:warning"]] * 4],
            [[]] * 6,
            ["clear", "clear", *["caution"] * 4],
        ),
        (
            "only_at_the_actual_origin",
            [False] * 6,
            [[]] * 6,
            [["RES-901:warning"]] * 6,
            ["clear"] * 6,
        ),
    ],
)
def test_the_findings_are_compared_at_origins_one_to_six_days_before_the_first_assignment(
    raw_spec: dict,
    fires: str,
    same: list[bool],
    appear: list[list[str]],
    disappear: list[list[str]],
    verdict: list[str],
) -> None:
    spec = results_spec(raw_spec)
    data = build_data([*crowd("control", 3), *crowd("variant_b", 3), *crowd("variant_c", 3)])
    rules = (_origin_rule(fires, calls := []),)
    actual = review_context(ResultsContext.of(spec, data), rules=rules)
    calls.clear()

    found = origin_sensitivity(spec, data, actual, rules=rules)

    assert found["ran"] is True
    assert [shift["days_earlier"] for shift in found["shifts"]] == [1, 2, 3, 4, 5, 6]
    assert [shift["same"] for shift in found["shifts"]] == same
    assert [shift["appear"] for shift in found["shifts"]] == appear
    assert [shift["disappear"] for shift in found["shifts"]] == disappear
    assert [shift["verdict"] for shift in found["shifts"]] == verdict
    assert calls == [at(-d) for d in range(1, 7)]  # no player was added or left out


def test_a_registered_origin_is_not_varied(raw_spec: dict) -> None:
    spec = results_spec(raw_spec, design__start_utc="2026-04-11T00:00:00Z")
    data = build_data([*crowd("control", 3), *crowd("variant_b", 3), *crowd("variant_c", 3)])
    rules = (_origin_rule("never", calls := []),)
    actual = review_context(ResultsContext.of(spec, data), rules=rules)
    calls.clear()

    found = origin_sensitivity(spec, data, actual, rules=rules)

    assert found == {"ran": False, "reason": "design.start_utc is registered", "shifts": []}
    assert calls == []
