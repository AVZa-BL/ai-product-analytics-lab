import pandas as pd
import pytest

from analytics_lab.analysis.hybrid_subscription_diagnostic import (
    bootstrap_intervals,
    engagement_summary,
    reconcile_published_inputs,
    revenue_summary,
)


@pytest.fixture
def matched_pairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pair_id": "subscriber-1__control-1",
                "subscriber_player_id": "subscriber-1",
                "control_player_id": "control-1",
                "subscriber_prior_payer_status": "prior_payer",
                "control_prior_payer_status": "prior_payer",
                "subscriber_platform": "pc",
                "control_platform": "pc",
                "subscriber_acquisition_channel": "organic",
                "control_acquisition_channel": "organic",
                "matched_pair_count": 2,
                "subscriber_session_count_change": 2.0,
                "control_session_count_change": 0.0,
                "session_count_difference_in_differences": 2.0,
                "subscriber_liveops_participation_count_change": 1.0,
                "control_liveops_participation_count_change": 0.0,
                "liveops_participation_count_difference_in_differences": 1.0,
                "subscriber_standalone_store_net_revenue_usd_change": -4.0,
                "control_standalone_store_net_revenue_usd_change": 1.0,
                "standalone_store_net_revenue_usd_difference_in_differences": -5.0,
                "subscriber_subscription_net_revenue_usd_change": 6.0,
                "control_subscription_net_revenue_usd_change": 0.0,
                "subscription_net_revenue_usd_difference_in_differences": 6.0,
                "subscriber_total_net_revenue_usd_change": 2.0,
                "control_total_net_revenue_usd_change": 1.0,
                "total_net_revenue_usd_difference_in_differences": 1.0,
                "reward_track_net_revenue_usd_difference_in_differences": 100.0,
            },
            {
                "pair_id": "subscriber-2__control-2",
                "subscriber_player_id": "subscriber-2",
                "control_player_id": "control-2",
                "subscriber_prior_payer_status": "prior_payer",
                "control_prior_payer_status": "prior_payer",
                "subscriber_platform": "pc",
                "control_platform": "pc",
                "subscriber_acquisition_channel": "organic",
                "control_acquisition_channel": "organic",
                "matched_pair_count": 2,
                "subscriber_session_count_change": 1.5,
                "control_session_count_change": 1.0,
                "session_count_difference_in_differences": 0.5,
                "subscriber_liveops_participation_count_change": 0.0,
                "control_liveops_participation_count_change": 1.0,
                "liveops_participation_count_difference_in_differences": -1.0,
                "subscriber_standalone_store_net_revenue_usd_change": -2.0,
                "control_standalone_store_net_revenue_usd_change": 0.0,
                "standalone_store_net_revenue_usd_difference_in_differences": -2.0,
                "subscriber_subscription_net_revenue_usd_change": 1.0,
                "control_subscription_net_revenue_usd_change": 0.0,
                "subscription_net_revenue_usd_difference_in_differences": 1.0,
                "subscriber_total_net_revenue_usd_change": -1.0,
                "control_total_net_revenue_usd_change": 0.0,
                "total_net_revenue_usd_difference_in_differences": -1.0,
                "reward_track_net_revenue_usd_difference_in_differences": 200.0,
            },
        ]
    )


@pytest.fixture
def engagement_inputs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "prior_payer_status": "prior_payer",
                "platform": "pc",
                "acquisition_channel": "organic",
                "matched_pair_count": 2,
                "matched_subscriber_count": 2,
                "matched_control_count": 2,
                "subscriber_session_count_change_sum": 3.5,
                "control_session_count_change_sum": 1.0,
                "session_count_difference_in_differences_sum": 2.5,
                "mean_subscriber_session_count_change": 1.75,
                "mean_control_session_count_change": 0.5,
                "mean_session_count_difference_in_differences": 1.25,
                "subscriber_liveops_participation_count_change_sum": 1.0,
                "control_liveops_participation_count_change_sum": 1.0,
                "liveops_participation_count_difference_in_differences_sum": 0.0,
                "mean_subscriber_liveops_participation_count_change": 0.5,
                "mean_control_liveops_participation_count_change": 0.5,
                "mean_liveops_participation_count_difference_in_differences": 0.0,
            }
        ]
    )


