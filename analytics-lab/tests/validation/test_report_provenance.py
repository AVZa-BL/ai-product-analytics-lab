"""The published documents name the execution their results JSON records.

A memo, an audit or a validation record that cites a different commit, time or incident
table than the JSON it describes has drifted from its evidence. That happened twice by
transcription; these tests make the agreement a checked reference value.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]  # analytics-lab/
LIVE = ROOT / "reports" / "live_strategy"
HYBRID = ROOT / "reports" / "hybrid_subscription"
CASES = {
    "live_strategy": (
        LIVE / "d7_retention_diagnostic_results.json",
        (LIVE / "d7_retention_diagnostic.md",),
    ),
    "hybrid_subscription": (
        HYBRID / "engagement_cannibalization_diagnostic_results.json",
        (
            HYBRID / "engagement_cannibalization_decision_memo.md",
            ROOT / "docs" / "ai-audit" / "hybrid_subscription.md",
        ),
    ),
}


@pytest.mark.parametrize("scenario", sorted(CASES))
def test_the_documents_quote_the_commit_and_time_of_their_json(scenario: str) -> None:
    results_path, documents = CASES[scenario]
    metadata = json.loads(results_path.read_text())["metadata"]
    for document in documents:
        text = document.read_text()
        for key in ("code_version", "executed_at_utc"):
            assert f"`{metadata[key]}`" in text, f"{document.name} does not quote {key}"


def test_the_hybrid_validation_record_and_incident_table_agree_with_the_json() -> None:
    results_path, (memo_path, audit_path) = CASES["hybrid_subscription"]
    results = json.loads(results_path.read_text())
    record = json.loads((HYBRID / "native_validation.json").read_text())
    memo = memo_path.read_text()
    audit = audit_path.read_text()

    assert record["source_commit"] == results["metadata"]["code_version"]
    executed_at = results["metadata"]["executed_at_utc"]
    assert record["generated_at_utc"] <= executed_at, "the build must come before the diagnostic"
    for document in (memo, audit):
        assert f"TOTAL={record['results']['total']}" in document

    # The memo's incident table: code, affected rows and decision status, in the JSON's order.
    rows = re.findall(r"^\| (\w+) \| (\d+) \| (\w+) \| ", memo, flags=re.MULTILINE)
    expected = [
        (row["incident_code"], str(row["affected_rows"]), row["decision_status"])
        for row in results["data_quality_incidents"]
    ]
    assert rows == expected
