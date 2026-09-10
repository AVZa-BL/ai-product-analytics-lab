with period_spine as (
    select * from (values ('pre'), ('post')) as periods(analysis_period)
),
population_periods as (
    select
        population.*,
        periods.analysis_period,
        case
            when periods.analysis_period = 'pre'
                then population.index_at_utc - interval '28 days'
            else population.index_at_utc
        end as period_start_at_utc,
        case
            when periods.analysis_period = 'pre'
                then population.index_at_utc
            else population.index_at_utc + interval '28 days'
        end as period_end_at_utc
    from {{ ref('int_hybrid_subscription__analysis_population') }} population
    cross join period_spine periods
),
session_metrics as (
    select
        period.player_id,
        period.analysis_period,
        count(session.session_id) as session_count,
        coalesce(sum(session.duration_seconds), 0) as session_duration_seconds
    from population_periods period
    left join {{ ref('stg_hybrid_subscription__sessions') }} session
        on period.player_id = session.player_id
        and session.started_at_utc >= period.period_start_at_utc
        and session.started_at_utc < period.period_end_at_utc
    group by period.player_id, period.analysis_period
),
revenue_metrics as (
    select
        period.player_id,
        period.analysis_period,
        coalesce(sum(transaction.net_amount_usd - transaction.refund_amount_usd)
            filter (where transaction.product_type = 'subscription'), 0) as subscription_net_revenue_usd,
        coalesce(sum(transaction.net_amount_usd - transaction.refund_amount_usd)
            filter (where transaction.product_type != 'subscription'), 0) as standalone_store_net_revenue_usd,
        coalesce(sum(transaction.discount_amount_usd), 0) as discount_amount_usd
    from population_periods period
    left join {{ ref('stg_hybrid_subscription__store_transactions') }} transaction
        on period.player_id = transaction.player_id
        and transaction.transaction_status in ('succeeded', 'refunded')
        and transaction.transaction_at_utc >= period.period_start_at_utc
        and transaction.transaction_at_utc < period.period_end_at_utc
    group by period.player_id, period.analysis_period
),
liveops_metrics as (
    select
        period.player_id,
        period.analysis_period,
        count(participation.participation_id) as liveops_participation_count
    from population_periods period
    left join {{ ref('stg_hybrid_subscription__live_event_participation') }} participation
        on period.player_id = participation.player_id
        and participation.participated_at_utc >= period.period_start_at_utc
        and participation.participated_at_utc < period.period_end_at_utc
    group by period.player_id, period.analysis_period
)
select
    period.player_id,
    period.analysis_period,
    period.period_start_at_utc,
    period.period_end_at_utc,
    period.prior_payer_status,
    period.platform,
    period.acquisition_channel,
    period.is_subscriber,
    period.has_eligible_exposure,
    session.session_count,
    session.session_duration_seconds,
    liveops.liveops_participation_count,
    revenue.subscription_net_revenue_usd,
    revenue.standalone_store_net_revenue_usd,
    revenue.subscription_net_revenue_usd
        + revenue.standalone_store_net_revenue_usd as total_net_revenue_usd,
    revenue.discount_amount_usd
from population_periods period
join session_metrics session using (player_id, analysis_period)
join revenue_metrics revenue using (player_id, analysis_period)
join liveops_metrics liveops using (player_id, analysis_period)
