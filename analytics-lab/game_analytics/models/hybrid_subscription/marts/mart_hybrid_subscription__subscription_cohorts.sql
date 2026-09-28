with observation as (
    select observation_start_at_utc, as_of_at_utc
    from {{ ref('int_hybrid_subscription__governed_observation_boundary') }}
    where are_source_watermarks_valid
),
exposures as (
    -- Conversion requires an eligible exposure and mature forward window, not a
    -- mature pre-window or a successful observational match.
    select player_id, min(exposed_at_utc) as first_exposure_at_utc
    from {{ ref('fct_hybrid_subscription__marketing_exposures') }}
    where is_incrementality_eligible
    group by player_id
),
starters as (
    select player_id, min(entitlement_start_at_utc) as first_start_at_utc
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }}
    group by player_id
),
conversion as (
    select
        'eligible_exposure' as cohort_type,
        cast(timezone('UTC', e.first_exposure_at_utc) as date) as cohort_date,
        max(e.first_exposure_at_utc) as cohort_latest_at_utc,
        o.as_of_at_utc,
        count(distinct e.player_id) as eligible_exposed_player_count,
        count(distinct case when s.first_start_at_utc > e.first_exposure_at_utc
            and s.first_start_at_utc < e.first_exposure_at_utc + interval '672 hours'
            and s.first_start_at_utc <= o.as_of_at_utc then e.player_id end)
            as converted_within_28d_player_count,
        0::bigint as subscription_starter_count,
        0::bigint as mature_subscription_starter_count,
        0::bigint as retained_at_d30_player_count,
        max(e.first_exposure_at_utc) + interval '672 hours' <= o.as_of_at_utc as is_conversion_mature,
        false as is_d30_mature
    from exposures e left join starters s using (player_id)
    cross join observation o
    where e.first_exposure_at_utc >= o.observation_start_at_utc
      and e.first_exposure_at_utc <= o.as_of_at_utc
    group by cast(timezone('UTC', e.first_exposure_at_utc) as date), o.as_of_at_utc
),
retention as (
    select
        'subscription_start' as cohort_type,
        cast(timezone('UTC', s.first_start_at_utc) as date) as cohort_date,
        max(s.first_start_at_utc) as cohort_latest_at_utc,
        o.as_of_at_utc,
        0::bigint as eligible_exposed_player_count,
        0::bigint as converted_within_28d_player_count,
        count(distinct s.player_id) as subscription_starter_count,
        count(distinct case when s.first_start_at_utc + interval '720 hours' <= o.as_of_at_utc
            then s.player_id end) as mature_subscription_starter_count,
        count(distinct case when s.first_start_at_utc + interval '720 hours' <= o.as_of_at_utc
            and e.player_id is not null then s.player_id end) as retained_at_d30_player_count,
        false as is_conversion_mature,
        max(s.first_start_at_utc) + interval '720 hours' <= o.as_of_at_utc as is_d30_mature
    from starters s cross join observation o
    left join {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e
        on e.player_id = s.player_id
        and e.entitlement_start_at_utc <= s.first_start_at_utc + interval '720 hours'
        and e.entitlement_end_at_utc > s.first_start_at_utc + interval '720 hours'
    where s.first_start_at_utc >= o.observation_start_at_utc
      and s.first_start_at_utc <= o.as_of_at_utc
    group by cast(timezone('UTC', s.first_start_at_utc) as date), o.as_of_at_utc
),
cohorts as (
    select * from conversion
    union all select * from retention
)
select
    cohort_type || '__' || cast(cohort_date as varchar) as subscription_cohort_id,
    *,
    case when is_conversion_mature then converted_within_28d_player_count::double
        / nullif(eligible_exposed_player_count, 0) end as subscription_conversion_rate,
    case when is_d30_mature then retained_at_d30_player_count::double
        / nullif(mature_subscription_starter_count, 0) end as d30_subscriber_retention_rate
from cohorts
