from __future__ import annotations

import hashlib
from collections.abc import Iterable

import numpy as np
import pandas as pd

from analytics_lab.generation.base import GenerationConfig

TABLE_NAMES = (
    "players",
    "sessions",
    "subscription_events",
    "store_transactions",
    "currency_ledger",
    "live_event_participation",
    "marketing_exposures",
    "product_catalogue",
)


def _ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}_{index:07d}" for index in range(1, count + 1)]


def _spread_times(
    rng: np.random.Generator,
    lower: pd.Timestamp,
    upper: pd.Timestamp,
    count: int,
) -> pd.DatetimeIndex:
    if count == 0:
        return pd.DatetimeIndex([], tz="UTC")
    seconds = max(1, int((upper - lower).total_seconds()))
    return pd.DatetimeIndex(
        lower + pd.to_timedelta(rng.integers(0, seconds, count), unit="s")
    )


def _timestamp_evidence(
    prefix: str,
    utc_values: Iterable[pd.Timestamp],
    timezone: str,
) -> dict[str, object]:
    utc = pd.DatetimeIndex(utc_values)
    if utc.tz is None:
        utc = utc.tz_localize("UTC")
    else:
        utc = utc.tz_convert("UTC")
    local = utc.tz_convert(timezone)
    return {
        f"{prefix}_raw": local.strftime("%Y-%m-%dT%H:%M:%S%z"),
        f"{prefix}_local": local.tz_localize(None),
        f"{prefix}_timezone": timezone,
        f"{prefix}_utc": utc,
    }


def _finish(frame: pd.DataFrame, run_id: str) -> pd.DataFrame:
    frame["scenario_run_id"] = run_id
    return frame.reset_index(drop=True)


