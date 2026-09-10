-- Independent fact-side oracle: no expected component or rate reads a KPI mart.
-- EXCEPT ALL in both directions catches null corruption, missing/extra rows and duplicates.
with observed as (
    select started_at_utc as observed_at_utc from {{ ref('fct_hybrid_subscription__sessions') }}
    union all select transaction_at_utc from {{ ref('fct_hybrid_subscription__store_transactions') }}
    union all select participated_at_utc from {{ ref('stg_hybrid_subscription__live_event_participation') }}
),
bounds as (select min(observed_at_utc) as first_at, max(observed_at_utc) as as_of_at_utc from observed),
daily_events as (
    select f.player_id, cast(f.started_at_utc as date) as metric_date from {{ ref('fct_hybrid_subscription__sessions') }} f
    union all
    select f.player_id, cast(f.participated_at_utc as date) as metric_date from {{ ref('stg_hybrid_subscription__live_event_participation') }} f
    union all
    select f.player_id, cast(f.transaction_at_utc as date) as metric_date from {{ ref('fct_hybrid_subscription__store_transactions') }} f
    union all
    select f.player_id, cast(f.entitlement_start_at_utc as date) as metric_date from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} f
    union all
    select f.player_id, cast(f.exposed_at_utc as date) as metric_date from {{ ref('fct_hybrid_subscription__marketing_exposures') }} f
    union all
    select f.player_id, cast(f.occurred_at_utc as date) as metric_date from {{ ref('fct_hybrid_subscription__currency_grants') }} f
    where f.entry_type = 'subscription_grant'
    union all
    select f.player_id, cast(f.metric_date as date) as metric_date from {{ ref('fct_hybrid_subscription__subscriber_daily') }} f
),
daily_keys as (
    select distinct e.metric_date,p.prior_payer_status
    from daily_events e join {{ ref('dim_hybrid_subscription__players') }} p using (player_id)
    cross join bounds b where e.metric_date <= cast(b.as_of_at_utc as date)
),
daily_components as (
    select k.*,
        (select count(*) from {{ ref('fct_hybrid_subscription__sessions') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.started_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as session_count,
        (select coalesce(sum(f.duration_seconds),0) from {{ ref('fct_hybrid_subscription__sessions') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.started_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as session_duration_seconds,
        (select count(*) from {{ ref('stg_hybrid_subscription__live_event_participation') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.participated_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as liveops_participation_count,
        (select coalesce(sum(f.recognized_net_revenue_usd),0) from {{ ref('fct_hybrid_subscription__store_transactions') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.transaction_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and f.is_standalone_store_revenue) as standalone_store_net_revenue_usd,
        (select coalesce(sum(f.recognized_net_revenue_usd),0) from {{ ref('fct_hybrid_subscription__store_transactions') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.transaction_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and f.is_subscription_revenue) as subscription_net_revenue_usd,
        (select coalesce(sum(f.discount_amount_usd),0) from {{ ref('fct_hybrid_subscription__store_transactions') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.transaction_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as discount_amount_usd,
        (select count(*) from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.entitlement_start_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as new_subscription_count,
        (select count(*) from {{ ref('fct_hybrid_subscription__marketing_exposures') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.exposed_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and f.is_incrementality_eligible) as eligible_exposure_count,
        (select count(*) from {{ ref('fct_hybrid_subscription__marketing_exposures') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.exposed_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and not f.is_incrementality_eligible) as rejected_exposure_count,
        (select count(*) from {{ ref('fct_hybrid_subscription__currency_grants') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.occurred_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and f.entry_type = 'subscription_grant') as subscription_grant_count,
        (select count(*) from {{ ref('fct_hybrid_subscription__currency_grants') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.occurred_at_utc as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and f.entry_type = 'subscription_grant' and f.is_reconciled) as reconciled_subscription_grant_count,
        (select count(distinct f.player_id) from {{ ref('fct_hybrid_subscription__subscriber_daily') }} f join {{ ref('dim_hybrid_subscription__players') }} p using (player_id) where cast(f.metric_date as date)=k.metric_date and p.prior_payer_status=k.prior_payer_status and true) as active_subscriber_count
    from daily_keys k
),
expected_daily as (
    select metric_date,prior_payer_status,session_count,session_duration_seconds,liveops_participation_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,discount_amount_usd,new_subscription_count,eligible_exposure_count,rejected_exposure_count,subscription_grant_count,reconciled_subscription_grant_count,active_subscriber_count,
        standalone_store_net_revenue_usd + subscription_net_revenue_usd as total_net_revenue_usd,
        reconciled_subscription_grant_count::double / nullif(subscription_grant_count,0) as subscription_grant_reconciliation_rate
    from daily_components
),
month_keys as (
    select distinct date_trunc('month',d.date_day)::date as metric_month,b.as_of_at_utc
    from {{ ref('dim_dates') }} d cross join bounds b
    where date_trunc('month',d.date_day) between date_trunc('month',b.first_at) and date_trunc('month',b.as_of_at_utc)
),
monthly_components as (
    select k.metric_month,
        (select count(distinct s.player_id) from {{ ref('fct_hybrid_subscription__sessions') }} s where date_trunc('month',s.started_at_utc)::date=k.metric_month) as mau,
        (select count(distinct e.player_id) from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e where e.entitlement_start_at_utc <= k.metric_month::timestamptz and e.entitlement_end_at_utc > k.metric_month::timestamptz) as month_start_active_subscriber_count,
        (select case when k.metric_month + interval '1 month' <= k.as_of_at_utc then count(distinct s.player_id) end from {{ ref('fct_hybrid_subscription__subscriber_daily') }} s where s.metric_date=(k.metric_month + interval '1 month' - interval '1 day')::date) as month_end_active_subscriber_count,
        (select count(distinct e.subscription_id) from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e where date_trunc('month',e.terminal_event_at_utc)::date=k.metric_month and e.terminal_event_at_utc <= k.as_of_at_utc and exists (select 1 from {{ ref('stg_hybrid_subscription__subscription_events') }} v where v.player_id=e.player_id and v.occurred_at_utc=e.terminal_event_at_utc and v.event_type in ('expired','revoked'))) as expired_or_revoked_entitlement_count,
        (select coalesce(sum(t.recognized_net_revenue_usd),0) from {{ ref('fct_hybrid_subscription__store_transactions') }} t where date_trunc('month',t.transaction_at_utc)::date=k.metric_month and t.is_standalone_store_revenue) as standalone_store_net_revenue_usd,
        (select coalesce(sum(t.recognized_net_revenue_usd),0) from {{ ref('fct_hybrid_subscription__store_transactions') }} t where date_trunc('month',t.transaction_at_utc)::date=k.metric_month and t.is_subscription_revenue) as subscription_net_revenue_usd,
        (select count(*) from {{ ref('fct_hybrid_subscription__store_transactions') }} t where date_trunc('month',t.transaction_at_utc)::date=k.metric_month and t.is_standalone_store_revenue and t.transaction_status in ('succeeded','refunded')) as eligible_standalone_transaction_count,
        (select count(*) from {{ ref('fct_hybrid_subscription__store_transactions') }} t where date_trunc('month',t.transaction_at_utc)::date=k.metric_month and t.is_standalone_store_revenue and t.transaction_status in ('succeeded','refunded') and t.discount_amount_usd>0) as discounted_standalone_transaction_count,
        (select count(distinct l.player_id) from {{ ref('stg_hybrid_subscription__live_event_participation') }} l where date_trunc('month',l.participated_at_utc)::date=k.metric_month and exists (select 1 from {{ ref('fct_hybrid_subscription__sessions') }} s where s.player_id=l.player_id and date_trunc('month',s.started_at_utc)::date=k.metric_month)) as liveops_participant_count
    from month_keys k
),
expected_monthly as (
    select *,
        standalone_store_net_revenue_usd + subscription_net_revenue_usd as total_net_revenue_usd,
        (standalone_store_net_revenue_usd + subscription_net_revenue_usd)::double / nullif(mau,0) as arpmau,
        expired_or_revoked_entitlement_count::double / nullif(month_start_active_subscriber_count,0) as subscriber_churn_rate,
        discounted_standalone_transaction_count::double / nullif(eligible_standalone_transaction_count,0) as discount_utilization_rate,
        liveops_participant_count::double / nullif(mau,0) as liveops_participation_rate
    from monthly_components
),
first_exposures as (
    select player_id,min(exposed_at_utc) as index_at
    from {{ ref('fct_hybrid_subscription__marketing_exposures') }} where is_incrementality_eligible group by player_id
),
first_starts as (
    select player_id,min(entitlement_start_at_utc) as start_at
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} group by player_id
),
cohort_members as (
    select 'eligible_exposure' as cohort_type,x.player_id,x.index_at as cohort_at,
        1 as eligible_exposed_player_count,
        case when s.start_at > x.index_at and s.start_at < x.index_at + interval '28 days'
            and s.start_at <= b.as_of_at_utc then 1 else 0 end as converted_within_28d_player_count,
        0 as subscription_starter_count,0 as mature_subscription_starter_count,0 as retained_at_d30_player_count
    from first_exposures x left join first_starts s using (player_id) cross join bounds b
    where x.index_at <= b.as_of_at_utc
    union all
    select 'subscription_start',s.player_id,s.start_at,0,0,1,
        case when s.start_at + interval '30 days' <= b.as_of_at_utc then 1 else 0 end,
        case when s.start_at + interval '30 days' <= b.as_of_at_utc and exists (
            select 1 from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e
            where e.player_id=s.player_id and e.entitlement_start_at_utc <= s.start_at + interval '30 days'
              and e.entitlement_end_at_utc > s.start_at + interval '30 days') then 1 else 0 end
    from first_starts s cross join bounds b where s.start_at <= b.as_of_at_utc
),
cohort_components as (
    select cohort_type,cast(cohort_at as date) as cohort_date,
        max(cohort_at) as cohort_latest_at_utc,b.as_of_at_utc,
        sum(eligible_exposed_player_count) as eligible_exposed_player_count,
        sum(converted_within_28d_player_count) as converted_within_28d_player_count,
        sum(subscription_starter_count) as subscription_starter_count,
        sum(mature_subscription_starter_count) as mature_subscription_starter_count,
        sum(retained_at_d30_player_count) as retained_at_d30_player_count,
        cohort_type='eligible_exposure' and max(cohort_at)+interval '28 days'<=b.as_of_at_utc as is_conversion_mature,
        cohort_type='subscription_start' and max(cohort_at)+interval '30 days'<=b.as_of_at_utc as is_d30_mature
    from cohort_members cross join bounds b
    group by cohort_type,cast(cohort_at as date),b.as_of_at_utc
),
expected_cohorts as (
    select *,
        case when is_conversion_mature then converted_within_28d_player_count::double/nullif(eligible_exposed_player_count,0) end as subscription_conversion_rate,
        case when is_d30_mature then retained_at_d30_player_count::double/nullif(mature_subscription_starter_count,0) end as d30_subscriber_retention_rate
    from cohort_components
),
daily_missing as (select metric_date,prior_payer_status,session_count,session_duration_seconds,liveops_participation_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,discount_amount_usd,new_subscription_count,eligible_exposure_count,rejected_exposure_count,subscription_grant_count,reconciled_subscription_grant_count,active_subscriber_count,total_net_revenue_usd,subscription_grant_reconciliation_rate from expected_daily except all select metric_date,prior_payer_status,session_count,session_duration_seconds,liveops_participation_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,discount_amount_usd,new_subscription_count,eligible_exposure_count,rejected_exposure_count,subscription_grant_count,reconciled_subscription_grant_count,active_subscriber_count,total_net_revenue_usd,subscription_grant_reconciliation_rate from {{ ref('mart_hybrid_subscription__daily_kpis') }}),
daily_unexpected as (select metric_date,prior_payer_status,session_count,session_duration_seconds,liveops_participation_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,discount_amount_usd,new_subscription_count,eligible_exposure_count,rejected_exposure_count,subscription_grant_count,reconciled_subscription_grant_count,active_subscriber_count,total_net_revenue_usd,subscription_grant_reconciliation_rate from {{ ref('mart_hybrid_subscription__daily_kpis') }} except all select metric_date,prior_payer_status,session_count,session_duration_seconds,liveops_participation_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,discount_amount_usd,new_subscription_count,eligible_exposure_count,rejected_exposure_count,subscription_grant_count,reconciled_subscription_grant_count,active_subscriber_count,total_net_revenue_usd,subscription_grant_reconciliation_rate from expected_daily),
monthly_missing as (select metric_month,mau,month_start_active_subscriber_count,month_end_active_subscriber_count,expired_or_revoked_entitlement_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,eligible_standalone_transaction_count,discounted_standalone_transaction_count,liveops_participant_count,total_net_revenue_usd,arpmau,subscriber_churn_rate,discount_utilization_rate,liveops_participation_rate from expected_monthly except all select metric_month,mau,month_start_active_subscriber_count,month_end_active_subscriber_count,expired_or_revoked_entitlement_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,eligible_standalone_transaction_count,discounted_standalone_transaction_count,liveops_participant_count,total_net_revenue_usd,arpmau,subscriber_churn_rate,discount_utilization_rate,liveops_participation_rate from {{ ref('mart_hybrid_subscription__monthly_kpis') }}),
monthly_unexpected as (select metric_month,mau,month_start_active_subscriber_count,month_end_active_subscriber_count,expired_or_revoked_entitlement_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,eligible_standalone_transaction_count,discounted_standalone_transaction_count,liveops_participant_count,total_net_revenue_usd,arpmau,subscriber_churn_rate,discount_utilization_rate,liveops_participation_rate from {{ ref('mart_hybrid_subscription__monthly_kpis') }} except all select metric_month,mau,month_start_active_subscriber_count,month_end_active_subscriber_count,expired_or_revoked_entitlement_count,standalone_store_net_revenue_usd,subscription_net_revenue_usd,eligible_standalone_transaction_count,discounted_standalone_transaction_count,liveops_participant_count,total_net_revenue_usd,arpmau,subscriber_churn_rate,discount_utilization_rate,liveops_participation_rate from expected_monthly),
cohorts_missing as (select cohort_type,cohort_date,cohort_latest_at_utc,as_of_at_utc,eligible_exposed_player_count,converted_within_28d_player_count,subscription_starter_count,mature_subscription_starter_count,retained_at_d30_player_count,is_conversion_mature,is_d30_mature,subscription_conversion_rate,d30_subscriber_retention_rate from expected_cohorts except all select cohort_type,cohort_date,cohort_latest_at_utc,as_of_at_utc,eligible_exposed_player_count,converted_within_28d_player_count,subscription_starter_count,mature_subscription_starter_count,retained_at_d30_player_count,is_conversion_mature,is_d30_mature,subscription_conversion_rate,d30_subscriber_retention_rate from {{ ref('mart_hybrid_subscription__subscription_cohorts') }}),
cohorts_unexpected as (select cohort_type,cohort_date,cohort_latest_at_utc,as_of_at_utc,eligible_exposed_player_count,converted_within_28d_player_count,subscription_starter_count,mature_subscription_starter_count,retained_at_d30_player_count,is_conversion_mature,is_d30_mature,subscription_conversion_rate,d30_subscriber_retention_rate from {{ ref('mart_hybrid_subscription__subscription_cohorts') }} except all select cohort_type,cohort_date,cohort_latest_at_utc,as_of_at_utc,eligible_exposed_player_count,converted_within_28d_player_count,subscription_starter_count,mature_subscription_starter_count,retained_at_d30_player_count,is_conversion_mature,is_d30_mature,subscription_conversion_rate,d30_subscriber_retention_rate from expected_cohorts)
select 'daily_missing' as violation from daily_missing
union all select 'daily_unexpected' from daily_unexpected
union all select 'monthly_missing' from monthly_missing
union all select 'monthly_unexpected' from monthly_unexpected
union all select 'cohorts_missing' from cohorts_missing
union all select 'cohorts_unexpected' from cohorts_unexpected
union all select 'monthly_cash_identity' from {{ ref('mart_hybrid_subscription__monthly_kpis') }} where total_net_revenue_usd is distinct from standalone_store_net_revenue_usd+subscription_net_revenue_usd
union all select 'daily_cash_identity' from {{ ref('mart_hybrid_subscription__daily_kpis') }} where total_net_revenue_usd is distinct from standalone_store_net_revenue_usd+subscription_net_revenue_usd
