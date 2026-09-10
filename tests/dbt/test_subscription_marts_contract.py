from pathlib import Path

MODEL_DIR = Path("game_analytics/models/subscription")

EXPECTED_MODELS = {
    "dim_subscription__users.sql",
    "dim_subscription__campaigns.sql",
    "fct_subscription__daily_user_state.sql",
    "fct_subscription__payments.sql",
    "fct_subscription__marketing_spend_daily.sql",
    "mart_subscription__kpis_daily.sql",
    "mart_subscription__trial_conversion_diagnostic.sql",
}


def test_subscription_dimensions_facts_and_marts_exist() -> None:
    actual = {path.name for path in MODEL_DIR.glob("*.sql")}
    assert EXPECTED_MODELS <= actual
