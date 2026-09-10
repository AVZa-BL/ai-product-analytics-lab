from pathlib import Path

CATALOGUE = Path("docs/metrics/hybrid_subscription.md")
EXPECTED_METRICS = [
    "28-day engagement lift",
    "Standalone-store net revenue per player",
    "Subscription net revenue per player",
    "Total net revenue per player",
    "Prior-payer standalone-store cannibalization",
    "Subscription-grant reconciliation rate",
    "Incrementality-eligible exposure rate",
]
REQUIRED_FIELDS = [
    "Source relation",
    "Grain",
    "Population",
    "Formula",
    "Maturity rule",
    "Exclusions",
    "Owner",
    "Interpretation boundary",
]


def test_every_hybrid_metric_has_a_complete_semantic_contract() -> None:
    text = CATALOGUE.read_text()

    for metric in EXPECTED_METRICS:
        section = text.split(f"## {metric}", 1)[1].split("## ", 1)[0]
        for field in REQUIRED_FIELDS:
            assert f"**{field}:**" in section, f"{metric}: {field}"


def test_readme_links_to_hybrid_metric_catalogue() -> None:
    readme = Path("README.md").read_text()

    assert "docs/metrics/hybrid_subscription.md" in readme
