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
        as unmatched_control_count
from eligible_totals eligible
cross join matched_totals matched
cross join population_totals population
