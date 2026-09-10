"""Pure calculations for the hybrid subscription diagnostic."""

from collections.abc import Iterable

import numpy as np
import pandas as pd

BEHAVIOR_COLUMNS = {
    "player_id",
    "analysis_period",
    "is_subscriber",
    "prior_payer_status",
    "session_count",
    "standalone_store_net_revenue_usd",
    "subscription_net_revenue_usd",
    "total_net_revenue_usd",
}


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _paired_rows(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, BEHAVIOR_COLUMNS, "player behavior")
    periods = set(frame["analysis_period"].dropna().unique())
    if not {"pre", "post"}.issubset(periods):
        raise ValueError("player behavior must contain pre and post periods")
    if frame.duplicated(["player_id", "analysis_period"]).any():
        raise ValueError("player behavior must have one row per player and period")

    complete_ids = (
        frame[frame["analysis_period"].isin(["pre", "post"])]
        .groupby("player_id")["analysis_period"]
        .nunique()
    )
    paired = frame[
        frame["player_id"].isin(complete_ids[complete_ids == 2].index)
        & frame["analysis_period"].isin(["pre", "post"])
    ].copy()
    if paired.empty:
        raise ValueError("player behavior has no complete pre and post pairs")
    return paired


def _period_means(frame: pd.DataFrame, value: str) -> tuple[float, float]:
    means = frame.groupby("analysis_period")[value].mean()
    return float(means["pre"]), float(means["post"])


def engagement_summary(frame: pd.DataFrame) -> dict[str, float | int | None]:
    """Summarize paired pre/post session behavior without causal interpretation."""
    paired = _paired_rows(frame)
    pre, post = _period_means(paired, "session_count")
    result: dict[str, float | int | None] = {
        "paired_player_count": int(paired["player_id"].nunique()),
        "pre_sessions_per_player": pre,
        "post_sessions_per_player": post,
        "absolute_change": post - pre,
        "relative_change": None if pre == 0 else (post - pre) / pre,
    }
    for subscriber, prefix in [(True, "subscriber"), (False, "non_subscriber")]:
        segment = paired[paired["is_subscriber"] == subscriber]
        if segment.empty:
            raise ValueError("engagement summary requires both subscriber groups")
        segment_pre, segment_post = _period_means(segment, "session_count")
        result[f"{prefix}_pre_sessions_per_player"] = segment_pre
        result[f"{prefix}_post_sessions_per_player"] = segment_post
        result[f"{prefix}_absolute_change"] = segment_post - segment_pre
    return result


def _difference_in_differences(frame: pd.DataFrame, value: str) -> tuple[float, float, float]:
    means = frame.groupby(["is_subscriber", "analysis_period"])[value].mean()
    required = {(True, "pre"), (True, "post"), (False, "pre"), (False, "post")}
    if not required.issubset(set(means.index)):
        raise ValueError("revenue summary requires both periods and subscriber groups")
    subscriber_change = float(means[(True, "post")] - means[(True, "pre")])
    non_subscriber_change = float(means[(False, "post")] - means[(False, "pre")])
    return subscriber_change, non_subscriber_change, subscriber_change - non_subscriber_change


def revenue_summary(frame: pd.DataFrame) -> dict[str, float | int]:
    """Separate prior-payer store displacement from subscription and total value."""
    paired = _paired_rows(frame)
    prior_payers = paired[paired["prior_payer_status"] == "prior_payer"]
    if prior_payers.empty:
        raise ValueError("revenue summary requires prior payers")

    store_sub, store_non_sub, store_did = _difference_in_differences(
        prior_payers, "standalone_store_net_revenue_usd"
    )
    subscription_sub, subscription_non_sub, subscription_did = (
        _difference_in_differences(prior_payers, "subscription_net_revenue_usd")
    )
    total_sub, total_non_sub, total_did = _difference_in_differences(
        prior_payers, "total_net_revenue_usd"
    )
    return {
        "eligible_prior_payer_count": int(prior_payers["player_id"].nunique()),
        "subscriber_store_change": store_sub,
        "non_subscriber_store_change": store_non_sub,
        "standalone_store_difference_in_differences": store_did,
        "subscriber_subscription_change": subscription_sub,
        "non_subscriber_subscription_change": subscription_non_sub,
        "subscription_difference_in_differences": subscription_did,
        "subscriber_total_revenue_change": total_sub,
        "non_subscriber_total_revenue_change": total_non_sub,
        "total_revenue_difference_in_differences": total_did,
    }


