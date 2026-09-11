select
    subscription_id,
    player_id,
    entitlement_start_at_utc,
    entitlement_end_at_utc,
    contractual_period_end_at_utc,
    canceled_at_utc,
    terminal_event_at_utc,
    latest_event_type,
    auto_renew_enabled,
    is_canceled_pending_expiry,
    case
        when terminal_event_at_utc is not null then 'ended'
        when is_canceled_pending_expiry then 'canceling'
        else 'active'
    end as entitlement_status
from {{ ref('int_hybrid_subscription__subscription_entitlements') }}
