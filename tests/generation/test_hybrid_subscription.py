from datetime import date
from pathlib import Path

import pandas.testing as pdt
import pytest

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.hybrid_subscription import generate

EXPECTED_TABLES = {
    "players",
    "sessions",
    "subscription_events",
    "store_transactions",
    "currency_ledger",
    "live_event_participation",
    "marketing_exposures",
    "product_catalogue",
}


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        scenario="hybrid_subscription",
        seed=seed,
        start_date=date(2026, 1, 1),
        days=120,
        scale=200,
        output_dir=Path("data/raw"),
    )


def test_generator_is_deterministic_and_has_complete_contract() -> None:
    first, second = generate(config()), generate(config())

    assert set(first) == EXPECTED_TABLES
    for table_name in sorted(first):
        pdt.assert_frame_equal(first[table_name], second[table_name], check_like=False)
        assert first[table_name]["scenario_run_id"].nunique() == 1


def test_generator_preserves_references_and_injects_designed_failures() -> None:
    tables = generate(config())
    players = set(tables["players"].player_id)
    catalogue = set(tables["product_catalogue"].sku)

    for table_name in EXPECTED_TABLES - {"players", "product_catalogue"}:
        assert set(tables[table_name].player_id) <= players
    assert set(tables["store_transactions"].sku) <= catalogue

    transactions = tables["store_transactions"]
    assert transactions.transaction_id.duplicated().any()

    grants = tables["currency_ledger"].query("entry_type == 'subscription_grant'")
    assert grants.source_subscription_transaction_id.isna().any()

    starts = (
        tables["subscription_events"]
        .query("event_type == 'started'")
        .set_index("player_id")
        .occurred_at_utc
    )
    exposures = tables["marketing_exposures"].loc[
        lambda frame: frame.player_id.isin(starts.index)
    ]
    assert (
        exposures.exposed_at_utc > exposures.player_id.map(starts)
    ).any()

    canceled = tables["subscription_events"].query("event_type == 'canceled'")
    assert (~canceled.auto_renew_enabled).all()
    assert (canceled.current_period_end_at_utc > canceled.occurred_at_utc).all()


def test_generator_encodes_incrementality_diagnostic_signal() -> None:
    tables = generate(config())
    starts = (
        tables["subscription_events"]
        .query("event_type == 'started'")
        .set_index("player_id")
        .occurred_at_utc
    )
    subscribers = set(starts.index)

    sessions = tables["sessions"].loc[lambda frame: frame.player_id.isin(subscribers)].copy()
    sessions["period"] = [
        "post" if timestamp >= starts[player_id] else "pre"
        for player_id, timestamp in zip(sessions.player_id, sessions.started_at_utc, strict=True)
    ]
    session_counts = sessions.groupby(["player_id", "period"]).size().unstack(fill_value=0)
    assert session_counts["post"].mean() > session_counts["pre"].mean() * 1.20

    transactions = tables["store_transactions"].drop_duplicates("transaction_id")
    prior_payer_subscribers = set(
        tables["players"]
        .query("prior_payer_status == 'prior_payer'")
        .player_id
    ) & subscribers
    iap = transactions.loc[
        transactions.player_id.isin(prior_payer_subscribers)
        & transactions.product_type.ne("subscription")
        & transactions.transaction_status.eq("succeeded")
    ].copy()
    iap["period"] = [
        "post" if timestamp >= starts[player_id] else "pre"
        for player_id, timestamp in zip(iap.player_id, iap.transaction_at_utc, strict=True)
    ]
    revenue = iap.groupby("period").amount_usd.sum()
    assert revenue["post"] < revenue["pre"] * 0.60


def test_event_tables_preserve_raw_local_timezone_and_utc_evidence() -> None:
    tables = generate(config())
    timestamp_contracts = {
        "sessions": "started_at",
        "subscription_events": "occurred_at",
        "store_transactions": "transaction_at",
        "currency_ledger": "occurred_at",
        "live_event_participation": "participated_at",
        "marketing_exposures": "exposed_at",
    }

    for table_name, prefix in timestamp_contracts.items():
        assert {
            f"{prefix}_raw",
            f"{prefix}_local",
            f"{prefix}_timezone",
            f"{prefix}_utc",
            "ingested_at_utc",
        } <= set(tables[table_name])

    assert set(tables["sessions"].started_at_timezone) == {
        "America/Los_Angeles"
    }
    assert set(tables["store_transactions"].transaction_at_timezone) == {
        "Europe/Berlin"
    }


def test_generator_rejects_wrong_scenario() -> None:
    with pytest.raises(ValueError, match="scenario must be hybrid_subscription"):
        generate(
            GenerationConfig(
                "subscription", 42, date(2026, 1, 1), 120, 200, Path("data/raw")
            )
        )
