from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "mart_hybrid_subscription__daily_kpis",
    "mart_hybrid_subscription__engagement_lift_inputs",
    "mart_hybrid_subscription__cannibalization_inputs",
}
EXPECTED_TESTS = {
    "assert_hybrid_diagnostic_periods_are_complete.sql",
    "assert_hybrid_kpi_grains_are_unique.sql",
    "assert_hybrid_cannibalization_reconciles.sql",
    "assert_hybrid_diagnostic_segments_are_populated.sql",
}


def test_kpi_marts_publish_decision_ready_contracts() -> None:
    schema = yaml.safe_load((MODEL_DIR / "kpi_schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert EXPECTED_MODELS <= {path.stem for path in MODEL_DIR.glob("*.sql")}
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]
        assert any(
            "unique" in column.get("data_tests", [])
            for column in model.get("columns", [])
        ), model["name"]


def test_kpi_invariants_have_executable_dbt_tests() -> None:
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}
