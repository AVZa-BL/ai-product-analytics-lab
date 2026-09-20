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

    # Assert the artifact exists, not merely that the memo names it. The prose
    # check alone passed for weeks while the file was absent from the repository.
    results = Path("reports/live_strategy/d7_retention_diagnostic_results.json")
    assert results.is_file(), "memo cites a results artifact that is not committed"
    assert "d7_retention_diagnostic_results.json" in text
