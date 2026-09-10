from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "dim_hybrid_subscription__players",
    "dim_hybrid_subscription__products",
    "fct_hybrid_subscription__subscription_entitlements",
    "fct_hybrid_subscription__store_transactions",
    "fct_hybrid_subscription__currency_grants",
    "fct_hybrid_subscription__marketing_exposures",
    "fct_hybrid_subscription__player_behavior_28d",
}
EXPECTED_TESTS = {
    "assert_fact_entitlements_have_valid_windows.sql",
    "assert_fact_revenue_reconciles.sql",
    "assert_incrementality_exposures_are_eligible.sql",
    "assert_player_behavior_has_one_row_per_period.sql",
}


def test_marts_publish_governed_dimensions_and_facts() -> None:
    schema = yaml.safe_load((MODEL_DIR / "schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert {path.stem for path in MODEL_DIR.glob("*.sql")} == EXPECTED_MODELS
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]


def test_marts_define_keys_and_executable_control_tests() -> None:
    schema = yaml.safe_load((MODEL_DIR / "schema.yml").read_text())

    for model in schema["models"]:
        assert any(
            "unique" in column.get("data_tests", [])
            for column in model.get("columns", [])
        ), model["name"]
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}
