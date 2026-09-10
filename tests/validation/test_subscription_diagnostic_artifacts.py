from pathlib import Path


def test_subscription_diagnostic_artifacts_are_auditable() -> None:
    notebook = Path("notebooks/subscription/trial_to_paid_diagnostic.ipynb").read_text()
    memo = Path("reports/subscription/trial_to_paid_decision_memo.md").read_text()
    audit = Path("docs/ai-audit/subscription/trial_to_paid_diagnostic.md").read_text()
    for token in [
        "source_models",
        "execution_date",
        "filters",
        "code_version",
        "maturity_cutoff_date",
    ]:
        assert token in notebook
    for heading in [
        "## Observed facts",
        "## Inference",
        "## Assumptions and uncertainty",
        "## Recommendation",
    ]:
        assert heading in memo
    for heading in [
        "## Proposed work",
        "## Human validation",
        "## Rejected output",
        "## Correction",
        "## Provenance",
    ]:
        assert heading in audit
