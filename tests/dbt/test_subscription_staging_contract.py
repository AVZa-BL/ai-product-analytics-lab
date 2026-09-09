from pathlib import Path

import pandas as pd
import yaml

PROJECT = Path("game_analytics")
MODEL_DIR = PROJECT / "models" / "subscription"
EXPECTED_STAGING_MODELS = {
    "stg_subscription__users.sql",
    "stg_subscription__onboarding_events.sql",
    "stg_subscription__product_events.sql",
    "stg_subscription__subscription_events.sql",
    "stg_subscription__payments.sql",
    "stg_subscription__marketing_spend.sql",
    "stg_subscription__support_tickets.sql",
}


def test_subscription_activation_mapping_is_explicit_and_complete() -> None:
    mapping_path = PROJECT / "seeds" / "subscription_event_name_map.csv"
    assert mapping_path.exists(), "subscription activation mapping seed is missing"

    records = pd.read_csv(mapping_path).to_dict("records")
    assert records == [
        {
            "raw_event_name": "activation_completed",
            "canonical_event_name": "activation_completed",
            "is_activation_event": True,
        },
        {
            "raw_event_name": "activated",
            "canonical_event_name": "activation_completed",
            "is_activation_event": True,
        },
        {
            "raw_event_name": "onboarding_complete",
            "canonical_event_name": "activation_completed",
            "is_activation_event": True,
        },
        {
            "raw_event_name": "screen_view",
            "canonical_event_name": "screen_view",
            "is_activation_event": False,
        },
        {
            "raw_event_name": "feature_used",
            "canonical_event_name": "feature_used",
            "is_activation_event": False,
        },
    ]


def test_all_subscription_raw_entities_have_staging_models() -> None:
    actual = {path.name for path in MODEL_DIR.glob("stg_subscription__*.sql")}
    assert actual == EXPECTED_STAGING_MODELS


def test_subscription_staging_models_are_tagged_and_contracted() -> None:
    schema_path = MODEL_DIR / "schema.yml"
    assert schema_path.exists(), "subscription staging schema contract is missing"

    schema = yaml.safe_load(schema_path.read_text())
    models = {model["name"]: model for model in schema["models"]}
    assert {
        "stg_subscription__users",
        "stg_subscription__subscription_events",
        "stg_subscription__product_events",
    } <= set(models)
    for model in models.values():
        assert "subscription" in model["config"]["tags"]
