import pandas as pd

from analytics_lab.analysis.live_strategy_retention import (
    d7_contribution_table,
    standardized_retention,
)


def test_standardization_holds_pre_mix_constant() -> None:
    frame = pd.DataFrame(
        {
            "period": ["pre_update", "pre_update", "post_update", "post_update"],
            "retention_signal": ["robust_activity"] * 4,
            "acquisition_channel": [
                "organic",
                "paid_social",
                "organic",
                "paid_social",
            ],
            "eligible_players": [80, 20, 20, 80],
            "retained_players": [48, 8, 10, 24],
        }
    )

    assert standardized_retention(frame, "robust_activity", "pre_update") == 0.46


def test_contribution_table_accounts_for_observed_change() -> None:
    frame = pd.DataFrame(
        {
            "period": ["pre_update", "pre_update", "post_update", "post_update"],
            "retention_signal": ["robust_activity"] * 4,
            "acquisition_channel": [
                "organic",
                "paid_social",
                "organic",
                "paid_social",
            ],
            "eligible_players": [80, 20, 20, 80],
            "retained_players": [48, 8, 10, 24],
        }
    )

    contributions = d7_contribution_table(frame)

    assert round(contributions.contribution.sum(), 10) == round(
        contributions.loc[
            contributions.component.eq("observed_change"), "value"
        ].iloc[0],
        10,
    )
