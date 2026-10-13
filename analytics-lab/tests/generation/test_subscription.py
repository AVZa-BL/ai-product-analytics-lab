from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.subscription import generate


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        "subscription",
        seed,
        date(2026, 1, 1),
        180,
        1000,
        Path("data/raw"),
    )


def test_generate_is_deterministic_for_the_same_config() -> None:
    first = generate(config())
    second = generate(config())

    assert set(first) == {
        "subscription_users",
        "subscription_onboarding_events",
        "subscription_product_events",
        "subscription_lifecycle_events",
        "subscription_payments",
        "subscription_marketing_spend",
        "subscription_support_tickets",
        "subscription_generation_controls",
    }
    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_generated_foreign_keys_and_designed_failure_evidence_are_present() -> None:
    tables = generate(config())
    users = set(tables["subscription_users"].user_id)
    controls = tables["subscription_generation_controls"].set_index(
        "control_name"
    ).expected_value

    assert set(tables["subscription_lifecycle_events"].user_id) <= users
    assert set(tables["subscription_payments"].user_id) <= users
    assert tables["subscription_lifecycle_events"].duplicated("webhook_id").sum() > 0
    assert tables["subscription_users"].campaign_id.isna().any()
    assert set(tables["subscription_product_events"].event_name) >= {
        "activation_completed",
        "activated",
        "onboarding_complete",
    }
    assert 0.15 <= float(controls["trial_start_rate"]) <= 0.21
    assert float(controls["duplicate_webhook_rows"]) > 0
    assert float(controls["late_cancellation_rows"]) > 0
    assert float(controls["payment_failure_trial_rate"]) >= 0.03


def test_invalid_generator_config_fails_loudly() -> None:
    with pytest.raises(ValueError, match="days must be positive"):
        generate(
            GenerationConfig(
                "subscription",
                42,
                date(2026, 1, 1),
                0,
                1000,
                Path("data/raw"),
            )
        )
