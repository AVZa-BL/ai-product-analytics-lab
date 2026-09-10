"""Pure calculations for the observational hybrid subscription diagnostic."""

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

MATCHING_COVARIATES = ("prior_payer_status", "platform", "acquisition_channel")
ENGAGEMENT_DIFFERENCE_COLUMNS = (
    "subscriber_session_count_change",
    "control_session_count_change",
    "session_count_difference_in_differences",
    "subscriber_liveops_participation_count_change",
    "control_liveops_participation_count_change",
    "liveops_participation_count_difference_in_differences",
)
REVENUE_DIFFERENCE_COLUMNS = (
    "subscriber_standalone_store_net_revenue_usd_change",
    "control_standalone_store_net_revenue_usd_change",
    "standalone_store_net_revenue_usd_difference_in_differences",
    "subscriber_subscription_net_revenue_usd_change",
    "control_subscription_net_revenue_usd_change",
    "subscription_net_revenue_usd_difference_in_differences",
    "subscriber_total_net_revenue_usd_change",
    "control_total_net_revenue_usd_change",
    "total_net_revenue_usd_difference_in_differences",
)
MATCHED_PAIR_COLUMNS = {
    "pair_id",
    "subscriber_player_id",
    "control_player_id",
    "matched_pair_count",
    *(f"subscriber_{column}" for column in MATCHING_COVARIATES),
    *(f"control_{column}" for column in MATCHING_COVARIATES),
    *ENGAGEMENT_DIFFERENCE_COLUMNS,
    *REVENUE_DIFFERENCE_COLUMNS,
}
PAIR_IDENTITY_COLUMNS = ("pair_id", "subscriber_player_id", "control_player_id")
PAIR_NUMERIC_COLUMNS = (
    "matched_pair_count",
    *ENGAGEMENT_DIFFERENCE_COLUMNS,
    *REVENUE_DIFFERENCE_COLUMNS,
)
POPULATION_COUNT_COLUMNS = (
    "eligible_subscriber_count",
    "eligible_control_count",
    "matched_pair_count",
    "unmatched_subscriber_count",
    "unmatched_control_count",
)
EXCLUSION_REASONS = (
    "invalid_player_identity",
    "invalid_matching_covariates",
    "no_eligible_exposure",
    "subscription_not_after_exposure",
    "missing_or_invalid_source_watermark",
    "immature_pre_window",
    "immature_post_window",
    "ingestion_watermark_not_mature",
)

