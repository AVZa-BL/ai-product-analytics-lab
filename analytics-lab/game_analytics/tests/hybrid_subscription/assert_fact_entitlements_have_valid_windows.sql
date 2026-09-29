select *
from {{ ref('fct_hybrid_subscription__subscription_entitlements') }}
where entitlement_start_at_utc >= entitlement_end_at_utc
    or canceled_at_utc < entitlement_start_at_utc
    or (
        is_canceled_pending_expiry
        and entitlement_end_at_utc != contractual_period_end_at_utc
    )
