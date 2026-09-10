from pathlib import Path


def test_memo_has_evidence_and_decision_boundaries() -> None:
    text = Path("reports/live_strategy/d7_retention_diagnostic.md").read_text()

    for heading in [
        "## Decision",
        "## Observed facts",
        "## Inference",
        "## Assumptions and uncertainty",
        "## Data-quality qualification",
        "## Recommended next actions",
        "## Reproducibility",
    ]:
        assert heading in text

    assert "mart_live_strategy__d7_diagnostic_inputs" in text
    assert "d7_retention_diagnostic_results.json" in text