ENGAGEMENT_KEYS = ("prior_payer_status", "platform", "acquisition_channel")
ENGAGEMENT_CONTROL_COLUMNS = (
    "matched_pair_count",
    "matched_subscriber_count",
    "matched_control_count",
    "subscriber_session_count_change_sum",
    "control_session_count_change_sum",
    "session_count_difference_in_differences_sum",
    "mean_subscriber_session_count_change",
    "mean_control_session_count_change",
    "mean_session_count_difference_in_differences",
    "subscriber_liveops_participation_count_change_sum",
    "control_liveops_participation_count_change_sum",
    "liveops_participation_count_difference_in_differences_sum",
    "mean_subscriber_liveops_participation_count_change",
    "mean_control_liveops_participation_count_change",
    "mean_liveops_participation_count_difference_in_differences",
)
CANNIBALIZATION_KEYS = ("prior_payer_status",)
CANNIBALIZATION_CONTROL_COLUMNS = (
    "matched_pair_count",
    "matched_subscriber_count",
    "matched_control_count",
    "subscriber_standalone_store_net_revenue_usd_change_sum",
    "control_standalone_store_net_revenue_usd_change_sum",
    "standalone_store_net_revenue_usd_difference_in_differences_sum",
    "mean_subscriber_standalone_store_net_revenue_usd_change",
    "mean_control_standalone_store_net_revenue_usd_change",
    "mean_standalone_store_net_revenue_usd_difference_in_differences",
    "subscriber_subscription_net_revenue_usd_change_sum",
    "control_subscription_net_revenue_usd_change_sum",
    "subscription_net_revenue_usd_difference_in_differences_sum",
    "mean_subscriber_subscription_net_revenue_usd_change",
    "mean_control_subscription_net_revenue_usd_change",
    "mean_subscription_net_revenue_usd_difference_in_differences",
    "subscriber_total_net_revenue_usd_change_sum",
    "control_total_net_revenue_usd_change_sum",
    "total_net_revenue_usd_difference_in_differences_sum",
    "mean_subscriber_total_net_revenue_usd_change",
    "mean_control_total_net_revenue_usd_change",
    "mean_total_net_revenue_usd_difference_in_differences",
)


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _validated_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, MATCHED_PAIR_COLUMNS, "matched incrementality")
    identity = frame.loc[:, PAIR_IDENTITY_COLUMNS].astype("string")
    if identity.isna().any().any() or any(
        identity[column].str.strip().eq("").any() for column in PAIR_IDENTITY_COLUMNS
    ):
        raise ValueError("matched incrementality must have valid pair identity")
    expected_pair_id = identity["subscriber_player_id"] + "__" + identity["control_player_id"]
    if not identity["pair_id"].eq(expected_pair_id).all():
        raise ValueError("matched incrementality must have valid pair identity")
    if frame["pair_id"].duplicated().any():
        raise ValueError("matched incrementality must have unique pair_id")
    for column in MATCHING_COVARIATES:
        subscriber_values = frame[f"subscriber_{column}"]
        control_values = frame[f"control_{column}"]
        if (
            subscriber_values.isna().any()
            or control_values.isna().any()
            or subscriber_values.astype("string").str.strip().eq("").any()
            or control_values.astype("string").str.strip().eq("").any()
            or not subscriber_values.eq(control_values).fillna(False).all()
        ):
            raise ValueError("matched pair matching covariates disagree")
    try:
        numeric_values = frame.loc[:, PAIR_NUMERIC_COLUMNS].apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError("matched incrementality values must be numeric") from error
    if not np.isfinite(numeric_values.to_numpy(dtype=float)).all():
        raise ValueError("matched incrementality values must be finite")
    normalized = frame.copy()
    for column in PAIR_NUMERIC_COLUMNS:
        normalized[column] = numeric_values[column]
    return normalized


