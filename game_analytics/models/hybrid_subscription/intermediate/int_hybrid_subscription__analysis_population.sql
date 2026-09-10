with first_subscription as (
    select
        player_id,
        min(occurred_at_utc) as first_subscription_at_utc
    from {{ ref('stg_hybrid_subscription__subscription_events') }}
    where event_type = 'started'
    group by player_id
),
launch as (
    select min(first_subscription_at_utc) as subscription_launch_at_utc
    from first_subscription
),
eligible_exposure as (
    select
        player_id,
        bool_or(is_incrementality_eligible) as has_eligible_exposure,
        min(exposed_at_utc) filter (where is_incrementality_eligible) as eligible_exposure_at_utc
    from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}
    group by player_id
)
select
    player.player_id,
    player.country_code,
    player.platform,
    player.acquisition_channel,
    player.prior_payer_status,
    first_subscription.first_subscription_at_utc,
    coalesce(
        first_subscription.first_subscription_at_utc,
        launch.subscription_launch_at_utc
    ) as index_at_utc,
    first_subscription.first_subscription_at_utc is not null as is_subscriber,
    coalesce(eligible_exposure.has_eligible_exposure, false) as has_eligible_exposure,
    eligible_exposure.eligible_exposure_at_utc
from {{ ref('stg_hybrid_subscription__players') }} player
cross join launch
left join first_subscription using (player_id)
left join eligible_exposure using (player_id)
