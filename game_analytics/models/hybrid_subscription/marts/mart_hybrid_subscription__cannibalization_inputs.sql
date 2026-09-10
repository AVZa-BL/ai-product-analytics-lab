select
    analysis_period || '__prior_payer__'
        || cast(is_subscriber as varchar) as cannibalization_segment_id,
    analysis_period,
    is_subscriber,
    prior_payer_status,
    count(*) as eligible_player_count,
    sum(case when standalone_store_net_revenue_usd > 0 then 1 else 0 end)
        as standalone_store_payer_count,
    sum(standalone_store_net_revenue_usd) as standalone_store_net_revenue_usd,
    sum(subscription_net_revenue_usd) as subscription_net_revenue_usd,
    sum(total_net_revenue_usd) as total_net_revenue_usd,
    sum(discount_amount_usd) as discount_amount_usd,
    avg(standalone_store_net_revenue_usd)
        as mean_standalone_store_net_revenue_per_player_usd,
    avg(subscription_net_revenue_usd)
        as mean_subscription_net_revenue_per_player_usd,
    avg(total_net_revenue_usd) as mean_total_net_revenue_per_player_usd
from {{ ref('fct_hybrid_subscription__player_behavior_28d') }}
where prior_payer_status = 'prior_payer'
group by analysis_period, is_subscriber, prior_payer_status
