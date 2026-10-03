from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "mart_hybrid_subscription__experiment_arm_daily",
    "mart_hybrid_subscription__experiment_readout",
}
EXPECTED_TESTS = {
    "assert_experiment_arm_daily_reconciles.sql",
    "assert_experiment_readout_reconciles.sql",
}


def test_experiment_marts_publish_governed_contracts() -> None:
    schema = yaml.safe_load((MODEL_DIR / "experiment_schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert EXPECTED_MODELS <= {path.stem for path in MODEL_DIR.glob("*.sql")}
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]


def test_experiment_mart_invariants_have_executable_dbt_tests() -> None:
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}
