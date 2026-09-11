import re
from pathlib import Path

import pytest

EXPECTED_METRICS = [
    "MAU",
    "Active subscribers",
    "Subscription conversion",
    "Subscriber churn",
    "D30 subscriber retention",
    "ARPMAU",
    "Incremental net revenue",
    "Discount utilization",
    "Engagement lift",
    "LiveOps participation",
]
REQUIRED_FIELDS = [
    "Source model",
    "Grain",
    "Numerator",
    "Denominator",
    "Maturity",
    "Exclusions",
    "Interpretation boundary",
]


@pytest.mark.parametrize("metric", EXPECTED_METRICS)
def test_every_approved_kpi_has_a_complete_contract(metric: str) -> None:
    text = Path("docs/metrics/hybrid_subscription.md").read_text()
    sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S))
    assert metric in sections, f"Missing approved KPI: {metric}"
    for field in REQUIRED_FIELDS:
        assert re.search(rf"\*\*{field}:\*\*\s+\S", sections[metric]), (metric, field)


def test_catalogue_preserves_population_and_accounting_boundaries() -> None:
    text = Path("docs/metrics/hybrid_subscription.md").read_text().lower()
    for boundary in [
        "earliest incrementality-eligible exposure",
        "without replacement",
        "pre_session_count",
        "unmatched",
        "reward-track",
        "null",
        "global observation",
        "does not establish causality",
        "cancellation alone",
        "entitlement-event rate",
        "exact start plus 30 days",
    ]:
        assert boundary in text


def test_readme_links_only_committed_hybrid_evidence() -> None:
    readme = Path("README.md").read_text()
    for artifact in [
        "docs/metrics/hybrid_subscription.md",
        "engagement_cannibalization_diagnostic.py",
        "engagement_cannibalization_diagnostic_results.json",
        "engagement_cannibalization_decision_memo.md",
    ]:
        assert artifact in readme
    assert not re.search(r"\]\([^)]*hybrid_subscription[^)]*(?:\.ipynb|figures/)", readme)
