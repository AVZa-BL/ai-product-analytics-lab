from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from analytics_lab.generation.base import GenerationConfig


def _validate_config(config: GenerationConfig) -> None:
    if config.scenario != "live_strategy":
        raise ValueError("scenario must be live_strategy")
    if config.days <= 7:
        raise ValueError("days must be greater than 7")
    if config.scale <= 0:
        raise ValueError("scale must be positive")


def _update_timestamp(config: GenerationConfig) -> pd.Timestamp:
    return pd.Timestamp(config.start_date, tz="UTC") + timedelta(days=90)


def _assign_channels(
    rng: np.random.Generator, install_days: np.ndarray, update_day: int
) -> np.ndarray:
    channels = np.full(len(install_days), "organic", dtype=object)
    for mask, paid_share in (
        (install_days < update_day, 0.25),
        (install_days >= update_day, 0.45),
    ):
        indexes = np.flatnonzero(mask)
        shuffled = rng.permutation(indexes)
        paid_count = round(paid_share * len(indexes))
        search_count = round(0.15 * len(indexes))
        channels[shuffled[:paid_count]] = "paid_social"
        channels[shuffled[paid_count : paid_count + search_count]] = "paid_search"
    return channels


def _live_event_for(timestamp: pd.Timestamp, live_events: pd.DataFrame) -> str | None:
    active = live_events.loc[
        (live_events["starts_at_utc"] <= timestamp)
        & (live_events["ends_at_utc"] > timestamp),
        "live_event_id",
    ]
    return None if active.empty else str(active.iloc[0])


