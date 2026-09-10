import pandas as pd
import pytest

from analytics_lab.analysis.hybrid_subscription_diagnostic import (
    bootstrap_intervals,
    engagement_summary,
    reconcile_published_inputs,
    revenue_summary,
)


@pytest.fixture
def player_behavior() -> pd.DataFrame:
    rows = [
        ("p1", "pre", True, "prior_payer", 2, 10.0, 0.0, 10.0),
        ("p1", "post", True, "prior_payer", 4, 6.0, 8.0, 14.0),
        ("p2", "pre", True, "prior_payer", 4, 20.0, 0.0, 20.0),
        ("p2", "post", True, "prior_payer", 6, 10.0, 10.0, 20.0),
        ("p3", "pre", False, "prior_payer", 3, 10.0, 0.0, 10.0),
        ("p3", "post", False, "prior_payer", 3, 12.0, 0.0, 12.0),
        ("p4", "pre", False, "prior_payer", 5, 20.0, 0.0, 20.0),
        ("p4", "post", False, "prior_payer", 4, 22.0, 0.0, 22.0),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "player_id",
            "analysis_period",
            "is_subscriber",
            "prior_payer_status",
            "session_count",
            "standalone_store_net_revenue_usd",
            "subscription_net_revenue_usd",
            "total_net_revenue_usd",
        ],
    )


def test_engagement_summary_uses_only_complete_player_pairs(
    player_behavior: pd.DataFrame,
) -> None:
    incomplete = pd.DataFrame(
        [("p5", "post", True, "prior_nonpayer", 100, 0.0, 5.0, 5.0)],
        columns=player_behavior.columns,
    )

    result = engagement_summary(pd.concat([player_behavior, incomplete]))

    assert result["paired_player_count"] == 4
    assert result["pre_sessions_per_player"] == pytest.approx(3.5)
    assert result["post_sessions_per_player"] == pytest.approx(4.25)
    assert result["absolute_change"] == pytest.approx(0.75)
    assert result["subscriber_absolute_change"] == pytest.approx(2.0)
    assert result["non_subscriber_absolute_change"] == pytest.approx(-0.5)


def test_revenue_summary_separates_store_displacement_from_total_value(
    player_behavior: pd.DataFrame,
) -> None:
    result = revenue_summary(player_behavior)

    assert result["eligible_prior_payer_count"] == 4
    assert result["subscriber_store_change"] == pytest.approx(-7.0)
    assert result["non_subscriber_store_change"] == pytest.approx(2.0)
    assert result["standalone_store_difference_in_differences"] == pytest.approx(-9.0)
    assert result["subscription_difference_in_differences"] == pytest.approx(9.0)
    assert result["total_revenue_difference_in_differences"] == pytest.approx(0.0)


def test_bootstrap_resamples_players_deterministically(
    player_behavior: pd.DataFrame,
) -> None:
    first = bootstrap_intervals(player_behavior, draws=200, seed=17)
    second = bootstrap_intervals(player_behavior, draws=200, seed=17)

    assert first == second
    assert set(first) == {
        "engagement_change_ci_95",
        "standalone_store_difference_in_differences_ci_95",
        "total_revenue_difference_in_differences_ci_95",
    }
    assert all(lower <= upper for lower, upper in first.values())


def test_reconciliation_rejects_mismatched_published_controls(
    player_behavior: pd.DataFrame,
) -> None:
    engagement_inputs = pd.DataFrame(
        [
            (period, subscriber, 2, mean)
            for period, subscriber, mean in [
                ("pre", True, 3.0),
                ("post", True, 5.0),
                ("pre", False, 4.0),
                ("post", False, 3.5),
            ]
        ],
        columns=[
            "analysis_period",
            "is_subscriber",
            "eligible_player_count",
            "mean_sessions_per_player",
        ],
    )
    cannibalization_inputs = pd.DataFrame(
        [
            ("pre", True, 2, 30.0, 0.0, 30.0),
            ("post", True, 2, 16.0, 18.0, 34.0),
            ("pre", False, 2, 30.0, 0.0, 30.0),
            ("post", False, 2, 34.0, 0.0, 34.0),
        ],
        columns=[
            "analysis_period",
            "is_subscriber",
            "eligible_player_count",
            "standalone_store_net_revenue_usd",
            "subscription_net_revenue_usd",
            "total_net_revenue_usd",
        ],
    )

    reconcile_published_inputs(
        player_behavior, engagement_inputs, cannibalization_inputs
    )
    engagement_inputs.loc[0, "mean_sessions_per_player"] = 999.0

    with pytest.raises(ValueError, match="engagement control totals"):
        reconcile_published_inputs(
            player_behavior, engagement_inputs, cannibalization_inputs
        )


def test_missing_analysis_period_is_rejected(player_behavior: pd.DataFrame) -> None:
    only_pre = player_behavior[player_behavior["analysis_period"] == "pre"]

    with pytest.raises(ValueError, match="pre and post"):
        engagement_summary(only_pre)