def population_summary(pairs: pd.DataFrame, published: pd.DataFrame) -> dict[str, int]:
    """Validate the independent one-row population control, including zero pairs."""
    validated = _validated_pairs(pairs)
    columns = (
        *POPULATION_COUNT_COLUMNS,
        "candidate_player_count",
        "excluded_player_count",
        *(f"{reason}_count" for reason in EXCLUSION_REASONS),
    )
    _require_columns(published, columns, "population summary")
    if len(published) != 1:
        raise ValueError("population summary must contain exactly one row")
    try:
        counts = pd.to_numeric(published.loc[:, columns].iloc[0], errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError("population summary counts must be numeric") from error
    if (
        not np.isfinite(counts.to_numpy(dtype=float)).all()
        or (counts < 0).any()
        or not counts.eq(np.floor(counts)).all()
    ):
        raise ValueError("population summary counts must be nonnegative finite integers")
    result = {column: int(counts[column]) for column in columns}
    if result["matched_pair_count"] != len(validated):
        raise ValueError("population summary matched pair count does not reconcile")
    for arm in ("subscriber", "control"):
        if (
            result[f"eligible_{arm}_count"] != len(validated) + result[f"unmatched_{arm}_count"]
            or validated[f"{arm}_player_id"].duplicated().any()
        ):
            raise ValueError(f"population summary {arm} counts do not reconcile")
    if set(validated.subscriber_player_id) & set(validated.control_player_id):
        raise ValueError("population summary cannot reuse players across arms")
    if result["candidate_player_count"] != (
        result["eligible_subscriber_count"]
        + result["eligible_control_count"]
        + result["excluded_player_count"]
    ) or result["excluded_player_count"] != sum(result[f"{r}_count"] for r in EXCLUSION_REASONS):
        raise ValueError("population summary exclusion counts do not reconcile")
    if not validated.empty:
        _require_columns(validated, POPULATION_COUNT_COLUMNS, "matched population")
        for column in POPULATION_COUNT_COLUMNS:
            if not pd.to_numeric(validated[column], errors="raise").eq(result[column]).all():
                raise ValueError("population summary disagrees with pair-row totals")
    result["matched_prior_payer_pair_count"] = len(_prior_payer_pairs(validated))
    return result


def engagement_summary(pairs: pd.DataFrame) -> dict[str, float | int | None]:
    """Summarize observed matched-pair engagement changes without a causal claim."""
    validated = _validated_pairs(pairs)
    if validated.empty:
        return {
            "matched_pair_count": 0,
            **dict.fromkeys(
                [
                    "subscriber_session_count_change",
                    "control_session_count_change",
                    "engagement_difference_in_differences",
                    "subscriber_liveops_participation_count_change",
                    "control_liveops_participation_count_change",
                    "liveops_difference_in_differences",
                ]
            ),
        }
    return {
        "matched_pair_count": len(validated),
        "subscriber_session_count_change": float(
            validated["subscriber_session_count_change"].mean()
        ),
        "control_session_count_change": float(validated["control_session_count_change"].mean()),
        "engagement_difference_in_differences": float(
            validated["session_count_difference_in_differences"].mean()
        ),
        "subscriber_liveops_participation_count_change": float(
            validated["subscriber_liveops_participation_count_change"].mean()
        ),
        "control_liveops_participation_count_change": float(
            validated["control_liveops_participation_count_change"].mean()
        ),
        "liveops_difference_in_differences": float(
            validated["liveops_participation_count_difference_in_differences"].mean()
        ),
    }


def _prior_payer_pairs(pairs: pd.DataFrame) -> pd.DataFrame:
    prior_payers = pairs[
        pairs["subscriber_prior_payer_status"].eq("prior_payer")
        & pairs["control_prior_payer_status"].eq("prior_payer")
    ]
    return prior_payers


def revenue_summary(pairs: pd.DataFrame) -> dict[str, float | int | None]:
    """Summarize observed cash-revenue changes for matched prior-payer pairs."""
    prior_payers = _prior_payer_pairs(_validated_pairs(pairs))
    if prior_payers.empty:
        return {
            "eligible_prior_payer_count": 0,
            **dict.fromkeys(
                [
                    "subscriber_store_change",
                    "non_subscriber_store_change",
                    "standalone_store_difference_in_differences",
                    "subscriber_subscription_change",
                    "non_subscriber_subscription_change",
                    "subscription_difference_in_differences",
                    "subscriber_total_revenue_change",
                    "non_subscriber_total_revenue_change",
                    "total_revenue_difference_in_differences",
                ]
            ),
        }
    mean = prior_payers.loc[:, REVENUE_DIFFERENCE_COLUMNS].mean()
    return {
        "eligible_prior_payer_count": len(prior_payers),
        "subscriber_store_change": float(
            mean["subscriber_standalone_store_net_revenue_usd_change"]
        ),
        "non_subscriber_store_change": float(
            mean["control_standalone_store_net_revenue_usd_change"]
        ),
        "standalone_store_difference_in_differences": float(
            mean["standalone_store_net_revenue_usd_difference_in_differences"]
        ),
        "subscriber_subscription_change": float(
            mean["subscriber_subscription_net_revenue_usd_change"]
        ),
        "non_subscriber_subscription_change": float(
            mean["control_subscription_net_revenue_usd_change"]
        ),
        "subscription_difference_in_differences": float(
            mean["subscription_net_revenue_usd_difference_in_differences"]
        ),
        "subscriber_total_revenue_change": float(mean["subscriber_total_net_revenue_usd_change"]),
        "non_subscriber_total_revenue_change": float(mean["control_total_net_revenue_usd_change"]),
        "total_revenue_difference_in_differences": float(
            mean["total_net_revenue_usd_difference_in_differences"]
        ),
    }


def bootstrap_intervals(
    pairs: pd.DataFrame, *, draws: int = 2000, seed: int = 42
) -> dict[str, list[float] | None]:
    """Return deterministic intervals from whole matched-pair bootstrap samples."""
    if draws < 1:
        raise ValueError("draws must be positive")
    validated = _validated_pairs(pairs)
    unavailable = dict.fromkeys(
        [
            "engagement_change_ci_95",
            "standalone_store_difference_in_differences_ci_95",
            "total_revenue_difference_in_differences_ci_95",
        ]
    )
    if validated.empty:
        return unavailable
    prior_payers = _prior_payer_pairs(validated)
    rng = np.random.default_rng(seed)

    engagement_values = validated["session_count_difference_in_differences"].to_numpy(dtype=float)
    revenue_values = prior_payers[
        [
            "standalone_store_net_revenue_usd_difference_in_differences",
            "total_net_revenue_usd_difference_in_differences",
        ]
    ].to_numpy(dtype=float)
    estimates = np.empty((draws, 3), dtype=float)
    same_population = len(prior_payers) == len(validated)
    for draw in range(draws):
        pair_indices = rng.integers(0, len(validated), size=len(validated))
        estimates[draw, 0] = engagement_values[pair_indices].mean()
        if prior_payers.empty:
            continue
        revenue_indices = (
            pair_indices
            if same_population
            else rng.integers(0, len(prior_payers), size=len(prior_payers))
        )
        estimates[draw, 1:] = revenue_values[revenue_indices].mean(axis=0)

    if prior_payers.empty:
        bounds = np.quantile(estimates[:, 0], [0.025, 0.975])
        return {**unavailable, "engagement_change_ci_95": bounds.tolist()}
    bounds = np.quantile(estimates, [0.025, 0.975], axis=0)
    return {
        "engagement_change_ci_95": [float(bounds[0, 0]), float(bounds[1, 0])],
        "standalone_store_difference_in_differences_ci_95": [
            float(bounds[0, 1]),
            float(bounds[1, 1]),
        ],
        "total_revenue_difference_in_differences_ci_95": [
            float(bounds[0, 2]),
            float(bounds[1, 2]),
        ],
    }


def _engagement_aggregates(pairs: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        pairs.groupby(
            [f"subscriber_{column}" for column in ENGAGEMENT_KEYS],
            as_index=False,
            dropna=False,
        )
        .agg(
            matched_pair_count=("pair_id", "size"),
            matched_subscriber_count=("subscriber_player_id", "nunique"),
            matched_control_count=("control_player_id", "nunique"),
            subscriber_session_count_change_sum=(
                "subscriber_session_count_change",
                "sum",
            ),
            control_session_count_change_sum=("control_session_count_change", "sum"),
            session_count_difference_in_differences_sum=(
                "session_count_difference_in_differences",
                "sum",
            ),
            subscriber_liveops_participation_count_change_sum=(
                "subscriber_liveops_participation_count_change",
                "sum",
            ),
            control_liveops_participation_count_change_sum=(
                "control_liveops_participation_count_change",
                "sum",
            ),
            liveops_participation_count_difference_in_differences_sum=(
                "liveops_participation_count_difference_in_differences",
                "sum",
            ),
        )
        .rename(columns={f"subscriber_{column}": column for column in ENGAGEMENT_KEYS})
    )
    mean_sources = {
        "mean_subscriber_session_count_change": "subscriber_session_count_change_sum",
        "mean_control_session_count_change": "control_session_count_change_sum",
        "mean_session_count_difference_in_differences": (
            "session_count_difference_in_differences_sum"
        ),
        "mean_subscriber_liveops_participation_count_change": (
            "subscriber_liveops_participation_count_change_sum"
        ),
        "mean_control_liveops_participation_count_change": (
            "control_liveops_participation_count_change_sum"
        ),
        "mean_liveops_participation_count_difference_in_differences": (
            "liveops_participation_count_difference_in_differences_sum"
        ),
    }
    for mean_column, sum_column in mean_sources.items():
        grouped[mean_column] = grouped[sum_column] / grouped["matched_pair_count"]
    return grouped.loc[:, [*ENGAGEMENT_KEYS, *ENGAGEMENT_CONTROL_COLUMNS]]


def _cannibalization_aggregates(pairs: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        pairs.groupby("subscriber_prior_payer_status", as_index=False, dropna=False)
        .agg(
            matched_pair_count=("pair_id", "size"),
            matched_subscriber_count=("subscriber_player_id", "nunique"),
            matched_control_count=("control_player_id", "nunique"),
            subscriber_standalone_store_net_revenue_usd_change_sum=(
                "subscriber_standalone_store_net_revenue_usd_change",
                "sum",
            ),
            control_standalone_store_net_revenue_usd_change_sum=(
                "control_standalone_store_net_revenue_usd_change",
                "sum",
            ),
            standalone_store_net_revenue_usd_difference_in_differences_sum=(
                "standalone_store_net_revenue_usd_difference_in_differences",
                "sum",
            ),
            subscriber_subscription_net_revenue_usd_change_sum=(
                "subscriber_subscription_net_revenue_usd_change",
                "sum",
            ),
            control_subscription_net_revenue_usd_change_sum=(
                "control_subscription_net_revenue_usd_change",
                "sum",
            ),
            subscription_net_revenue_usd_difference_in_differences_sum=(
                "subscription_net_revenue_usd_difference_in_differences",
                "sum",
            ),
            subscriber_total_net_revenue_usd_change_sum=(
                "subscriber_total_net_revenue_usd_change",
                "sum",
            ),
            control_total_net_revenue_usd_change_sum=(
                "control_total_net_revenue_usd_change",
                "sum",
            ),
            total_net_revenue_usd_difference_in_differences_sum=(
                "total_net_revenue_usd_difference_in_differences",
                "sum",
            ),
        )
        .rename(columns={"subscriber_prior_payer_status": "prior_payer_status"})
    )
    for sum_column in [column for column in grouped if column.endswith("_sum")]:
        grouped[f"mean_{sum_column.removesuffix('_sum')}"] = (
            grouped[sum_column] / grouped["matched_pair_count"]
        )
    return grouped.loc[:, [*CANNIBALIZATION_KEYS, *CANNIBALIZATION_CONTROL_COLUMNS]]


def _reconcile_aggregate(
    expected: pd.DataFrame,
    published: pd.DataFrame,
    *,
    keys: Sequence[str],
    values: Sequence[str],
    label: str,
    tolerance: float,
) -> None:
    _require_columns(published, [*keys, *values], f"{label} inputs")
    if expected.empty and published.empty:
        return
    if published.empty:
        raise ValueError(f"{label} controls missing matched population")
    if published.duplicated(list(keys)).any():
        key_label = "matching covariates" if len(keys) > 1 else keys[0]
        raise ValueError(f"{label} inputs must have unique {key_label}")

    expected_ordered = expected.sort_values(list(keys)).reset_index(drop=True)
    published_ordered = (
        published.loc[:, [*keys, *values]].sort_values(list(keys)).reset_index(drop=True)
    )
    if not expected_ordered.loc[:, keys].equals(published_ordered.loc[:, keys]):
        raise ValueError(f"{label} controls missing matched population")
    try:
        published_values = published_ordered.loc[:, values].apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} control totals must be numeric") from error
    if not np.isfinite(published_values.to_numpy(dtype=float)).all():
        raise ValueError(f"{label} control totals must be finite")
    if not np.allclose(
        expected_ordered.loc[:, values].to_numpy(dtype=float),
        published_values.to_numpy(dtype=float),
        atol=tolerance,
        rtol=0,
    ):
        raise ValueError(f"{label} control totals do not reconcile")


def reconcile_published_inputs(
    pairs: pd.DataFrame,
    engagement_inputs: pd.DataFrame,
    cannibalization_inputs: pd.DataFrame,
    *,
    tolerance: float = 1e-9,
) -> None:
    """Raise when governed aggregate controls disagree with matched-pair rows."""
    validated = _validated_pairs(pairs)
    if not validated["matched_pair_count"].eq(len(validated)).all():
        raise ValueError("matched incrementality pair population count does not reconcile")
    _reconcile_aggregate(
        _engagement_aggregates(validated),
        engagement_inputs,
        keys=ENGAGEMENT_KEYS,
        values=ENGAGEMENT_CONTROL_COLUMNS,
        label="engagement",
        tolerance=tolerance,
    )
    _reconcile_aggregate(
        _cannibalization_aggregates(_prior_payer_pairs(validated)),
        cannibalization_inputs,
        keys=CANNIBALIZATION_KEYS,
        values=CANNIBALIZATION_CONTROL_COLUMNS,
        label="cannibalization",
        tolerance=tolerance,
    )