def generate(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    if config.scenario != "hybrid_subscription":
        raise ValueError("scenario must be hybrid_subscription")

    rng = np.random.default_rng(config.seed)
    start = pd.Timestamp(config.start_date, tz="UTC")
    end = start + pd.Timedelta(days=config.days)
    run_key = (
        f"{config.scenario}:{config.seed}:{config.start_date}:"
        f"{config.days}:{config.scale}"
    )
    run_id = hashlib.sha256(run_key.encode()).hexdigest()[:16]

    player_ids = np.asarray(_ids("player", config.scale))
    shuffled = rng.permutation(player_ids)
    prior_payer_count = max(1, round(config.scale * 0.35))
    prior_payers = set(shuffled[:prior_payer_count])
    players = _players(rng, player_ids, prior_payers, start, run_id)

    subscriber_ids: list[str] = []
    for status in ("prior_payer", "prior_nonpayer"):
        candidates = players.loc[
            players.prior_payer_status.eq(status), "player_id"
        ].to_numpy()
        count = max(1, round(len(candidates) * 0.40))
        subscriber_ids.extend(rng.choice(candidates, count, replace=False))
    subscriber_ids = sorted(subscriber_ids)

    launch_at = start + pd.Timedelta(days=max(1, config.days // 2))
    max_jitter = max(1, min(5, config.days // 10))
    start_map = {
        player_id: launch_at
        + pd.Timedelta(days=int(rng.integers(-max_jitter, max_jitter + 1)))
        for player_id in subscriber_ids
    }
    catalogue = _product_catalogue(run_id)
    subscription_events = _subscription_events(
        rng, start_map, end, run_id
    )
    store_transactions = _store_transactions(
        rng,
        players,
        start_map,
        start,
        end,
        run_id,
    )

    tables = {
        "players": players,
        "sessions": _sessions(rng, players, start_map, launch_at, start, end, run_id),
        "subscription_events": subscription_events,
        "store_transactions": store_transactions,
        "currency_ledger": _currency_ledger(
            rng, store_transactions, run_id
        ),
        "live_event_participation": _live_event_participation(
            rng, players, start_map, launch_at, start, end, run_id
        ),
        "marketing_exposures": _marketing_exposures(
            rng, players, start_map, launch_at, run_id
        ),
        "product_catalogue": catalogue,
    }
    return {name: tables[name] for name in TABLE_NAMES}


def _players(
    rng: np.random.Generator,
    player_ids: np.ndarray,
    prior_payers: set[str],
    start: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    count = len(player_ids)
    acquired = _spread_times(
        rng, start - pd.Timedelta(days=120), start - pd.Timedelta(days=30), count
    )
    frame = pd.DataFrame(
        {
            "player_id": player_ids,
            "country_code": rng.choice(
                ["US", "DE", "GB", "CA"], count, p=[0.45, 0.20, 0.20, 0.15]
            ),
            "platform": rng.choice(["ios", "android"], count),
            "acquisition_channel": rng.choice(
                ["organic", "paid_social", "search"], count
            ),
            "prior_payer_status": [
                "prior_payer" if player_id in prior_payers else "prior_nonpayer"
                for player_id in player_ids
            ],
            "acquired_at_utc": acquired,
        }
    )
    return _finish(frame, run_id)


def _product_catalogue(run_id: str) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "sku": [
                "sub_monthly",
                "currency_bundle_small",
                "currency_bundle_large",
                "reward_track_premium",
            ],
            "product_type": [
                "subscription",
                "currency",
                "currency",
                "reward_track",
            ],
            "list_price_usd": [9.99, 1.99, 9.99, 4.99],
            "subscriber_discount_rate": [0.00, 0.10, 0.10, 1.00],
            "currency_code": ["USD"] * 4,
        }
    )
    return _finish(frame, run_id)


def _subscription_events(
    rng: np.random.Generator,
    start_map: dict[str, pd.Timestamp],
    end: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    subscriber_ids = np.asarray(sorted(start_map))
    cancel_count = max(1, round(len(subscriber_ids) * 0.12))
    canceled = set(rng.choice(subscriber_ids, cancel_count, replace=False))

    for player_id in subscriber_ids:
        started_at = start_map[player_id]
        period_end = started_at + pd.Timedelta(days=30)
        rows.append(
            {
                "player_id": player_id,
                "event_type": "started",
                "current_period_end_at_utc": period_end,
                "auto_renew_enabled": True,
                "occurred_at": started_at,
            }
        )
        if player_id in canceled:
            rows.append(
                {
                    "player_id": player_id,
                    "event_type": "canceled",
                    "current_period_end_at_utc": period_end,
                    "auto_renew_enabled": False,
                    "occurred_at": started_at + pd.Timedelta(days=18),
                }
            )
            if period_end < end:
                rows.append(
                    {
                        "player_id": player_id,
                        "event_type": "expired",
                        "current_period_end_at_utc": period_end,
                        "auto_renew_enabled": False,
                        "occurred_at": period_end,
                    }
                )
        elif period_end < end:
            rows.append(
                {
                    "player_id": player_id,
                    "event_type": "renewed",
                    "current_period_end_at_utc": period_end + pd.Timedelta(days=30),
                    "auto_renew_enabled": True,
                    "occurred_at": period_end,
                }
            )

    frame = pd.DataFrame(rows)
    occurred = pd.DatetimeIndex(frame.pop("occurred_at"))
    frame.insert(0, "subscription_event_id", _ids("subevt", len(frame)))
    frame = frame.assign(
        **_timestamp_evidence("occurred_at", occurred, "UTC"),
        ingested_at_utc=occurred + pd.Timedelta(minutes=3),
    )
    return _finish(frame, run_id)


def _window_bounds(
    anchor: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    window = min(pd.Timedelta(days=28), (end - start) / 3)
    pre_start = max(start, anchor - window)
    post_end = min(end, anchor + window)
    return pre_start, anchor, anchor, post_end


def _sessions(
    rng: np.random.Generator,
    players: pd.DataFrame,
    start_map: dict[str, pd.Timestamp],
    launch_at: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for player_id in players.player_id:
        anchor = start_map.get(player_id, launch_at)
        pre_start, pre_end, post_start, post_end = _window_bounds(anchor, start, end)
        is_subscriber = player_id in start_map
        for period, lower, upper, count in (
            ("pre", pre_start, pre_end, 8 if is_subscriber else 7),
            ("post", post_start, post_end, 11 if is_subscriber else 7),
        ):
            for timestamp in _spread_times(rng, lower, upper, count):
                rows.append(
                    {
                        "player_id": player_id,
                        "analysis_period": period,
                        "duration_seconds": int(rng.integers(180, 5_401)),
                        "started_at": timestamp,
                    }
                )

    frame = pd.DataFrame(rows)
    times = pd.DatetimeIndex(frame.pop("started_at"))
    frame.insert(0, "session_id", _ids("session", len(frame)))
    frame = frame.assign(
        **_timestamp_evidence("started_at", times, "America/Los_Angeles"),
        ingested_at_utc=times + pd.Timedelta(minutes=5),
    )
    return _finish(frame, run_id)


def _store_transactions(
    rng: np.random.Generator,
    players: pd.DataFrame,
    start_map: dict[str, pd.Timestamp],
    start: pd.Timestamp,
    end: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for player in players.itertuples(index=False):
        player_id = player.player_id
        anchor = start_map.get(player_id, start + (end - start) / 2)
        pre_start, pre_end, post_start, post_end = _window_bounds(anchor, start, end)
        is_subscriber = player_id in start_map

        if is_subscriber:
            rows.append(
                {
                    "player_id": player_id,
                    "sku": "sub_monthly",
                    "product_type": "subscription",
                    "transaction_status": "succeeded",
                    "gross_amount_usd": 9.99,
                    "discount_amount_usd": 0.0,
                    "refund_amount_usd": 0.0,
                    "amount_usd": 9.99,
                    "transaction_at": anchor,
                }
            )

        if player.prior_payer_status == "prior_payer":
            pre_count = 4 if is_subscriber else 3
            post_count = 1 if is_subscriber else 3
        else:
            pre_count = 1
            post_count = 1

        for lower, upper, count, is_post in (
            (pre_start, pre_end, pre_count, False),
            (post_start, post_end, post_count, True),
        ):
            for timestamp in _spread_times(rng, lower, upper, count):
                sku = str(rng.choice(["currency_bundle_small", "currency_bundle_large"]))
                gross = 1.99 if sku.endswith("small") else 9.99
                discount = round(gross * 0.10, 2) if is_subscriber and is_post else 0.0
                rows.append(
                    {
                        "player_id": player_id,
                        "sku": sku,
                        "product_type": "currency",
                        "transaction_status": "succeeded",
                        "gross_amount_usd": gross,
                        "discount_amount_usd": discount,
                        "refund_amount_usd": 0.0,
                        "amount_usd": round(gross - discount, 2),
                        "transaction_at": timestamp,
                    }
                )

    frame = pd.DataFrame(rows)
    times = pd.DatetimeIndex(frame.pop("transaction_at"))
    frame.insert(0, "transaction_id", _ids("transaction", len(frame)))
    frame = frame.assign(
        currency_code="USD",
        **_timestamp_evidence("transaction_at", times, "Europe/Berlin"),
        ingested_at_utc=times + pd.Timedelta(minutes=2),
    )

    duplicate_count = max(1, round(len(frame) * 0.015))
    duplicate_indexes = rng.choice(frame.index, duplicate_count, replace=False)
    duplicates = frame.loc[duplicate_indexes].copy()
    duplicates["ingested_at_utc"] += pd.Timedelta(minutes=15)
    frame = pd.concat([frame, duplicates], ignore_index=True).sort_values(
        ["transaction_id", "ingested_at_utc"], kind="stable"
    )
    return _finish(frame, run_id)


def _currency_ledger(
    rng: np.random.Generator,
    transactions: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    canonical = transactions.drop_duplicates("transaction_id", keep="first")
    rows: list[dict[str, object]] = []
    for transaction in canonical.itertuples(index=False):
        if transaction.product_type == "subscription":
            entry_type = "subscription_grant"
            amount = 500
            source = transaction.transaction_id
        elif transaction.product_type == "currency":
            entry_type = "purchase_grant"
            amount = 100 if transaction.sku.endswith("small") else 650
            source = None
        else:
            continue
        rows.append(
            {
                "player_id": transaction.player_id,
                "entry_type": entry_type,
                "currency_amount": amount,
                "source_subscription_transaction_id": source,
                "occurred_at": transaction.transaction_at_utc,
            }
        )

    subscription_indexes = [
        index for index, row in enumerate(rows) if row["entry_type"] == "subscription_grant"
    ]
    missing_count = max(1, round(len(subscription_indexes) * 0.08))
    for index in rng.choice(subscription_indexes, missing_count, replace=False):
        rows[int(index)]["source_subscription_transaction_id"] = None

    frame = pd.DataFrame(rows)
    times = pd.DatetimeIndex(frame.pop("occurred_at"))
    frame.insert(0, "ledger_entry_id", _ids("ledger", len(frame)))
    frame = frame.assign(
        **_timestamp_evidence("occurred_at", times, "UTC"),
        ingested_at_utc=times + pd.Timedelta(minutes=4),
    )
    return _finish(frame, run_id)


def _live_event_participation(
    rng: np.random.Generator,
    players: pd.DataFrame,
    start_map: dict[str, pd.Timestamp],
    launch_at: pd.Timestamp,
    start: pd.Timestamp,
    end: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for player_id in players.player_id:
        anchor = start_map.get(player_id, launch_at)
        pre_start, pre_end, post_start, post_end = _window_bounds(anchor, start, end)
        is_subscriber = player_id in start_map
        for period, lower, upper, count in (
            ("pre", pre_start, pre_end, 1),
            ("post", post_start, post_end, 3 if is_subscriber else 1),
        ):
            for timestamp in _spread_times(rng, lower, upper, count):
                rows.append(
                    {
                        "player_id": player_id,
                        "live_event_id": str(rng.choice(["raid_01", "league_01"])),
                        "analysis_period": period,
                        "score": int(rng.integers(1, 10_001)),
                        "participated_at": timestamp,
                    }
                )

    frame = pd.DataFrame(rows)
    times = pd.DatetimeIndex(frame.pop("participated_at"))
    frame.insert(0, "participation_id", _ids("participation", len(frame)))
    frame = frame.assign(
        **_timestamp_evidence("participated_at", times, "UTC"),
        ingested_at_utc=times + pd.Timedelta(minutes=6),
    )
    return _finish(frame, run_id)


def _marketing_exposures(
    rng: np.random.Generator,
    players: pd.DataFrame,
    start_map: dict[str, pd.Timestamp],
    launch_at: pd.Timestamp,
    run_id: str,
) -> pd.DataFrame:
    subscriber_ids = np.asarray(sorted(start_map))
    late_count = max(1, round(len(subscriber_ids) * 0.05))
    late_subscribers = set(rng.choice(subscriber_ids, late_count, replace=False))
    rows: list[dict[str, object]] = []
    for player_id in players.player_id:
        if player_id in start_map:
            delta = 1 if player_id in late_subscribers else -2
            exposed_at = start_map[player_id] + pd.Timedelta(days=delta)
        else:
            exposed_at = launch_at - pd.Timedelta(
                days=int(rng.integers(1, 15))
            )
        rows.append(
            {
                "player_id": player_id,
                "campaign_id": "subscription_launch",
                "experiment_arm": str(rng.choice(["control", "offer"])),
                "channel": str(rng.choice(["in_game", "email", "paid_social"])),
                "exposed_at": exposed_at,
            }
        )

    frame = pd.DataFrame(rows)
    times = pd.DatetimeIndex(frame.pop("exposed_at"))
    frame.insert(0, "exposure_id", _ids("exposure", len(frame)))
    frame = frame.assign(
        **_timestamp_evidence("exposed_at", times, "UTC"),
        ingested_at_utc=times + pd.Timedelta(minutes=7),
    )
    return _finish(frame, run_id)

