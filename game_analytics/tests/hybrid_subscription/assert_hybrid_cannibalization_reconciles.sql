with prior_payer_pairs as (
    select *
    from {{ ref('mart_hybrid_subscription__matched_incrementality') }}
    where subscriber_prior_payer_status = 'prior_payer'
      and control_prior_payer_status = 'prior_payer'
),
expected as (
    select
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
        sum(subscriber_subscription_net_revenue_usd_change)
            as subscriber_subscription_net_revenue_usd_change_sum,
        sum(control_subscription_net_revenue_usd_change)
            as control_subscription_net_revenue_usd_change_sum,
        sum(subscription_net_revenue_usd_difference_in_differences)
            as subscription_net_revenue_usd_difference_in_differences_sum,
        sum(subscriber_total_net_revenue_usd_change)
            as subscriber_total_net_revenue_usd_change_sum,
        sum(control_total_net_revenue_usd_change)
            as control_total_net_revenue_usd_change_sum,
        sum(total_net_revenue_usd_difference_in_differences)
            as total_net_revenue_usd_difference_in_differences_sum,
        avg(subscriber_standalone_store_net_revenue_usd_change)
            as mean_subscriber_standalone_store_net_revenue_usd_change,
        avg(control_standalone_store_net_revenue_usd_change)
            as mean_control_standalone_store_net_revenue_usd_change,
        avg(standalone_store_net_revenue_usd_difference_in_differences)
            as mean_standalone_store_net_revenue_usd_difference_in_differences,
        avg(subscriber_subscription_net_revenue_usd_change)
            as mean_subscriber_subscription_net_revenue_usd_change,
        avg(control_subscription_net_revenue_usd_change)
            as mean_control_subscription_net_revenue_usd_change,
        avg(subscription_net_revenue_usd_difference_in_differences)
            as mean_subscription_net_revenue_usd_difference_in_differences,
        avg(subscriber_total_net_revenue_usd_change)
            as mean_subscriber_total_net_revenue_usd_change,
        avg(control_total_net_revenue_usd_change)
            as mean_control_total_net_revenue_usd_change,
        avg(total_net_revenue_usd_difference_in_differences)
            as mean_total_net_revenue_usd_difference_in_differences
    from prior_payer_pairs
    group by subscriber_prior_payer_status
),
published as (
    select
        prior_payer_status,
        matched_pair_count,
        matched_subscriber_count,
        matched_control_count,
        subscriber_standalone_store_net_revenue_usd_change_sum,
        control_standalone_store_net_revenue_usd_change_sum,
        standalone_store_net_revenue_usd_difference_in_differences_sum,
        subscriber_subscription_net_revenue_usd_change_sum,
        control_subscription_net_revenue_usd_change_sum,
        subscription_net_revenue_usd_difference_in_differences_sum,
        subscriber_total_net_revenue_usd_change_sum,
        control_total_net_revenue_usd_change_sum,
        total_net_revenue_usd_difference_in_differences_sum,
        mean_subscriber_standalone_store_net_revenue_usd_change,
        mean_control_standalone_store_net_revenue_usd_change,
        mean_standalone_store_net_revenue_usd_difference_in_differences,
        mean_subscriber_subscription_net_revenue_usd_change,
        mean_control_subscription_net_revenue_usd_change,
        mean_subscription_net_revenue_usd_difference_in_differences,
        mean_subscriber_total_net_revenue_usd_change,
        mean_control_total_net_revenue_usd_change,
        mean_total_net_revenue_usd_difference_in_differences
    from {{ ref('mart_hybrid_subscription__cannibalization_inputs') }}
),
missing_published_rows as (
    select * from expected
    except all
    select * from published
),
unexpected_published_rows as (
    select * from published
    except all
    select * from expected
),
reconciliation_differences as (
    select * from missing_published_rows
    union all
    select * from unexpected_published_rows
),
violations as (
    select 'invalid_prior_payer_pair_id' as violation, pair_id as row_id
    from prior_payer_pairs
    where pair_id is null

    union all

    select 'invalid_segment_arm_counts', cannibalization_segment_id
    from {{ ref('mart_hybrid_subscription__cannibalization_inputs') }}
    where matched_pair_count <= 0
       or matched_pair_count is distinct from matched_subscriber_count
       or matched_pair_count is distinct from matched_control_count

    union all

    select 'aggregate_does_not_reconcile' as violation, prior_payer_status as row_id
    from reconciliation_differences

    union all

    select 'pair_revenue_components_do_not_reconcile', pair_id
    from prior_payer_pairs
    where abs(
        total_net_revenue_usd_difference_in_differences
        - standalone_store_net_revenue_usd_difference_in_differences
        - subscription_net_revenue_usd_difference_in_differences
    ) > 0.01
       or abs(
        subscriber_total_net_revenue_usd_change
        - subscriber_standalone_store_net_revenue_usd_change
        - subscriber_subscription_net_revenue_usd_change
    ) > 0.01
       or abs(
        control_total_net_revenue_usd_change
        - control_standalone_store_net_revenue_usd_change
        - control_subscription_net_revenue_usd_change
    ) > 0.01

    union all

    select 'revenue_components_do_not_reconcile', cannibalization_segment_id
    from {{ ref('mart_hybrid_subscription__cannibalization_inputs') }}
    where abs(
        total_net_revenue_usd_difference_in_differences_sum
        - standalone_store_net_revenue_usd_difference_in_differences_sum
        - subscription_net_revenue_usd_difference_in_differences_sum
    ) > 0.01
       or abs(
        mean_total_net_revenue_usd_difference_in_differences
        - mean_standalone_store_net_revenue_usd_difference_in_differences
        - mean_subscription_net_revenue_usd_difference_in_differences
    ) > 0.01
)
select * from violations
