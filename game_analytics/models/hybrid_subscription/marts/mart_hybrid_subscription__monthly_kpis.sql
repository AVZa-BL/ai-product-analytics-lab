-- Calendar-month descriptive metrics only. The approved 28-day engagement lift
-- and incremental total net revenue remain at pair grain in matched_incrementality;
-- consumers query that mart separately rather than replicating estimates by month.
with observation as (
    select observation_start_at_utc as first_observed_at_utc, as_of_at_utc
    from {{ ref('int_hybrid_subscription__governed_observation_boundary') }}
    where are_source_watermarks_valid
),
months as (
    select distinct cast(date_trunc('month', d.date_day) as date) as metric_month,
        o.first_observed_at_utc, o.as_of_at_utc
    from {{ ref('dim_dates') }} d cross join observation o
    -- Suppress the first calendar month when common governed coverage begins
    -- after its opening instant; later partial months are published month-to-date.
    where d.date_day >= case
        when timezone('UTC', o.first_observed_at_utc)
            = date_trunc('month', timezone('UTC', o.first_observed_at_utc))
            then cast(date_trunc('month', timezone('UTC', o.first_observed_at_utc)) as date)
        else cast(date_trunc('month', timezone('UTC', o.first_observed_at_utc)) + interval '1 month' as date)
      end
      and d.date_day <= cast(timezone('UTC', o.as_of_at_utc) as date)
),
active_players as (
    select distinct cast(date_trunc('month', timezone('UTC', started_at_utc)) as date) as metric_month, player_id
    from {{ ref('fct_hybrid_subscription__sessions') }} cross join observation o
    where started_at_utc >= o.first_observed_at_utc
      and started_at_utc <= o.as_of_at_utc
),
activity as (
    select metric_month, count(*) as mau from active_players group by metric_month
),
liveops as (
    select a.metric_month, count(distinct a.player_id) as liveops_participant_count
    from active_players a cross join observation o
    join {{ ref('stg_hybrid_subscription__live_event_participation') }} p
        on p.player_id = a.player_id
        and cast(date_trunc('month', timezone('UTC', p.participated_at_utc)) as date) = a.metric_month
        and p.participated_at_utc >= o.first_observed_at_utc
        and p.participated_at_utc <= o.as_of_at_utc
    group by a.metric_month
),
revenue as (
    select cast(date_trunc('month', timezone('UTC', transaction_at_utc)) as date) as metric_month,
        sum(case when is_standalone_store_revenue then recognized_net_revenue_usd else 0 end)
            as standalone_store_net_revenue_usd,
        sum(case when is_subscription_revenue then recognized_net_revenue_usd else 0 end)
            as subscription_net_revenue_usd,
        count(*) filter (where is_standalone_store_revenue and transaction_status in ('succeeded', 'refunded'))
            as eligible_standalone_transaction_count,
        count(*) filter (where is_standalone_store_revenue and transaction_status in ('succeeded', 'refunded')
            and discount_amount_usd > 0) as discounted_standalone_transaction_count
    from {{ ref('fct_hybrid_subscription__store_transactions') }} cross join observation o
    where transaction_at_utc >= o.first_observed_at_utc
      and transaction_at_utc <= o.as_of_at_utc
    group by cast(date_trunc('month', timezone('UTC', transaction_at_utc)) as date)
),
start_subscribers as (
    -- Opening instant, not subscribers who join later on day one.
    select m.metric_month, count(distinct e.player_id) as month_start_active_subscriber_count
    from months m left join {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e
        on e.entitlement_start_at_utc <= timezone('UTC', cast(m.metric_month as timestamp))
        and e.entitlement_end_at_utc > timezone('UTC', cast(m.metric_month as timestamp))
    group by m.metric_month
),
end_subscribers as (
    select m.metric_month, count(distinct s.player_id) as month_end_active_subscriber_count
    from months m left join {{ ref('fct_hybrid_subscription__subscriber_daily') }} s
        on s.metric_date = cast(m.metric_month + interval '1 month' - interval '1 day' as date)
    group by m.metric_month
),
churn as (
    -- The governed terminal timestamp comes only from expiry/revocation, never cancellation.
    select cast(date_trunc('month', timezone('UTC', e.terminal_event_at_utc)) as date) as metric_month,
        count(distinct e.subscription_id) as expired_or_revoked_entitlement_count
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} e cross join observation o
    where e.terminal_event_at_utc >= o.first_observed_at_utc
      and e.terminal_event_at_utc <= o.as_of_at_utc
    group by cast(date_trunc('month', timezone('UTC', e.terminal_event_at_utc)) as date)
),
components as (
    select m.metric_month, m.as_of_at_utc,
        m.metric_month + interval '1 month' <= timezone('UTC', m.as_of_at_utc) as is_month_complete,
        coalesce(a.mau, 0) as mau,
        s.month_start_active_subscriber_count,
        case when m.metric_month + interval '1 month' <= timezone('UTC', m.as_of_at_utc)
            then e.month_end_active_subscriber_count end as month_end_active_subscriber_count,
        coalesce(c.expired_or_revoked_entitlement_count, 0) as expired_or_revoked_entitlement_count,
        coalesce(r.standalone_store_net_revenue_usd, 0) as standalone_store_net_revenue_usd,
        coalesce(r.subscription_net_revenue_usd, 0) as subscription_net_revenue_usd,
        coalesce(r.discounted_standalone_transaction_count, 0) as discounted_standalone_transaction_count,
        coalesce(r.eligible_standalone_transaction_count, 0) as eligible_standalone_transaction_count,
        coalesce(l.liveops_participant_count, 0) as liveops_participant_count
    from months m
    left join activity a using (metric_month)
    left join start_subscribers s using (metric_month)
    left join end_subscribers e using (metric_month)
    left join churn c using (metric_month)
    left join revenue r using (metric_month)
    left join liveops l using (metric_month)
)
select cast(metric_month as varchar) as monthly_kpi_id, *,
    expired_or_revoked_entitlement_count::double / nullif(month_start_active_subscriber_count, 0) as subscriber_churn_rate,
    standalone_store_net_revenue_usd + subscription_net_revenue_usd as total_net_revenue_usd,
    (standalone_store_net_revenue_usd + subscription_net_revenue_usd)::double / nullif(mau, 0) as arpmau,
    discounted_standalone_transaction_count::double / nullif(eligible_standalone_transaction_count, 0) as discount_utilization_rate,
    liveops_participant_count::double / nullif(mau, 0) as liveops_participation_rate
from components
