with first_subscription as (
    select
        player_id,
        min(occurred_at_utc) as first_subscription_at_utc
    from {{ ref('stg_hybrid_subscription__subscription_events') }}
    where event_type = 'started'
    group by player_id
),
eligible_exposure as (
    select
        player_id,
        bool_or(is_incrementality_eligible) as has_eligible_exposure,
        min(exposed_at_utc) filter (where is_incrementality_eligible)
            as eligible_exposure_at_utc
    from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}
    group by player_id
),
observation_timestamps as (
    select started_at_utc as observed_at_utc
    from {{ ref('fct_hybrid_subscription__sessions') }}

    union all

    select transaction_at_utc as observed_at_utc
    from {{ ref('fct_hybrid_subscription__store_transactions') }}

    union all

    select participated_at_utc as observed_at_utc
    from {{ ref('stg_hybrid_subscription__live_event_participation') }}
),
observation_bounds as (
    select
        min(observed_at_utc) as observation_start_at_utc,
        max(observed_at_utc) as observation_end_at_utc
    from observation_timestamps
),
classified_population as (
    select
        player.player_id,
        player.country_code,
        player.platform,
        player.acquisition_channel,
        player.prior_payer_status,
        first_subscription.first_subscription_at_utc,
        eligible_exposure.eligible_exposure_at_utc as index_at_utc,
        first_subscription.first_subscription_at_utc is not null as is_subscriber,
        coalesce(eligible_exposure.has_eligible_exposure, false)
            as has_eligible_exposure,
        eligible_exposure.eligible_exposure_at_utc,
        observation_bounds.observation_start_at_utc,
        observation_bounds.observation_end_at_utc,
        case
            when eligible_exposure.eligible_exposure_at_utc is null
                then 'no_eligible_exposure'
            when first_subscription.first_subscription_at_utc is not null
                and first_subscription.first_subscription_at_utc
                    <= eligible_exposure.eligible_exposure_at_utc
                then 'subscription_not_after_exposure'
            when eligible_exposure.eligible_exposure_at_utc - interval '28 days'
                < observation_bounds.observation_start_at_utc
                then 'immature_pre_window'
            when eligible_exposure.eligible_exposure_at_utc + interval '28 days'
                > observation_bounds.observation_end_at_utc
                then 'immature_post_window'
            else null
        end as exclusion_reason
    from {{ ref('stg_hybrid_subscription__players') }} player
    cross join observation_bounds
    left join first_subscription using (player_id)
    left join eligible_exposure using (player_id)
)
select
    *,
    exclusion_reason is null as is_population_eligible
from classified_population
