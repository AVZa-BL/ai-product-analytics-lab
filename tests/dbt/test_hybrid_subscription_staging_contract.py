from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription")
EXPECTED_MODELS = {
    "stg_hybrid_subscription__players",
    "stg_hybrid_subscription__sessions",
    "stg_hybrid_subscription__subscription_events",
    "stg_hybrid_subscription__store_transactions",
    "stg_hybrid_subscription__currency_ledger",
    "stg_hybrid_subscription__live_event_participation",
    "stg_hybrid_subscription__marketing_exposures",
    "stg_hybrid_subscription__product_catalogue",
}


def test_every_hybrid_raw_entity_has_a_contracted_staging_model() -> None:
    schema = yaml.safe_load((MODEL_DIR / "staging/schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert {
        path.stem for path in (MODEL_DIR / "staging").glob("*.sql")
    } == EXPECTED_MODELS
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]


def test_sources_cover_all_generator_tables() -> None:
    source = yaml.safe_load((MODEL_DIR / "sources.yml").read_text())["sources"][0]

    assert source["name"] == "hybrid_subscription_raw"
    assert {table["name"] for table in source["tables"]} == {
        name.removeprefix("stg_hybrid_subscription__") for name in EXPECTED_MODELS
    }

