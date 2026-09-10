select
    entitlement.player_id || '__' || cast(date.date_day as varchar) as player_date_id,
    entitlement.player_id,
    date.date_day as metric_date,
    entitlement.subscription_id,
    entitlement.entitlement_start_at_utc,
    entitlement.entitlement_end_at_utc
from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} entitlement
join {{ ref('dim_dates') }} date
  on date.date_day >= cast(entitlement.entitlement_start_at_utc as date)
 and date.date_day < cast(entitlement.entitlement_end_at_utc as date)
