"""Governed calculations for the live-strategy D7-retention diagnostic."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

INPUT_RELATION = "main_live_strategy.mart_live_strategy__d7_diagnostic_inputs"
PERIODS = ("pre_update", "post_update")


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    """Resolve relative Parquet paths in dbt-created DuckDB views safely."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def load_diagnostic_inputs(db_path: Path) -> pd.DataFrame:
    """Load the approved diagnostic mart through a read-only DuckDB connection."""
    resolved = db_path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"DuckDB database does not exist: {resolved}")

    query = f"""
        select
            install_date_utc,
            period,
            platform,
            country_code,
            acquisition_channel,
            config_version_id,
            retention_signal,
            eligible_players,
            retained_players,
            retention_rate,
            median_upgrade_attempts,
            median_progression_velocity
        from {INPUT_RELATION}
        order by
            install_date_utc,
            platform,
            country_code,
            acquisition_channel,
            config_version_id,
            retention_signal
    """
    with _working_directory(resolved.parent):
        connection = duckdb.connect(str(resolved), read_only=True)
        try:
            return connection.sql(query).df()
        finally:
            connection.close()


def _validate_frame(frame: pd.DataFrame, *, signal: str) -> pd.DataFrame:
    required = {
        "period",
        "retention_signal",
        "acquisition_channel",
        "eligible_players",
        "retained_players",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")

    subset = frame.loc[frame["retention_signal"].eq(signal)].copy()
    if subset.empty:
        raise ValueError(f"retention signal is absent: {signal}")
    if not set(PERIODS) <= set(subset["period"]):
        raise ValueError("retention signal must contain both periods")
    numeric = subset[["eligible_players", "retained_players"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("eligible_players and retained_players must be finite numbers")
    subset[["eligible_players", "retained_players"]] = numeric
    if (subset["eligible_players"] <= 0).any():
        raise ValueError("eligible_players must be positive")
    if (subset["retained_players"] < 0).any() or (
        subset["retained_players"] > subset["eligible_players"]
    ).any():
        raise ValueError("retained_players must be between zero and eligible_players")
    if subset["acquisition_channel"].isna().any():
        raise ValueError("acquisition_channel must be populated")

    channels_by_period = {
        period: set(subset.loc[subset["period"].eq(period), "acquisition_channel"])
        for period in PERIODS
    }
    if channels_by_period[PERIODS[0]] != channels_by_period[PERIODS[1]]:
        raise ValueError("every acquisition channel must be present in both periods")
    return subset


def _weighted_rate(frame: pd.DataFrame) -> float:
    eligible = float(frame["eligible_players"].sum())
    if eligible <= 0:
        raise ValueError("eligible_players must sum to a positive value")
    return float(frame["retained_players"].sum() / eligible)


def standardized_retention(frame: pd.DataFrame, signal: str, weights_from: str) -> float:
    """Return post-update retention standardized to another period's channel mix."""
    if weights_from not in PERIODS:
        raise ValueError(f"weights_from must be one of: {', '.join(PERIODS)}")
    subset = _validate_frame(frame, signal=signal)

    source = subset.loc[subset["period"].eq(weights_from)]
    weights = source.groupby("acquisition_channel")["eligible_players"].sum()
    weights = weights / weights.sum()

    post = subset.loc[subset["period"].eq("post_update")]
    post_by_channel = post.groupby("acquisition_channel").agg(
        retained_players=("retained_players", "sum"),
        eligible_players=("eligible_players", "sum"),
    )
    post_rates = post_by_channel["retained_players"] / post_by_channel["eligible_players"]
    return float((weights * post_rates).sum())


def d7_contribution_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Decompose the descriptive D7 change while isolating measurement sensitivity."""
    robust = _validate_frame(frame, signal="robust_activity")
    pre_rate = _weighted_rate(robust.loc[robust["period"].eq("pre_update")])
    post_rate = _weighted_rate(robust.loc[robust["period"].eq("post_update")])
    standardized_post = standardized_retention(frame, "robust_activity", "pre_update")

    observed_change = post_rate - pre_rate
    acquisition_mix = post_rate - standardized_post
    within_channel_change = standardized_post - pre_rate

    has_completed_signal = frame["retention_signal"].eq("completed_session").any()
    if has_completed_signal:
        if "platform" not in frame.columns:
            raise ValueError("platform is required for Android instrumentation sensitivity")
        completed = _validate_frame(frame, signal="completed_session")
        completed_android_post = completed.loc[
            completed["period"].eq("post_update")
            & completed["platform"].eq("android")
        ]
        robust_android_post = robust.loc[
            robust["period"].eq("post_update") & robust["platform"].eq("android")
        ]
        if completed_android_post.empty or robust_android_post.empty:
            raise ValueError("both retention signals require post-update Android rows")
        instrumentation = _weighted_rate(completed_android_post) - _weighted_rate(
            robust_android_post
        )
    else:
        instrumentation = np.nan

    rounding_residual = observed_change - acquisition_mix - within_channel_change
    return pd.DataFrame(
        {
            "component": [
                "observed_change",
                "acquisition_mix",
                "within_channel_change",
                "android_instrumentation_sensitivity",
                "rounding_residual",
            ],
            "value": [
                observed_change,
                acquisition_mix,
                within_channel_change,
                instrumentation,
                rounding_residual,
            ],
            "contribution": [
                0.0,
                acquisition_mix,
                within_channel_change,
                0.0,
                rounding_residual,
            ],
        }
    )


def bootstrap_difference_ci(
    frame: pd.DataFrame,
    seed: int,
    draws: int = 2_000,
) -> tuple[float, float]:
    """Bootstrap the robust post-minus-pre change over cohort rows within strata."""
    if draws <= 0:
        raise ValueError("draws must be positive")
    robust = _validate_frame(frame, signal="robust_activity")
    rng = np.random.default_rng(seed)
    strata = [
        group.reset_index(drop=True)
        for _, group in robust.groupby(["period", "acquisition_channel"], sort=True)
    ]

    differences = np.empty(draws, dtype=float)
    for draw in range(draws):
        sampled = pd.concat(
            [
                group.iloc[rng.integers(0, len(group), size=len(group))]
                for group in strata
            ],
            ignore_index=True,
        )
        pre_rate = _weighted_rate(sampled.loc[sampled["period"].eq("pre_update")])
        post_rate = _weighted_rate(sampled.loc[sampled["period"].eq("post_update")])
        differences[draw] = post_rate - pre_rate

    lower, upper = np.quantile(differences, [0.025, 0.975])
    return float(lower), float(upper)
