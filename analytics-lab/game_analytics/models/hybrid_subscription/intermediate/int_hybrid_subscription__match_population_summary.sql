with population_totals as (
    select count(*) as candidate_player_count,
        count(*) filter (where not is_population_eligible) as excluded_player_count,
        count(*) filter (where exclusion_reason = 'invalid_player_identity')
            as invalid_player_identity_count,
        count(*) filter (where exclusion_reason = 'invalid_matching_covariates')
            as invalid_matching_covariates_count,
        count(*) filter (where exclusion_reason = 'no_eligible_exposure')
            as no_eligible_exposure_count,
        count(*) filter (where exclusion_reason = 'subscription_not_after_exposure')
            as subscription_not_after_exposure_count,
        count(*) filter (where exclusion_reason = 'missing_or_invalid_source_watermark')
            as missing_or_invalid_source_watermark_count,
        count(*) filter (where exclusion_reason = 'immature_pre_window')
            as immature_pre_window_count,
        count(*) filter (where exclusion_reason = 'immature_post_window')
            as immature_post_window_count,
        count(*) filter (where exclusion_reason = 'ingestion_watermark_not_mature')
            as ingestion_watermark_not_mature_count
    from {{ ref('int_hybrid_subscription__analysis_population') }}
),
eligible_totals as (
    select
        count(*) filter (where is_subscriber) as eligible_subscriber_count,
        count(*) filter (where not is_subscriber) as eligible_control_count
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
    where analysis_period = 'pre'
),
matched_totals as (
    select count(*) as matched_pair_count
    from {{ ref('int_hybrid_subscription__matched_pairs') }}
),
subscriber_balance as (
    -- Matching without replacement can exhaust the control pool stratum by stratum.
    -- Which subscribers then go unmatched is decided by the deterministic
    -- pre_session_count ordering, not at random, so unmatched counts alone do not
    -- describe the selection. Publish the baseline of each arm as governed evidence.
    select
        avg(pre.session_count) filter (where paired.subscriber_player_id is not null)
            as mean_matched_subscriber_pre_session_count,
        avg(pre.session_count) filter (where paired.subscriber_player_id is null)
            as mean_unmatched_subscriber_pre_session_count,
        var_samp(pre.session_count) filter (where paired.subscriber_player_id is not null)
            as matched_pre_session_count_variance,
        var_samp(pre.session_count) filter (where paired.subscriber_player_id is null)
            as unmatched_pre_session_count_variance
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }} pre
    left join (
        select distinct subscriber_player_id
        from {{ ref('int_hybrid_subscription__matched_pairs') }}
    ) paired on pre.player_id = paired.subscriber_player_id
    where pre.analysis_period = 'pre' and pre.is_subscriber
)
-- Both ungrouped aggregates return one row even when their inputs are empty.
-- Keep population totals queryable without manufacturing a matched-pair row.
select
    population.*,
    eligible.eligible_subscriber_count,
    eligible.eligible_control_count,
    matched.matched_pair_count,
    eligible.eligible_subscriber_count - matched.matched_pair_count
        as unmatched_subscriber_count,
    eligible.eligible_control_count - matched.matched_pair_count
        as unmatched_control_count,
    balance.mean_matched_subscriber_pre_session_count,
    balance.mean_unmatched_subscriber_pre_session_count,
    balance.mean_unmatched_subscriber_pre_session_count
        - balance.mean_matched_subscriber_pre_session_count
        as pre_session_count_selection_gap,
    -- Pooled-standard-deviation standardized mean difference. NULL whenever it is
    -- undefined: an empty arm, a single-member arm, or zero pooled variance. Never
    -- zero, which would read as balance achieved.
    (balance.mean_unmatched_subscriber_pre_session_count
        - balance.mean_matched_subscriber_pre_session_count)
        / nullif(
            sqrt(
                (balance.matched_pre_session_count_variance
                    + balance.unmatched_pre_session_count_variance) / 2.0
            ),
            0
        ) as pre_session_count_standardized_mean_difference
from eligible_totals eligible
cross join matched_totals matched
cross join population_totals population
cross join subscriber_balance balance