def generate(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    _validate_config(config)
    rng = np.random.default_rng(config.seed)
    start = pd.Timestamp(config.start_date, tz="UTC")
    update_at = _update_timestamp(config)

    player_numbers = np.arange(1, config.scale + 1)
    install_days = rng.integers(0, config.days, size=config.scale)
    install_seconds = rng.integers(0, 24 * 60 * 60, size=config.scale)
    installed_at = start + pd.to_timedelta(install_days, unit="D") + pd.to_timedelta(
        install_seconds, unit="s"
    )
    platforms = rng.choice(["android", "ios"], size=config.scale, p=[0.58, 0.42])
    countries = rng.choice(
        ["US", "DE", "GB", "FR"], size=config.scale, p=[0.40, 0.25, 0.20, 0.15]
    )
    channels = _assign_channels(rng, install_days, update_day=90)
    players = pd.DataFrame(
        {
            "player_id": [f"player_{number:06d}" for number in player_numbers],
            "installed_at_utc": installed_at,
            "platform": platforms,
            "country_code": countries,
            "acquisition_channel": channels,
            "install_app_version": np.where(installed_at < update_at, "4.11.0", "4.12.0"),
        }
    ).sort_values("player_id", ignore_index=True)

    live_events = pd.DataFrame(
        [
            {
                "live_event_id": "live_event_001",
                "event_name": "winter_campaign",
                "starts_at_utc": start + timedelta(days=20),
                "ends_at_utc": start + timedelta(days=45),
                "season_id": "season_10",
                "reward_track": "standard",
            },
            {
                "live_event_id": "live_event_002",
                "event_name": "season_update",
                "starts_at_utc": update_at,
                "ends_at_utc": start + timedelta(days=config.days),
                "season_id": "season_11",
                "reward_track": "reduced",
            },
        ]
    )

    config_starts = [
        start,
        update_at,
        start + timedelta(days=120, hours=12),
        start + timedelta(days=150, hours=18),
    ]
    config_versions = pd.DataFrame(
        {
            "config_version_id": [f"config_{index:03d}" for index in range(1, 5)],
            "effective_from_utc": config_starts,
            "effective_to_utc": config_starts[1:] + [start + timedelta(days=config.days)],
            "season_id": ["season_10", "season_11", "season_11", "season_11"],
            "upgrade_cost_multiplier": [1.00, 1.28, 1.20, 1.15],
            "event_reward_multiplier": [1.00, 0.80, 0.85, 0.90],
        }
    )

    session_rows: list[dict[str, object]] = []
    for player in players.itertuples(index=False):
        install_start = player.installed_at_utc + timedelta(minutes=5)
        session_rows.append(
            {
                "player_id": player.player_id,
                "started_at_utc": install_start,
                "ended_at_utc": install_start
                + timedelta(minutes=int(rng.integers(10, 61))),
                "app_version": player.install_app_version,
                "platform": player.platform,
            }
        )
        install_day = int((player.installed_at_utc - start).days)
        d7_probability = 0.36
        if player.acquisition_channel == "paid_social":
            d7_probability -= 0.04
        if player.installed_at_utc >= update_at:
            d7_probability -= 0.07
        if install_day <= config.days - 8 and rng.random() < d7_probability:
            d7_start = player.installed_at_utc + timedelta(
                days=7, minutes=int(rng.integers(5, 1_200))
            )
            session_rows.append(
                {
                    "player_id": player.player_id,
                    "started_at_utc": d7_start,
                    "ended_at_utc": d7_start
                    + timedelta(minutes=int(rng.integers(8, 46))),
                    "app_version": player.install_app_version,
                    "platform": player.platform,
                }
            )
    sessions = pd.DataFrame(session_rows)
    sessions.insert(
        0,
        "session_id",
        [f"session_{index:07d}" for index in range(1, len(sessions) + 1)],
    )
    missing_candidates = sessions.index[
        sessions["platform"].eq("android") & sessions["app_version"].eq("4.12.0")
    ].to_numpy()
    missing_count = round(0.35 * len(missing_candidates))
    if missing_count:
        missing_indexes = rng.choice(missing_candidates, size=missing_count, replace=False)
        sessions.loc[missing_indexes, "ended_at_utc"] = pd.NaT
    sessions = sessions.sort_values("session_id", ignore_index=True)

    event_rows: list[dict[str, object]] = []
    for session in sessions.itertuples(index=False):
        occurred_at = session.started_at_utc + timedelta(seconds=30)
        event_number = len(event_rows) + 1
        event_rows.append(
            {
                "ingestion_event_id": f"arrival_{event_number:08d}",
                "client_event_id": f"event_{event_number:08d}",
                "player_id": session.player_id,
                "session_id": session.session_id,
                "occurred_at_utc": occurred_at,
                "event_name": "session_started",
                "app_version": session.app_version,
                "platform": session.platform,
                "live_event_id": _live_event_for(occurred_at, live_events),
            }
        )

    generated_event_count = len(event_rows)
    preinstall_count = round(0.005 * generated_event_count)
    if preinstall_count:
        bad_players = rng.choice(config.scale, size=preinstall_count, replace=False)
        first_session_by_player = sessions.drop_duplicates("player_id").set_index("player_id")
        for player_index in bad_players:
            player = players.iloc[int(player_index)]
            event_number = len(event_rows) + 1
            event_rows.append(
                {
                    "ingestion_event_id": f"arrival_{event_number:08d}",
                    "client_event_id": f"event_{event_number:08d}",
                    "player_id": player.player_id,
                    "session_id": first_session_by_player.loc[player.player_id, "session_id"],
                    "occurred_at_utc": player.installed_at_utc - timedelta(hours=1),
                    "event_name": "session_started",
                    "app_version": player.install_app_version,
                    "platform": player.platform,
                    "live_event_id": None,
                }
            )

    gameplay_events = pd.DataFrame(event_rows)
    android_indexes = gameplay_events.index[gameplay_events["platform"].eq("android")].to_numpy()
    duplicate_count = round(0.06 * len(android_indexes))
    if duplicate_count:
        duplicated = gameplay_events.loc[
            rng.choice(android_indexes, size=duplicate_count, replace=False)
        ].copy()
        first_duplicate_number = len(gameplay_events) + 1
        duplicated["ingestion_event_id"] = [
            f"arrival_{number:08d}"
            for number in range(first_duplicate_number, first_duplicate_number + duplicate_count)
        ]
        gameplay_events = pd.concat([gameplay_events, duplicated], ignore_index=True)
    gameplay_events = gameplay_events.sort_values("ingestion_event_id", ignore_index=True)

    purchase_count = max(1, round(0.12 * config.scale))
    purchase_player_indexes = rng.choice(config.scale, size=purchase_count, replace=False)
    purchase_rows: list[dict[str, object]] = []
    for purchase_number, player_index in enumerate(purchase_player_indexes, start=1):
        player = players.iloc[int(player_index)]
        gross_amount = float(rng.choice([4.99, 9.99, 19.99]))
        currency_code = str(rng.choice(["USD", "EUR"], p=[0.75, 0.25]))
        purchase_rows.append(
            {
                "purchase_id": f"purchase_{purchase_number:06d}",
                "player_id": player.player_id,
                "purchased_at_utc": player.installed_at_utc + timedelta(days=3),
                "purchase_status": "completed",
                "platform_transaction_id": f"store_tx_{purchase_number:08d}",
                "product_id": str(rng.choice(["starter_pack", "gem_bundle"])),
                "gross_amount": gross_amount,
                "currency_code": currency_code,
                "gross_usd": round(gross_amount * (1.08 if currency_code == "EUR" else 1.0), 2),
            }
        )
    purchases = pd.DataFrame(purchase_rows).sort_values("purchase_id", ignore_index=True)

    snapshot_rows: list[dict[str, object]] = []
    for player in players.itertuples(index=False):
        for day, level_delta in ((1, 0), (7, 1)):
            snapshot_number = len(snapshot_rows) + 1
            post_update_penalty = 1 if player.installed_at_utc >= update_at else 0
            snapshot_rows.append(
                {
                    "snapshot_id": f"snapshot_{snapshot_number:08d}",
                    "player_id": player.player_id,
                    "snapshot_at_utc": player.installed_at_utc + timedelta(days=day),
                    "level": 2 + level_delta - post_update_penalty,
                    "power": 120 + 80 * level_delta - 20 * post_update_penalty,
                    "upgrade_attempts": 2 + 3 * level_delta + 2 * post_update_penalty,
                    "upgrade_successes": 2 + 2 * level_delta,
                }
            )
    progression_snapshots = pd.DataFrame(snapshot_rows).sort_values(
        "snapshot_id", ignore_index=True
    )

    alliance_count = max(1, config.scale // 50)
    alliances = pd.DataFrame(
        {
            "alliance_id": [f"alliance_{index:05d}" for index in range(1, alliance_count + 1)],
            "created_at_utc": [
                start + timedelta(days=index % 15) for index in range(alliance_count)
            ],
            "region": ["NA" if index % 2 == 0 else "EU" for index in range(alliance_count)],
            "leader_player_id": players["player_id"].iloc[:alliance_count].to_list(),
        }
    )

    membership_count = max(1, round(0.40 * config.scale))
    membership_player_indexes = rng.choice(config.scale, size=membership_count, replace=False)
    membership_rows: list[dict[str, object]] = []
    for membership_number, player_index in enumerate(membership_player_indexes, start=1):
        player = players.iloc[int(player_index)]
        valid_from = player.installed_at_utc + timedelta(days=2)
        membership_rows.append(
            {
                "membership_id": f"membership_{membership_number:07d}",
                "player_id": player.player_id,
                "alliance_id": alliances.iloc[(membership_number - 1) % alliance_count].alliance_id,
                "valid_from_utc": valid_from,
                "valid_to_utc": valid_from + timedelta(days=30),
                "membership_status": "active",
            }
        )
    invalid_membership_count = round(0.004 * membership_count)
    if invalid_membership_count:
        selected_memberships = rng.choice(
            len(membership_rows), size=invalid_membership_count, replace=False
        )
        for source_index in selected_memberships:
            invalid_row = membership_rows[int(source_index)].copy()
            membership_number = len(membership_rows) + 1
            invalid_row["membership_id"] = f"membership_{membership_number:07d}"
            invalid_row["valid_from_utc"] = invalid_row["valid_from_utc"] + timedelta(days=1)
            invalid_row["valid_to_utc"] = invalid_row["valid_from_utc"] - timedelta(days=1)
            membership_rows.append(invalid_row)
    alliance_memberships = pd.DataFrame(membership_rows).sort_values(
        "membership_id", ignore_index=True
    )

    battle_player_indexes = rng.choice(
        config.scale, size=max(1, round(0.60 * config.scale)), replace=False
    )
    battle_rows: list[dict[str, object]] = []
    for battle_number, player_index in enumerate(battle_player_indexes, start=1):
        player = players.iloc[int(player_index)]
        battle_rows.append(
            {
                "battle_id": f"battle_{battle_number:07d}",
                "player_id": player.player_id,
                "occurred_at_utc": player.installed_at_utc + timedelta(days=2),
                "opponent_type": str(rng.choice(["pve", "pvp"])),
                "outcome": str(rng.choice(["win", "loss"], p=[0.62, 0.38])),
                "power_delta": int(rng.integers(-50, 81)),
            }
        )
    battles = pd.DataFrame(battle_rows).sort_values("battle_id", ignore_index=True)

    ledger_rows: list[dict[str, object]] = []
    for player in players.itertuples(index=False):
        ledger_number = len(ledger_rows) + 1
        ledger_rows.append(
            {
                "ledger_entry_id": f"ledger_{ledger_number:08d}",
                "player_id": player.player_id,
                "occurred_at_utc": player.installed_at_utc + timedelta(hours=2),
                "transaction_type": "earn",
                "amount": 100.0,
                "currency_type": "soft_currency",
                "purchase_id": None,
            }
        )
    for purchase in purchases.itertuples(index=False):
        ledger_number = len(ledger_rows) + 1
        ledger_rows.append(
            {
                "ledger_entry_id": f"ledger_{ledger_number:08d}",
                "player_id": purchase.player_id,
                "occurred_at_utc": purchase.purchased_at_utc,
                "transaction_type": "purchase",
                "amount": purchase.gross_usd,
                "currency_type": "usd",
                "purchase_id": purchase.purchase_id,
            }
        )
    refund_count = max(1, round(0.20 * len(purchases)))
    refund_indexes = rng.choice(len(purchases), size=refund_count, replace=False)
    for purchase_index in refund_indexes:
        purchase = purchases.iloc[int(purchase_index)]
        ledger_number = len(ledger_rows) + 1
        ledger_rows.append(
            {
                "ledger_entry_id": f"ledger_{ledger_number:08d}",
                "player_id": purchase.player_id,
                "occurred_at_utc": purchase.purchased_at_utc + timedelta(days=5),
                "transaction_type": "refund",
                "amount": -float(purchase.gross_usd),
                "currency_type": "usd",
                "purchase_id": purchase.purchase_id,
            }
        )
    economy_transactions = pd.DataFrame(ledger_rows).sort_values(
        "ledger_entry_id", ignore_index=True
    )

    return {
        "players": players,
        "sessions": sessions,
        "gameplay_events": gameplay_events,
        "purchases": purchases,
        "progression_snapshots": progression_snapshots,
        "alliances": alliances,
        "alliance_memberships": alliance_memberships,
        "live_events": live_events.sort_values("live_event_id", ignore_index=True),
        "battles": battles,
        "economy_transactions": economy_transactions,
        "config_versions": config_versions.sort_values("config_version_id", ignore_index=True),
    }
