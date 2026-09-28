select
    subscription_id,
    user_id,
    paid_start_at,
    cast(paid_start_at as date) as cohort_date,
    plan_id,
    monthly_recurring_revenue_usd
from {{ ref('int_subscription__subscription_periods') }}
where lifecycle_status = 'paid'
qualify row_number() over (
    partition by subscription_id
    order by paid_start_at, period_start_at
) = 1
