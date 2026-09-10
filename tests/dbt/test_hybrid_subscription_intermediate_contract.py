from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/intermediate")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "int_hybrid_subscription__subscription_entitlements",
    "int_hybrid_subscription__grant_reconciliation",
    "int_hybrid_subscription__marketing_exposure_eligibility",
    "int_hybrid_subscription__analysis_population",
    "int_hybrid_subscription__player_28d_behavior",
    "int_hybrid_subscription__quality_audit",
    "int_hybrid_subscription__matched_pairs",
    "int_hybrid_subscription__match_population_summary",
}
EXPECTED_TESTS = {
    "assert_cancellation_preserves_entitlement.sql",
    "assert_entitlements_do_not_overlap.sql",
    "assert_grant_reconciliation_is_complete.sql",
    "assert_exposure_eligibility_precedes_subscription.sql",
    "assert_player_28d_behavior_grain.sql",
    "assert_hybrid_matched_pairs_valid.sql",
    "assert_hybrid_matched_population_reconciles.sql",
}


def test_intermediate_models_publish_business_state_contracts() -> None:
    schema = yaml.safe_load((MODEL_DIR / "schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert {path.stem for path in MODEL_DIR.glob("*.sql")} == EXPECTED_MODELS
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]


def test_intermediate_invariants_have_executable_dbt_tests() -> None:
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}
