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
