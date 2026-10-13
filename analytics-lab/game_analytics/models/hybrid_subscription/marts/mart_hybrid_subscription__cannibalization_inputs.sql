select
    subscriber_prior_payer_status as cannibalization_segment_id,
    subscriber_prior_payer_status as prior_payer_status,
    count(*) as matched_pair_count,
    count(distinct subscriber_player_id) as matched_subscriber_count,
    count(distinct control_player_id) as matched_control_count,
    sum(subscriber_standalone_store_net_revenue_usd_change)
        as subscriber_standalone_store_net_revenue_usd_change_sum,
    sum(control_standalone_store_net_revenue_usd_change)
        as control_standalone_store_net_revenue_usd_change_sum,
    sum(standalone_store_net_revenue_usd_difference_in_differences)
        as standalone_store_net_revenue_usd_difference_in_differences_sum,
    avg(subscriber_standalone_store_net_revenue_usd_change)
        as mean_subscriber_standalone_store_net_revenue_usd_change,
    avg(control_standalone_store_net_revenue_usd_change)
        as mean_control_standalone_store_net_revenue_usd_change,
    avg(standalone_store_net_revenue_usd_difference_in_differences)
        as mean_standalone_store_net_revenue_usd_difference_in_differences,
    sum(subscriber_subscription_net_revenue_usd_change)
        as subscriber_subscription_net_revenue_usd_change_sum,
    sum(control_subscription_net_revenue_usd_change)
        as control_subscription_net_revenue_usd_change_sum,
    sum(subscription_net_revenue_usd_difference_in_differences)
        as subscription_net_revenue_usd_difference_in_differences_sum,
    avg(subscriber_subscription_net_revenue_usd_change)
        as mean_subscriber_subscription_net_revenue_usd_change,
    avg(control_subscription_net_revenue_usd_change)
        as mean_control_subscription_net_revenue_usd_change,
    avg(subscription_net_revenue_usd_difference_in_differences)
        as mean_subscription_net_revenue_usd_difference_in_differences,
    sum(subscriber_total_net_revenue_usd_change)
        as subscriber_total_net_revenue_usd_change_sum,
    sum(control_total_net_revenue_usd_change)
        as control_total_net_revenue_usd_change_sum,
    sum(total_net_revenue_usd_difference_in_differences)
        as total_net_revenue_usd_difference_in_differences_sum,
    avg(subscriber_total_net_revenue_usd_change)
        as mean_subscriber_total_net_revenue_usd_change,
    avg(control_total_net_revenue_usd_change)
        as mean_control_total_net_revenue_usd_change,
    avg(total_net_revenue_usd_difference_in_differences)
        as mean_total_net_revenue_usd_difference_in_differences
from {{ ref('mart_hybrid_subscription__matched_incrementality') }}
where subscriber_prior_payer_status = 'prior_payer'
  and control_prior_payer_status = 'prior_payer'
group by subscriber_prior_payer_status
