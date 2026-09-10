import json
import re
from pathlib import Path

import pytest

ROOT = Path("reports/hybrid_subscription")
RESULTS = json.loads((ROOT / "engagement_cannibalization_diagnostic_results.json").read_text())


def test_memo_has_decision_and_observational_boundaries() -> None:
    text = (ROOT / "engagement_cannibalization_decision_memo.md").read_text()
    for heading in [
        "Decision",
        "Executive summary",
        "Observed facts",
        "Interpretation",
        "Assumptions and uncertainty",
        "Data-quality qualification",
        "Recommended experiment",
        "Reproducibility",
    ]:
        assert f"## {heading}" in text
    for boundary in [
        "does not establish causality",
        "standalone displacement",
        "total net value",
        "engagement_cannibalization_diagnostic_results.json",
        "mart_hybrid_subscription__matched_incrementality",
        "fct_hybrid_subscription__player_behavior_28d",
        "unmatched",
    ]:
        assert boundary in text


@pytest.mark.parametrize(
    "field",
    [
        "eligible_subscriber_count",
        "eligible_control_count",
        "matched_pair_count",
        "matched_prior_payer_pair_count",
        "unmatched_subscriber_count",
        "unmatched_control_count",
    ],
)
def test_memo_population_matches_committed_results(field: str) -> None:
    text = (ROOT / "engagement_cannibalization_decision_memo.md").read_text()
    assert f"| {field} | {RESULTS['population'][field]} |" in text


@pytest.mark.parametrize(
    "group,field",
    [
        ("engagement", "engagement_difference_in_differences"),
        ("revenue", "standalone_store_difference_in_differences"),
        ("revenue", "subscription_difference_in_differences"),
        ("revenue", "total_revenue_difference_in_differences"),
    ],
)
def test_memo_numeric_evidence_matches_committed_json(group: str, field: str) -> None:
    text = (ROOT / "engagement_cannibalization_decision_memo.md").read_text()
    assert f"| {field} | {RESULTS['results'][group][field]} |" in text


def test_governance_does_not_imply_unpublished_notebooks_or_execution() -> None:
    for path in [
        ROOT / "engagement_cannibalization_decision_memo.md",
        Path("docs/ai-audit/hybrid_subscription.md"),
    ]:
        text = path.read_text()
        assert not re.search(r"\]\([^)]*(?:\.ipynb|figures/)[^)]*\)", text)
        assert "Jupyter kernel execution" in text
        assert "real-checkout HEAD equivalence" in text
        assert "owner-run" in text
    audit = Path("docs/ai-audit/hybrid_subscription.md").read_text()
    assert "direct exact-source execution succeeded" in audit
    assert RESULTS["metadata"]["code_version"] in audit


def assert_memo_evidence(text, results):
    """Every copied population, estimate, interval, incident and provenance value."""
    for field, value in results["population"].items():
        assert f"| {field} | {value} |" in text, field
    for field, value in results["results"]["bootstrap_intervals"].items():
        assert f"| {field} | {value} |" in text, field
    for incident in results["data_quality_incidents"]:
        assert (
            f"| {incident['incident_code']} | {incident['affected_rows']} | "
            f"{incident['decision_status']} | {incident['containment_rule']} |"
        ) in text
    for key in ["code_version", "executed_at_utc"]:
        assert results["metadata"][key] in text
    for key in ["bootstrap_seed", "bootstrap_draws"]:
        assert f"{key} = {results['metadata'][key]}" in text


def assert_audit_evidence(text, results):
    """Copied audit numbers must be exact source fields, not prose-only numbers."""
    for field in ["matched_pair_count", "unmatched_subscriber_count", "unmatched_control_count"]:
        assert f"{field} = {results['population'][field]}" in text
    for group, field in [
        ("engagement", "engagement_difference_in_differences"),
        ("revenue", "standalone_store_difference_in_differences"),
        ("revenue", "subscription_difference_in_differences"),
        ("revenue", "total_revenue_difference_in_differences"),
    ]:
        assert f"{field} = {results['results'][group][field]}" in text
    for key in ["code_version", "executed_at_utc"]:
        assert results["metadata"][key] in text
    for relation in results["metadata"]["input_relations"]:
        assert relation in text


def test_all_copied_memo_and_audit_values_have_exact_committed_sources():
    assert_memo_evidence(
        (ROOT / "engagement_cannibalization_decision_memo.md").read_text(), RESULTS
    )
    assert_audit_evidence(Path("docs/ai-audit/hybrid_subscription.md").read_text(), RESULTS)


@pytest.mark.parametrize("field", ["interval", "incident", "timestamp"])
def test_source_checks_reject_mutated_memo_numbers(field):
    import copy

    text = (ROOT / "engagement_cannibalization_decision_memo.md").read_text()
    assert_memo_evidence(text, RESULTS)
    corrupted = copy.deepcopy(RESULTS)
    if field == "interval":
        corrupted["results"]["bootstrap_intervals"]["engagement_change_ci_95"][0] += 0.1
    elif field == "incident":
        corrupted["data_quality_incidents"][0]["affected_rows"] += 1
    else:
        corrupted["metadata"]["executed_at_utc"] = "invented-timestamp"
    with pytest.raises(AssertionError):
        assert_memo_evidence(text, corrupted)
