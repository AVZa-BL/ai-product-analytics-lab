select
    left_side.player_id,
    left_side.subscription_id as left_subscription_id,
    right_side.subscription_id as right_subscription_id
from {{ ref('int_hybrid_subscription__subscription_entitlements') }} left_side
join {{ ref('int_hybrid_subscription__subscription_entitlements') }} right_side
    on left_side.player_id = right_side.player_id
    and left_side.subscription_id < right_side.subscription_id
    and left_side.entitlement_start_at_utc < right_side.entitlement_end_at_utc
    and right_side.entitlement_start_at_utc < left_side.entitlement_end_at_utc
