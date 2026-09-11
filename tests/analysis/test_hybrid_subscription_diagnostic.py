import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics_lab.analysis.hybrid_subscription_diagnostic import (
    bootstrap_intervals,
    engagement_summary,
    population_summary,
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


@pytest.mark.parametrize(
    "column",
    ["pair_id", "subscriber_player_id", "control_player_id"],
)
def test_empty_pair_identity_values_are_rejected(matched_pairs: pd.DataFrame, column: str) -> None:
    malformed = matched_pairs.copy()
    malformed.loc[0, column] = ""

    with pytest.raises(ValueError, match="pair identity"):
        engagement_summary(malformed)


def test_pair_id_must_match_arm_identity(matched_pairs: pd.DataFrame) -> None:
    malformed = matched_pairs.copy()
    malformed.loc[0, "pair_id"] = "invented-pair"

    with pytest.raises(ValueError, match="pair identity"):
        engagement_summary(malformed)


def test_disagreeing_matching_covariates_are_rejected(
    matched_pairs: pd.DataFrame,
) -> None:
    malformed = matched_pairs.copy()
    malformed.loc[0, "control_platform"] = "mobile"

    with pytest.raises(ValueError, match="matching covariates"):
        revenue_summary(malformed)


@pytest.mark.parametrize("arm", ["subscriber", "control"])
def test_missing_matching_covariates_are_rejected(matched_pairs: pd.DataFrame, arm: str) -> None:
    malformed = matched_pairs.copy()
    for column in ("subscriber_platform", "control_platform"):
        malformed[column] = malformed[column].astype("string")
    malformed.loc[0, f"{arm}_platform"] = pd.NA

    with pytest.raises(ValueError, match="matching covariates"):
        revenue_summary(malformed)


def test_empty_pair_population_has_no_estimate(matched_pairs: pd.DataFrame) -> None:
    assert (
        engagement_summary(matched_pairs.iloc[0:0])["engagement_difference_in_differences"] is None
    )


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
    reconcile_published_inputs(matched_pairs, engagement_inputs, cannibalization_inputs)


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


def test_numeric_pair_columns_are_normalized_before_aggregation(matched_pairs):
    numeric_strings = matched_pairs.astype({"session_count_difference_in_differences": str})
    assert engagement_summary(numeric_strings)["engagement_difference_in_differences"] == 1.25


def test_valid_empty_pairs_publish_null_estimates_and_empty_intervals(
    matched_pairs, engagement_inputs, cannibalization_inputs
):
    empty = matched_pairs.iloc[:0]
    reconcile_published_inputs(empty, engagement_inputs.iloc[:0], cannibalization_inputs.iloc[:0])
    assert engagement_summary(empty)["matched_pair_count"] == 0
    assert engagement_summary(empty)["engagement_difference_in_differences"] is None
    assert revenue_summary(empty)["eligible_prior_payer_count"] == 0
    assert revenue_summary(empty)["total_revenue_difference_in_differences"] is None
    assert all(value is None for value in bootstrap_intervals(empty).values())


def test_no_prior_payer_pairs_preserve_engagement_but_skip_revenue(
    matched_pairs, engagement_inputs, cannibalization_inputs
):
    for arm in ["subscriber", "control"]:
        matched_pairs[f"{arm}_prior_payer_status"] = "prior_nonpayer"
    engagement_inputs["prior_payer_status"] = "prior_nonpayer"
    reconcile_published_inputs(matched_pairs, engagement_inputs, cannibalization_inputs.iloc[:0])
    assert revenue_summary(matched_pairs)["total_revenue_difference_in_differences"] is None
    intervals = bootstrap_intervals(matched_pairs)
    assert intervals["engagement_change_ci_95"] is not None
    assert intervals["total_revenue_difference_in_differences_ci_95"] is None


def test_malformed_empty_panel_still_fails_validation():
    with pytest.raises(ValueError, match="missing columns"):
        engagement_summary(pd.DataFrame())


def population_controls(pair_count=0):
    return pd.DataFrame(
        [
            {
                "eligible_subscriber_count": pair_count + 3,
                "eligible_control_count": pair_count,
                "matched_pair_count": pair_count,
                "unmatched_subscriber_count": 3,
                "unmatched_control_count": 0,
                "candidate_player_count": 2 * pair_count + 4,
                "excluded_player_count": 1,
                "invalid_player_identity_count": 1,
                "invalid_matching_covariates_count": 0,
                "no_eligible_exposure_count": 0,
                "subscription_not_after_exposure_count": 0,
                "missing_or_invalid_source_watermark_count": 0,
                "immature_pre_window_count": 0,
                "immature_post_window_count": 0,
                "ingestion_watermark_not_mature_count": 0,
                "source_watermarks_json": "[]",
            }
        ]
    )


def test_zero_pairs_require_independent_complete_population_counts(matched_pairs):
    pairs = matched_pairs.iloc[:0]
    result = population_summary(pairs, population_controls())
    assert result["unmatched_subscriber_count"] == 3
    assert result["invalid_player_identity_count"] == 1
    for summary in [population_controls().iloc[:0], pd.concat([population_controls()] * 2)]:
        with pytest.raises(ValueError, match="exactly one row"):
            population_summary(pairs, summary)
    for column in ["matched_pair_count", "excluded_player_count", "invalid_player_identity_count"]:
        malformed = population_controls()
        malformed[column] += 1
        with pytest.raises(ValueError, match="reconcile"):
            population_summary(pairs, malformed)


@pytest.mark.parametrize("pair_count", [0, 2])
def test_notebook_executes_empty_or_no_prior_payer_population(
    matched_pairs, engagement_inputs, cannibalization_inputs, tmp_path, monkeypatch, pair_count
):
    import duckdb

    notebook = Path(
        "notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py"
    ).resolve()
    summary = population_controls(pair_count)
    pairs = matched_pairs.iloc[:pair_count].copy()
    for arm in ["subscriber", "control"]:
        pairs[f"{arm}_prior_payer_status"] = "prior_nonpayer"
    for column in [
        "eligible_subscriber_count",
        "eligible_control_count",
        "matched_pair_count",
        "unmatched_subscriber_count",
        "unmatched_control_count",
    ]:
        pairs[column] = int(summary[column].iloc[0])
    pairs["subscriber_sequence"] = range(pair_count)
    engagement_inputs["prior_payer_status"] = "prior_nonpayer"
    frames = {
        "matched_incrementality": pairs,
        "engagement_lift_inputs": engagement_inputs.iloc[: int(pair_count > 0)],
        "cannibalization_inputs": cannibalization_inputs.iloc[:0],
        "match_population_summary": summary,
        "monthly_kpis": pd.DataFrame(
            columns=["metric_month", "is_month_complete", "mau", "total_net_revenue_usd", "arpmau"]
        ),
        "subscription_cohorts": pd.DataFrame(
            columns=[
                "cohort_type",
                "cohort_date",
                "is_conversion_mature",
                "is_d30_mature",
                "subscription_conversion_rate",
                "d30_subscriber_retention_rate",
            ]
        ),
        "data_quality_incidents": pd.DataFrame(columns=["incident_code", "affected_rows"]),
    }
    settings = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql):
            settings.append(sql)

        def sql(self, query):
            relation = query.split(" from ")[1].split()[0].split("__")[1]
            return SimpleNamespace(df=lambda: frames[relation].copy())

    monkeypatch.setattr(duckdb, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setenv("ANALYTICS_SOURCE_COMMIT", "a" * 40)
    monkeypatch.setenv("MPLBACKEND", "Agg")
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "game_analytics").mkdir()
    (tmp_path / "game_analytics/dev.duckdb").touch()
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(notebook), run_name="__main__")
    report = tmp_path / "reports/hybrid_subscription"
    result = json.loads((report / "engagement_cannibalization_diagnostic_results.json").read_text())
    assert result["population"]["matched_pair_count"] == pair_count
    assert result["population"]["unmatched_subscriber_count"] == 3
    assert result["results"]["revenue"]["total_revenue_difference_in_differences"] is None
    assert not (report / "figures/matched_pair_revenue_differences.png").exists()
    assert (report / "figures/matched_pair_session_differences.png").exists() == bool(pair_count)
    assert any("UTC" in setting for setting in settings)
