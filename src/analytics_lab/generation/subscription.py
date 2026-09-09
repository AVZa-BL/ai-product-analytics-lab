from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from analytics_lab.generation.base import GenerationConfig


def _frame(rows: list[dict[str, object]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def generate(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    """Generate deterministic, synthetic subscription analytics evidence."""
    if config.scenario != "subscription":
        raise ValueError("scenario must be subscription")
    if config.days <= 0:
        raise ValueError("days must be positive")
    if config.scale <= 0:
        raise ValueError("scale must be positive")

    rng = np.random.default_rng(config.seed)
    user_count = config.scale
    start = pd.Timestamp(config.start_date, tz="UTC")
    user_ids = [f"sub_user_{index:06d}" for index in range(1, user_count + 1)]
    signup_offsets = rng.integers(0, config.days, size=user_count)
    signup_seconds = rng.integers(0, 86_400, size=user_count)
    signup_at = [
        start + timedelta(days=int(day), seconds=int(second))
        for day, second in zip(signup_offsets, signup_seconds, strict=True)
    ]

    channels = np.array(["paid_social", "paid_search", "organic", "partner"])
    channel = rng.choice(channels, size=user_count, p=[0.34, 0.26, 0.30, 0.10])
    campaign_lookup = {
        "paid_social": "campaign_social_01",
        "paid_search": "campaign_search_01",
        "organic": "campaign_organic",
        "partner": "campaign_partner_01",
    }
    campaign_id: list[object] = [campaign_lookup[item] for item in channel]
    missing_campaign_count = max(1, round(user_count * 0.06))
    for index in rng.choice(user_count, size=missing_campaign_count, replace=False):
        campaign_id[int(index)] = None

    users = pd.DataFrame(
        {
            "user_id": user_ids,
            "signup_at": signup_at,
            "country_code": rng.choice(["DE", "US", "GB", "ES"], user_count),
            "platform": rng.choice(["ios", "android", "web"], user_count),
            "campaign_id": campaign_id,
            "acquisition_channel": channel,
        }
    ).sort_values("user_id", ignore_index=True)

    onboarding_rows: list[dict[str, object]] = []
    for index, (user_id, signed_up_at) in enumerate(
        zip(user_ids, signup_at, strict=True), start=1
    ):
        occurred_at = signed_up_at + timedelta(minutes=int(rng.integers(1, 31)))
        onboarding_rows.append(
            {
                "onboarding_event_id": f"onboarding_{index:06d}",
                "user_id": user_id,
                "event_name": "onboarding_started",
                "occurred_at": occurred_at,
                "ingested_at": occurred_at
                + timedelta(seconds=int(rng.integers(5, 181))),
            }
        )
    onboarding_events = _frame(
        onboarding_rows,
        [
            "onboarding_event_id",
            "user_id",
            "event_name",
            "occurred_at",
            "ingested_at",
        ],
    ).sort_values(["onboarding_event_id", "occurred_at"], ignore_index=True)

    activation_count = max(3, round(user_count * 0.48))
    activation_indices = np.sort(
        rng.choice(user_count, size=min(user_count, activation_count), replace=False)
    )
    aliases = ["activation_completed", "activated", "onboarding_complete"]
    product_rows: list[dict[str, object]] = []
    for sequence, user_index in enumerate(activation_indices, start=1):
        occurred_at = signup_at[int(user_index)] + timedelta(
            hours=int(rng.integers(1, 73))
        )
        product_rows.append(
            {
                "product_event_id": f"product_{sequence:06d}",
                "user_id": user_ids[int(user_index)],
                "event_name": aliases[(sequence - 1) % len(aliases)],
                "occurred_at": occurred_at,
                "ingested_at": occurred_at
                + timedelta(seconds=int(rng.integers(10, 601))),
            }
        )
    product_events = _frame(
        product_rows,
        [
            "product_event_id",
            "user_id",
            "event_name",
            "occurred_at",
            "ingested_at",
        ],
    ).sort_values(["product_event_id", "occurred_at"], ignore_index=True)

    trial_count = max(1, round(user_count * 0.18))
    trial_indices = np.sort(rng.choice(user_count, size=trial_count, replace=False))
    decline_day = max(1, round(config.days * 0.60))
    lifecycle_rows: list[dict[str, object]] = []
    payment_rows: list[dict[str, object]] = []
    paid_trial_indices: list[int] = []
    payment_failure_count = max(1, round(trial_count * 0.04))
    failure_positions = {
        int(item)
        for item in rng.choice(trial_count, size=payment_failure_count, replace=False)
    }
    post_decline_positions = {
        position
        for position, user_index in enumerate(trial_indices)
        if signup_offsets[int(user_index)] >= decline_day
    }
    pre_decline_positions = set(range(trial_count)) - post_decline_positions
    converted_positions: set[int] = set()
    for cohort_positions, conversion_rate in (
        (pre_decline_positions, 0.32),
        (post_decline_positions, 0.27),
    ):
        eligible_positions = sorted(cohort_positions - failure_positions)
        paid_count = min(len(eligible_positions), round(len(cohort_positions) * conversion_rate))
        if paid_count:
            converted_positions.update(
                int(item)
                for item in rng.choice(
                    eligible_positions,
                    size=paid_count,
                    replace=False,
                )
            )

    webhook_sequence = 1
    payment_sequence = 1
    for trial_position, user_index_raw in enumerate(trial_indices):
        user_index = int(user_index_raw)
        user_id = user_ids[user_index]
        subscription_id = f"subscription_{trial_position + 1:06d}"
        trial_start = signup_at[user_index] + timedelta(
            hours=int(rng.integers(0, 49))
        )
        trial_end = trial_start + timedelta(days=14)
        timezone = rng.choice(["Europe/Berlin", "America/New_York", "UTC"])
        plan_id = rng.choice(["monthly_basic", "annual_premium"])
        billing_period = "monthly" if plan_id == "monthly_basic" else "annual"

        lifecycle_rows.append(
            {
                "webhook_id": f"webhook_{webhook_sequence:07d}",
                "subscription_id": subscription_id,
                "user_id": user_id,
                "event_type": "trial_started",
                "occurred_at": trial_start,
                "effective_at": trial_start,
                "ingested_at": trial_start + timedelta(minutes=2),
                "plan_id": plan_id,
                "billing_period": billing_period,
                "trial_end_at_reported_utc": trial_end.tz_localize(None),
                "trial_timezone": timezone,
            }
        )
        webhook_sequence += 1

        converted = trial_position in converted_positions

        if trial_position in failure_positions:
            payment_rows.append(
                {
                    "payment_id": f"payment_{payment_sequence:07d}",
                    "subscription_id": subscription_id,
                    "user_id": user_id,
                    "payment_at": trial_end,
                    "amount_local": 9.99,
                    "currency_code": "USD",
                    "amount_usd": 9.99,
                    "payment_status": "failed",
                    "refund_at": pd.NaT,
                }
            )
            payment_sequence += 1
        elif converted:
            paid_trial_indices.append(trial_position)
            amount = 79.99 if billing_period == "annual" else 9.99
            lifecycle_rows.append(
                {
                    "webhook_id": f"webhook_{webhook_sequence:07d}",
                    "subscription_id": subscription_id,
                    "user_id": user_id,
                    "event_type": "paid_started",
                    "occurred_at": trial_end,
                    "effective_at": trial_end,
                    "ingested_at": trial_end + timedelta(minutes=3),
                    "plan_id": plan_id,
                    "billing_period": billing_period,
                    "trial_end_at_reported_utc": trial_end.tz_localize(None),
                    "trial_timezone": timezone,
                }
            )
            webhook_sequence += 1
            payment_rows.append(
                {
                    "payment_id": f"payment_{payment_sequence:07d}",
                    "subscription_id": subscription_id,
                    "user_id": user_id,
                    "payment_at": trial_end,
                    "amount_local": amount,
                    "currency_code": "USD",
                    "amount_usd": amount,
                    "payment_status": "succeeded",
                    "refund_at": pd.NaT,
                }
            )
            payment_sequence += 1

    late_cancellation_rows = 0
    cancellation_positions = paid_trial_indices[: max(1, len(paid_trial_indices) // 8)]
    for trial_position in cancellation_positions:
        user_index = int(trial_indices[trial_position])
        trial_start = signup_at[user_index] + timedelta(hours=1)
        effective_at = trial_start + timedelta(days=35)
        lifecycle_rows.append(
            {
                "webhook_id": f"webhook_{webhook_sequence:07d}",
                "subscription_id": f"subscription_{trial_position + 1:06d}",
                "user_id": user_ids[user_index],
                "event_type": "cancelled",
                "occurred_at": effective_at,
                "effective_at": effective_at,
                "ingested_at": effective_at + timedelta(days=3),
                "plan_id": "monthly_basic",
                "billing_period": "monthly",
                "trial_end_at_reported_utc": (
                    trial_start + timedelta(days=14)
                ).tz_localize(None),
                "trial_timezone": "Europe/Berlin",
            }
        )
        webhook_sequence += 1
        late_cancellation_rows += 1

    duplicate_count = max(1, round(len(lifecycle_rows) * 0.02))
    duplicates = [dict(row) for row in lifecycle_rows[:duplicate_count]]
    for row in duplicates:
        row["ingested_at"] = pd.Timestamp(row["ingested_at"]) + timedelta(minutes=7)
    lifecycle_rows.extend(duplicates)
    lifecycle_events = _frame(
        lifecycle_rows,
        [
            "webhook_id",
            "subscription_id",
            "user_id",
            "event_type",
            "occurred_at",
            "effective_at",
            "ingested_at",
            "plan_id",
            "billing_period",
            "trial_end_at_reported_utc",
            "trial_timezone",
        ],
    ).sort_values(["webhook_id", "ingested_at"], ignore_index=True)

    payments = _frame(
        payment_rows,
        [
            "payment_id",
            "subscription_id",
            "user_id",
            "payment_at",
            "amount_local",
            "currency_code",
            "amount_usd",
            "payment_status",
            "refund_at",
        ],
    ).sort_values(["payment_id", "payment_at"], ignore_index=True)

    campaigns = [
        ("campaign_social_01", "paid_social"),
        ("campaign_search_01", "paid_search"),
        ("campaign_partner_01", "partner"),
    ]
    spend_rows: list[dict[str, object]] = []
    spend_sequence = 1
    for day in range(config.days):
        for campaign, campaign_channel in campaigns:
            spend_rows.append(
                {
                    "spend_id": f"spend_{spend_sequence:07d}",
                    "spend_date": config.start_date + timedelta(days=day),
                    "campaign_id": campaign,
                    "channel": campaign_channel,
                    "country_code": "DE",
                    "spend_usd": round(float(rng.uniform(75, 250)), 2),
                }
            )
            spend_sequence += 1
    marketing_spend = _frame(
        spend_rows,
        [
            "spend_id",
            "spend_date",
            "campaign_id",
            "channel",
            "country_code",
            "spend_usd",
        ],
    ).sort_values(["spend_id", "spend_date"], ignore_index=True)

    ticket_count = max(1, round(user_count * 0.08))
    ticket_indices = np.sort(rng.choice(user_count, size=ticket_count, replace=False))
    ticket_rows = []
    for sequence, user_index_raw in enumerate(ticket_indices, start=1):
        user_index = int(user_index_raw)
        ticket_rows.append(
            {
                "ticket_id": f"ticket_{sequence:06d}",
                "user_id": user_ids[user_index],
                "created_at": signup_at[user_index]
                + timedelta(days=int(rng.integers(1, 31))),
                "ticket_category": rng.choice(
                    ["billing", "cancellation", "product", "account"]
                ),
                "ticket_status": rng.choice(["open", "resolved"]),
            }
        )
    support_tickets = _frame(
        ticket_rows,
        [
            "ticket_id",
            "user_id",
            "created_at",
            "ticket_category",
            "ticket_status",
        ],
    ).sort_values(["ticket_id", "created_at"], ignore_index=True)

    controls = _frame(
        [
            {
                "control_name": "trial_start_rate",
                "expected_value": trial_count / user_count,
                "description": "Realized share of synthetic users starting a trial.",
            },
            {
                "control_name": "duplicate_webhook_rows",
                "expected_value": lifecycle_events.duplicated("webhook_id").sum(),
                "description": "Duplicate raw webhook rows intentionally emitted.",
            },
            {
                "control_name": "late_cancellation_rows",
                "expected_value": late_cancellation_rows,
                "description": "Cancellations ingested after their effective timestamp.",
            },
            {
                "control_name": "payment_failure_trial_rate",
                "expected_value": payment_failure_count / trial_count,
                "description": "Realized share of trials with a failed first payment.",
            },
            {
                "control_name": "pre_decline_trial_to_paid_rate",
                "expected_value": (
                    len(converted_positions & pre_decline_positions)
                    / len(pre_decline_positions)
                    if pre_decline_positions
                    else 0.0
                ),
                "description": "Realized paid conversion before the designed decline.",
            },
            {
                "control_name": "post_decline_trial_to_paid_rate",
                "expected_value": (
                    len(converted_positions & post_decline_positions)
                    / len(post_decline_positions)
                    if post_decline_positions
                    else 0.0
                ),
                "description": "Realized paid conversion after the designed decline.",
            },
        ],
        ["control_name", "expected_value", "description"],
    ).sort_values("control_name", ignore_index=True)

    return {
        "subscription_users": users,
        "subscription_onboarding_events": onboarding_events,
        "subscription_product_events": product_events,
        "subscription_lifecycle_events": lifecycle_events,
        "subscription_payments": payments,
        "subscription_marketing_spend": marketing_spend,
        "subscription_support_tickets": support_tickets,
        "subscription_generation_controls": controls,
    }
