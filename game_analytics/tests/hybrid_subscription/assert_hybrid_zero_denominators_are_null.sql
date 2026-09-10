select monthly_kpi_id as row_id
from {{ ref('mart_hybrid_subscription__monthly_kpis') }}
where (mau = 0 and arpmau is not null)
   or (mau = 0 and liveops_participation_rate is not null)
   or (eligible_standalone_transaction_count = 0 and discount_utilization_rate is not null)
   or (month_start_active_subscriber_count = 0 and subscriber_churn_rate is not null)
union all
select daily_kpi_id
from {{ ref('mart_hybrid_subscription__daily_kpis') }}
where subscription_grant_count = 0 and subscription_grant_reconciliation_rate is not null
union all
select subscription_cohort_id
from {{ ref('mart_hybrid_subscription__subscription_cohorts') }}
where (eligible_exposed_player_count = 0 and subscription_conversion_rate is not null)
   or (mature_subscription_starter_count = 0 and d30_subscriber_retention_rate is not null)