def bootstrap_intervals(
    frame: pd.DataFrame, *, draws: int = 2000, seed: int = 42
) -> dict[str, list[float]]:
    """Return stratified player-cluster bootstrap intervals for key estimates."""
    if draws < 1:
        raise ValueError("draws must be positive")
    paired = _paired_rows(frame)
    subscriber_by_player = paired.groupby("player_id")["is_subscriber"].nunique()
    if not subscriber_by_player.eq(1).all():
        raise ValueError("subscriber status must be stable across periods")

    metadata = paired.groupby("player_id", as_index=True).agg(
        is_subscriber=("is_subscriber", "first"),
        prior_payer_status=("prior_payer_status", "first"),
    )
    deltas = paired.pivot(
        index="player_id",
        columns="analysis_period",
        values=[
            "session_count",
            "standalone_store_net_revenue_usd",
            "total_net_revenue_usd",
        ],
    )
    player_deltas = metadata.copy()
    player_deltas["session_delta"] = (
        deltas[("session_count", "post")] - deltas[("session_count", "pre")]
    )
    player_deltas["store_delta"] = (
        deltas[("standalone_store_net_revenue_usd", "post")]
        - deltas[("standalone_store_net_revenue_usd", "pre")]
    )
    player_deltas["total_delta"] = (
        deltas[("total_net_revenue_usd", "post")]
        - deltas[("total_net_revenue_usd", "pre")]
    )

    engagement_groups = {
        bool(subscriber): group["session_delta"].to_numpy(dtype=float)
        for subscriber, group in player_deltas.groupby("is_subscriber")
    }
    prior_payers = player_deltas[
        player_deltas["prior_payer_status"] == "prior_payer"
    ]
    revenue_groups = {
        bool(subscriber): group[["store_delta", "total_delta"]].to_numpy(dtype=float)
        for subscriber, group in prior_payers.groupby("is_subscriber")
    }
    if set(engagement_groups) != {False, True} or set(revenue_groups) != {False, True}:
        raise ValueError("bootstrap requires both subscriber groups")

    rng = np.random.default_rng(seed)
    estimates = {"engagement": [], "store": [], "total": []}
    for _ in range(draws):
        engagement_samples = []
        for subscriber in [False, True]:
            values = engagement_groups[subscriber]
            engagement_samples.append(rng.choice(values, size=len(values), replace=True))
        estimates["engagement"].append(
            float(np.concatenate(engagement_samples).mean())
        )
        revenue_samples = {
            subscriber: values[
                rng.integers(0, len(values), size=len(values))
            ]
            for subscriber, values in revenue_groups.items()
        }
        estimates["store"].append(
            float(revenue_samples[True][:, 0].mean() - revenue_samples[False][:, 0].mean())
        )
        estimates["total"].append(
            float(revenue_samples[True][:, 1].mean() - revenue_samples[False][:, 1].mean())
        )

    def interval(values: list[float]) -> list[float]:
        return [float(value) for value in np.quantile(values, [0.025, 0.975])]

    return {
        "engagement_change_ci_95": interval(estimates["engagement"]),
        "standalone_store_difference_in_differences_ci_95": interval(
            estimates["store"]
        ),
        "total_revenue_difference_in_differences_ci_95": interval(
            estimates["total"]
        ),
    }


def reconcile_published_inputs(
    frame: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
    *,
    tolerance: float = 1e-9,
) -> None:
    """Raise when governed aggregate inputs disagree with the player-level fact."""
    paired = _paired_rows(frame)
    engagement_columns = {
        "analysis_period",
        "is_subscriber",
        "eligible_player_count",
        "mean_sessions_per_player",
    }
    revenue_columns = {
        "analysis_period",
        "is_subscriber",
        "eligible_player_count",
        "standalone_store_net_revenue_usd",
        "subscription_net_revenue_usd",
        "total_net_revenue_usd",
    }
    _require_columns(engagement_inputs, engagement_columns, "engagement inputs")
    _require_columns(cannibalization_inputs, revenue_columns, "cannibalization inputs")

    expected_engagement = (
        paired.groupby(["analysis_period", "is_subscriber"])
        .agg(
            eligible_player_count=("player_id", "size"),
            mean_sessions_per_player=("session_count", "mean"),
        )
        .sort_index()
    )
    published_engagement = (
        engagement_inputs.assign(
            weighted_sessions=lambda value: value["eligible_player_count"]
            * value["mean_sessions_per_player"]
        )
        .groupby(["analysis_period", "is_subscriber"])
        .agg(
            eligible_player_count=("eligible_player_count", "sum"),
            weighted_sessions=("weighted_sessions", "sum"),
        )
    )
    published_engagement["mean_sessions_per_player"] = (
        published_engagement["weighted_sessions"]
        / published_engagement["eligible_player_count"]
    )
    published_engagement = published_engagement.drop(columns="weighted_sessions").sort_index()
    if not expected_engagement.index.equals(published_engagement.index) or not np.allclose(
        expected_engagement.to_numpy(),
        published_engagement.to_numpy(),
        atol=tolerance,
        rtol=0,
    ):
        raise ValueError("engagement control totals do not reconcile")

    expected_revenue = (
        paired[paired["prior_payer_status"] == "prior_payer"]
        .groupby(["analysis_period", "is_subscriber"])
        .agg(
            eligible_player_count=("player_id", "size"),
            standalone_store_net_revenue_usd=(
                "standalone_store_net_revenue_usd",
                "sum",
            ),
            subscription_net_revenue_usd=("subscription_net_revenue_usd", "sum"),
            total_net_revenue_usd=("total_net_revenue_usd", "sum"),
        )
        .sort_index()
    )
    published_revenue = (
        cannibalization_inputs.groupby(["analysis_period", "is_subscriber"])
        .agg(
            eligible_player_count=("eligible_player_count", "sum"),
            standalone_store_net_revenue_usd=(
                "standalone_store_net_revenue_usd",
                "sum",
            ),
            subscription_net_revenue_usd=("subscription_net_revenue_usd", "sum"),
            total_net_revenue_usd=("total_net_revenue_usd", "sum"),
        )
        .sort_index()
    )
    if not expected_revenue.index.equals(published_revenue.index) or not np.allclose(
        expected_revenue.to_numpy(),
        published_revenue.to_numpy(),
        atol=tolerance,
        rtol=0,
    ):
        raise ValueError("revenue control totals do not reconcile")