@pytest.fixture
def cannibalization_inputs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "prior_payer_status": "prior_payer",
                "matched_pair_count": 2,
                "matched_subscriber_count": 2,
                "matched_control_count": 2,
                "subscriber_standalone_store_net_revenue_usd_change_sum": -6.0,
                "control_standalone_store_net_revenue_usd_change_sum": 1.0,
                "standalone_store_net_revenue_usd_difference_in_differences_sum": -7.0,
                "mean_subscriber_standalone_store_net_revenue_usd_change": -3.0,
                "mean_control_standalone_store_net_revenue_usd_change": 0.5,
                "mean_standalone_store_net_revenue_usd_difference_in_differences": -3.5,
                "subscriber_subscription_net_revenue_usd_change_sum": 7.0,
                "control_subscription_net_revenue_usd_change_sum": 0.0,
                "subscription_net_revenue_usd_difference_in_differences_sum": 7.0,
                "mean_subscriber_subscription_net_revenue_usd_change": 3.5,
                "mean_control_subscription_net_revenue_usd_change": 0.0,
                "mean_subscription_net_revenue_usd_difference_in_differences": 3.5,
                "subscriber_total_net_revenue_usd_change_sum": 1.0,
                "control_total_net_revenue_usd_change_sum": 1.0,
                "total_net_revenue_usd_difference_in_differences_sum": 0.0,
                "mean_subscriber_total_net_revenue_usd_change": 0.5,
                "mean_control_total_net_revenue_usd_change": 0.5,
                "mean_total_net_revenue_usd_difference_in_differences": 0.0,
            }
        ]
    )


def test_engagement_summary_calculates_from_real_pair_rows(
    matched_pairs: pd.DataFrame,
) -> None:
    result = engagement_summary(matched_pairs)

    assert result["matched_pair_count"] == 2
    assert result["subscriber_session_count_change"] == pytest.approx(1.75)
    assert result["control_session_count_change"] == pytest.approx(0.5)
    assert result["engagement_difference_in_differences"] == pytest.approx(1.25)
    assert result["liveops_difference_in_differences"] == pytest.approx(0.0)


def test_revenue_summary_uses_governed_cash_components_only(
    matched_pairs: pd.DataFrame,
) -> None:
    result = revenue_summary(matched_pairs)

    assert result["eligible_prior_payer_count"] == 2
    assert result["standalone_store_difference_in_differences"] == pytest.approx(-3.5)
    assert result["subscription_difference_in_differences"] == pytest.approx(3.5)
    assert result["total_revenue_difference_in_differences"] == pytest.approx(0.0)
    assert result["total_revenue_difference_in_differences"] == pytest.approx(
        result["standalone_store_difference_in_differences"]
        + result["subscription_difference_in_differences"]
    )


def test_duplicate_pair_id_is_rejected(matched_pairs: pd.DataFrame) -> None:
    duplicate = pd.concat([matched_pairs, matched_pairs.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="unique pair_id"):
        engagement_summary(duplicate)


def test_disagreeing_matching_covariates_are_rejected(
    matched_pairs: pd.DataFrame,
) -> None:
    malformed = matched_pairs.copy()
    malformed.loc[0, "control_platform"] = "mobile"

    with pytest.raises(ValueError, match="matching covariates"):
        revenue_summary(malformed)


def test_empty_pair_population_is_rejected(matched_pairs: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="no matched pairs"):
        engagement_summary(matched_pairs.iloc[0:0])


def test_bootstrap_resamples_whole_pairs_deterministically(
    matched_pairs: pd.DataFrame,
) -> None:
    first = bootstrap_intervals(matched_pairs, draws=8, seed=17)
    second = bootstrap_intervals(matched_pairs, draws=8, seed=17)

    assert first == second
    assert first == {
        "engagement_change_ci_95": [0.5, 2.0],
        "standalone_store_difference_in_differences_ci_95": [-5.0, -2.0],
        "total_revenue_difference_in_differences_ci_95": [-1.0, 1.0],
    }


def test_reconciliation_accepts_governed_pair_aggregates(
    matched_pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
) -> None:
    reconcile_published_inputs(
        matched_pairs, engagement_inputs, cannibalization_inputs
    )


def test_reconciliation_rejects_numeric_control_mismatch(
    matched_pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
) -> None:
    malformed = engagement_inputs.copy()
    malformed.loc[0, "session_count_difference_in_differences_sum"] += 1e-8

    with pytest.raises(ValueError, match="engagement control totals"):
        reconcile_published_inputs(matched_pairs, malformed, cannibalization_inputs)


def test_reconciliation_rejects_duplicate_aggregate_rows(
    matched_pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
) -> None:
    duplicate = pd.concat([engagement_inputs, engagement_inputs], ignore_index=True)

    with pytest.raises(ValueError, match="unique matching covariates"):
        reconcile_published_inputs(matched_pairs, duplicate, cannibalization_inputs)


def test_reconciliation_rejects_missing_control_population(
    matched_pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="missing matched population"):
        reconcile_published_inputs(
            matched_pairs,
            engagement_inputs.iloc[0:0],
            cannibalization_inputs,
        )


def test_reconciliation_rejects_malformed_pair_population_count(
    matched_pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
) -> None:
    malformed = matched_pairs.copy()
    malformed["matched_pair_count"] = 3

    with pytest.raises(ValueError, match="pair population count"):
        reconcile_published_inputs(malformed, engagement_inputs, cannibalization_inputs)
