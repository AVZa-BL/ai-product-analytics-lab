with expected as (
  select calendar_date, sum(monthly_recurring_revenue_usd) as expected_mrr
  from {{ ref('fct_subscription__daily_user_state') }}
  where is_paid_active
  group by 1
)
select k.metric_date, k.mrr_usd, e.expected_mrr
from {{ ref('mart_subscription__kpis_daily') }} k
join expected e on k.metric_date = e.calendar_date
where abs(k.mrr_usd - e.expected_mrr) > 0.01
