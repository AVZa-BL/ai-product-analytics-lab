from pathlib import Path

REQUIRED = {
    "Owner",
    "Source model",
    "Grain",
    "Eligibility",
    "Formula",
    "Exclusions",
    "Time rule",
    "Known limitations",
    "Validation query",
}


def test_subscription_metric_contracts_are_complete() -> None:
    contracts = list(Path("docs/metrics/subscription").glob("*.md"))
    assert len(contracts) == 9
    for contract in contracts:
        text = contract.read_text()
        assert all(f"## {heading}" in text for heading in REQUIRED), contract
