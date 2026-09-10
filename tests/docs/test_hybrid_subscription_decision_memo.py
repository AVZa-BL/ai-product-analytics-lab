from pathlib import Path


def test_hybrid_memo_publishes_evidence_and_decision_boundaries() -> None:
    text = Path(
        "reports/hybrid_subscription/engagement_cannibalization_decision_memo.md"
    ).read_text()

    for heading in [
        "## Decision",
        "## Executive summary",
        "## Observed facts",
        "## Interpretation",
        "## Assumptions and uncertainty",
        "## Data-quality qualification",
        "## Recommended experiment",
        "## Reproducibility",
    ]:
        assert heading in text

    for evidence in [
        "+1.85 sessions per player",
        "-$24.66 per player",
        "-$14.67 per player",
        "[-$19.56, -$9.82]",
        "does not establish causality",
        "engagement_cannibalization_diagnostic_results.json",
        "fct_hybrid_subscription__player_behavior_28d",
    ]:
        assert evidence in text


def test_readme_links_to_hybrid_decision_artifacts() -> None:
    readme = Path("README.md").read_text()

    assert "engagement_cannibalization_diagnostic.py" in readme
    assert "engagement_cannibalization_decision_memo.md" in readme
