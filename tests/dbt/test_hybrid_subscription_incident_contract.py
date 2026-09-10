from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_TESTS = {
    "assert_expected_hybrid_incidents_detected.sql",
    "assert_hybrid_incident_counts_reconcile.sql",
    "assert_hybrid_containment_rules_hold.sql",
}


def test_incident_mart_has_governed_contract() -> None:
    schema = yaml.safe_load((MODEL_DIR / "incident_schema.yml").read_text())
    model = schema["models"][0]

    assert model["name"] == "mart_hybrid_subscription__data_quality_incidents"
    assert "hybrid_subscription" in model["config"]["tags"]
    assert any(
        "unique" in column.get("data_tests", [])
        for column in model["columns"]
    )
    assert (MODEL_DIR / f"{model['name']}.sql").is_file()


def test_incident_detection_and_containment_are_executable() -> None:
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}
