from pathlib import Path

import pandas as pd

PROJECT = Path("game_analytics")
MODEL_DIR = PROJECT / "models" / "subscription"


def test_subscription_activation_mapping_is_explicit_and_complete() -> None:
    # The seed must live under seeds/subscription/ so that the path-based
    # +tags: [subscription] config in dbt_project.yml applies to it. An untagged
    # seed is not selected by the subscription selector, and every model that
    # refs it then fails to build.
    mapping_path = PROJECT / "seeds" / "subscription" / "subscription_event_name_map.csv"
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


