select
    entitlement.subscription_id,
    entitlement.player_id,
    cancellation.occurred_at_utc as canceled_at_utc,
    cancellation.current_period_end_at_utc,
    entitlement.entitlement_end_at_utc
from {{ ref('int_hybrid_subscription__subscription_entitlements') }} entitlement
join {{ ref('stg_hybrid_subscription__subscription_events') }} cancellation
    on entitlement.player_id = cancellation.player_id
    and cancellation.event_type = 'canceled'
where entitlement.entitlement_end_at_utc < cancellation.current_period_end_at_utc
