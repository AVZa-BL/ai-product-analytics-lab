from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "mart_hybrid_subscription__daily_kpis",
    "mart_hybrid_subscription__monthly_kpis",
    "mart_hybrid_subscription__subscription_cohorts",
    "mart_hybrid_subscription__matched_incrementality",
    "mart_hybrid_subscription__match_population_summary",
    "mart_hybrid_subscription__engagement_lift_inputs",
    "mart_hybrid_subscription__cannibalization_inputs",
}
EXPECTED_TESTS = {
    "assert_hybrid_analysis_population_eligible.sql",
    "assert_hybrid_behavior_windows_complete.sql",
    "assert_hybrid_matched_pairs_valid.sql",
    "assert_hybrid_matched_population_reconciles.sql",
    "assert_hybrid_reward_track_excluded.sql",
    "assert_hybrid_kpis_reconcile.sql",
    "assert_hybrid_zero_denominators_are_null.sql",
    "assert_hybrid_cohort_maturity.sql",
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
