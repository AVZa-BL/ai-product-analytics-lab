with first_subscription as (
    select
        player_id,
        min(occurred_at_utc) as first_subscription_at_utc
    from {{ ref('stg_hybrid_subscription__subscription_events') }}
    where event_type = 'started'
    group by player_id
)
select
    exposure.*,
    first_subscription.first_subscription_at_utc,
    first_subscription.first_subscription_at_utc is null
        or exposure.exposed_at_utc <= first_subscription.first_subscription_at_utc
        as is_pre_subscription_exposure,
    exposure.experiment_arm is not null
        and (
            first_subscription.first_subscription_at_utc is null
            or exposure.exposed_at_utc <= first_subscription.first_subscription_at_utc
        ) as is_incrementality_eligible,
    case
        when first_subscription.first_subscription_at_utc is not null
            and exposure.exposed_at_utc > first_subscription.first_subscription_at_utc
            then 'exposure_after_subscription'
        when exposure.experiment_arm is null then 'missing_experiment_arm'
        else null
    end as ineligibility_reason
from {{ ref('stg_hybrid_subscription__marketing_exposures') }} exposure
left join first_subscription using (player_id)
