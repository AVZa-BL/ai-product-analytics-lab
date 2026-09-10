from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.live_strategy import generate


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        scenario="live_strategy",
        seed=seed,
        start_date=date(2026, 1, 1),
        days=180,
        scale=1_000,
        output_dir=Path("data/raw"),
    )


def test_generator_is_deterministic_and_has_the_complete_contract() -> None:
    first, second = generate(config()), generate(config())
    assert set(first) == {
        "players",
        "sessions",
        "gameplay_events",
        "purchases",
        "progression_snapshots",
        "alliances",
        "alliance_memberships",
        "live_events",
        "battles",
        "economy_transactions",
        "config_versions",
    }
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name], check_like=False)


def test_generator_injects_failures_without_breaking_base_references() -> None:
    tables = generate(config())
    players = set(tables["players"].player_id)

    assert set(tables["sessions"].player_id) <= players
    assert set(tables["gameplay_events"].player_id) <= players
    assert set(tables["purchases"].player_id) <= players
    assert set(tables["economy_transactions"].player_id) <= players
    assert set(tables["alliance_memberships"].player_id) <= players

    gameplay_events = tables["gameplay_events"]
    duplicate_android_events = gameplay_events.platform.eq("android") & (
        gameplay_events.client_event_id.duplicated(keep=False)
    )
    assert duplicate_android_events.any()
    assert tables["sessions"].ended_at_utc.isna().any()
    assert (
        tables["alliance_memberships"].valid_to_utc
        < tables["alliance_memberships"].valid_from_utc
    ).any()

    player_install = tables["players"].set_index("player_id").installed_at_utc
    assert (
        gameplay_events.occurred_at_utc
        < gameplay_events.player_id.map(player_install)
    ).any()
    assert tables["economy_transactions"].transaction_type.eq("refund").any()


def test_generator_preserves_diagnostic_distributions_and_failure_rates() -> None:
    tables = generate(config())
    update_at = pd.Timestamp("2026-04-01", tz="UTC")
    players = tables["players"]
    pre_paid_social = players.loc[
        players.installed_at_utc < update_at, "acquisition_channel"
    ].eq("paid_social").mean()
    post_paid_social = players.loc[
        players.installed_at_utc >= update_at, "acquisition_channel"
    ].eq("paid_social").mean()
    android_events = tables["gameplay_events"].loc[
        lambda frame: frame.platform.eq("android")
    ]
    duplicate_rate = android_events.client_event_id.duplicated(keep="first").mean()
    missing_end_rate = tables["sessions"].loc[
        lambda frame: frame.platform.eq("android")
        & frame.app_version.eq("4.12.0"),
        "ended_at_utc",
    ].isna().mean()

    assert post_paid_social > pre_paid_social + 0.15
    assert 0.055 <= duplicate_rate <= 0.065
    assert 0.345 <= missing_end_rate <= 0.355


def test_generator_rejects_wrong_scenario_and_nonpositive_scale() -> None:
    with pytest.raises(ValueError, match="scenario must be live_strategy"):
        generate(
            GenerationConfig(
                "subscription",
                42,
                date(2026, 1, 1),
                180,
                1_000,
                Path("data/raw"),
            )
        )
    with pytest.raises(ValueError, match="scale must be positive"):
        generate(
            GenerationConfig(
                "live_strategy",
                42,
                date(2026, 1, 1),
                180,
                0,
                Path("data/raw"),
            )
        )
