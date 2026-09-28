import json
from pathlib import Path

MEMO = Path("reports/live_strategy/d7_retention_diagnostic.md")
RESULTS = Path("reports/live_strategy/d7_retention_diagnostic_results.json")


def test_memo_provenance_matches_the_results_artifact() -> None:
    """The memo and its results JSON must name one commit and one execution.

    A re-run updated code_version and executed_at_utc in the JSON while the memo kept
    citing the previous run, and nothing failed: the test below asserts only that the
    artifact exists. The hybrid memo has carried this guard since P1-8; live strategy
    did not, so the two files disagreed in published form.
    """
    text = MEMO.read_text()
    metadata = json.loads(RESULTS.read_text())["metadata"]
    for key in ["code_version", "executed_at_utc"]:
        assert metadata[key] in text, f"memo does not cite the results artifact's {key}"


def test_memo_discloses_the_platform_its_figures_are_exact_for() -> None:
    """Values reproduce exactly within a platform and not across platforms.

    A Linux/x86_64 run of the same commit, from byte-identical generated inputs, moves
    the population by one player and every downstream figure with it. Publishing six
    decimal places without naming the platform they hold on overstates the guarantee.
    """
    text = MEMO.read_text()
    assert "Execution platform:" in text
    assert "not across platforms" in text


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
