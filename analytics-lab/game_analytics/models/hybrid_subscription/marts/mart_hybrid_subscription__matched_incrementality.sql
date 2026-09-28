select
    pair.pair_id,
    pair.subscriber_sequence,
    pair.subscriber_player_id,
    pair.control_player_id,
    pair.subscriber_prior_payer_status,
    pair.control_prior_payer_status,
    pair.subscriber_platform,
    pair.control_platform,
    pair.subscriber_acquisition_channel,
    pair.control_acquisition_channel,
    pair.pre_session_count_distance,
    population.eligible_subscriber_count,
    population.eligible_control_count,
    population.matched_pair_count,
    population.unmatched_subscriber_count,
    population.unmatched_control_count,

    subscriber_pre.session_count as subscriber_pre_session_count,
    subscriber_post.session_count as subscriber_post_session_count,
    subscriber_post.session_count - subscriber_pre.session_count
        as subscriber_session_count_change,
    control_pre.session_count as control_pre_session_count,
    control_post.session_count as control_post_session_count,
    control_post.session_count - control_pre.session_count
        as control_session_count_change,
    (subscriber_post.session_count - subscriber_pre.session_count)
        - (control_post.session_count - control_pre.session_count)
        as session_count_difference_in_differences,

    subscriber_pre.liveops_participation_count
        as subscriber_pre_liveops_participation_count,
    subscriber_post.liveops_participation_count
        as subscriber_post_liveops_participation_count,
    subscriber_post.liveops_participation_count
        - subscriber_pre.liveops_participation_count
        as subscriber_liveops_participation_count_change,
    control_pre.liveops_participation_count
        as control_pre_liveops_participation_count,
    control_post.liveops_participation_count
        as control_post_liveops_participation_count,
    control_post.liveops_participation_count
        - control_pre.liveops_participation_count
        as control_liveops_participation_count_change,
    (subscriber_post.liveops_participation_count
        - subscriber_pre.liveops_participation_count)
        - (control_post.liveops_participation_count
            - control_pre.liveops_participation_count)
        as liveops_participation_count_difference_in_differences,

    subscriber_pre.standalone_store_net_revenue_usd
        as subscriber_pre_standalone_store_net_revenue_usd,
    subscriber_post.standalone_store_net_revenue_usd
        as subscriber_post_standalone_store_net_revenue_usd,
    subscriber_post.standalone_store_net_revenue_usd
        - subscriber_pre.standalone_store_net_revenue_usd
        as subscriber_standalone_store_net_revenue_usd_change,
    control_pre.standalone_store_net_revenue_usd
        as control_pre_standalone_store_net_revenue_usd,
    control_post.standalone_store_net_revenue_usd
        as control_post_standalone_store_net_revenue_usd,
    control_post.standalone_store_net_revenue_usd
        - control_pre.standalone_store_net_revenue_usd
        as control_standalone_store_net_revenue_usd_change,
    (subscriber_post.standalone_store_net_revenue_usd
        - subscriber_pre.standalone_store_net_revenue_usd)
        - (control_post.standalone_store_net_revenue_usd
            - control_pre.standalone_store_net_revenue_usd)
        as standalone_store_net_revenue_usd_difference_in_differences,

    subscriber_pre.subscription_net_revenue_usd
        as subscriber_pre_subscription_net_revenue_usd,
    subscriber_post.subscription_net_revenue_usd
        as subscriber_post_subscription_net_revenue_usd,
    subscriber_post.subscription_net_revenue_usd
        - subscriber_pre.subscription_net_revenue_usd
        as subscriber_subscription_net_revenue_usd_change,
    control_pre.subscription_net_revenue_usd
        as control_pre_subscription_net_revenue_usd,
    control_post.subscription_net_revenue_usd
        as control_post_subscription_net_revenue_usd,
    control_post.subscription_net_revenue_usd
        - control_pre.subscription_net_revenue_usd
        as control_subscription_net_revenue_usd_change,
    (subscriber_post.subscription_net_revenue_usd
        - subscriber_pre.subscription_net_revenue_usd)
        - (control_post.subscription_net_revenue_usd
            - control_pre.subscription_net_revenue_usd)
        as subscription_net_revenue_usd_difference_in_differences,

    subscriber_pre.total_net_revenue_usd
        as subscriber_pre_total_net_revenue_usd,
    subscriber_post.total_net_revenue_usd
        as subscriber_post_total_net_revenue_usd,
    subscriber_post.total_net_revenue_usd
        - subscriber_pre.total_net_revenue_usd
        as subscriber_total_net_revenue_usd_change,
    control_pre.total_net_revenue_usd
        as control_pre_total_net_revenue_usd,
    control_post.total_net_revenue_usd
        as control_post_total_net_revenue_usd,
    control_post.total_net_revenue_usd
        - control_pre.total_net_revenue_usd
        as control_total_net_revenue_usd_change,
    (subscriber_post.total_net_revenue_usd
        - subscriber_pre.total_net_revenue_usd)
        - (control_post.total_net_revenue_usd
            - control_pre.total_net_revenue_usd)
        as total_net_revenue_usd_difference_in_differences
from {{ ref('int_hybrid_subscription__matched_pairs') }} pair
cross join {{ ref('int_hybrid_subscription__match_population_summary') }} population
join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} subscriber_pre
    on pair.subscriber_player_id = subscriber_pre.player_id
    and subscriber_pre.analysis_period = 'pre'
    and subscriber_pre.is_subscriber
join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} subscriber_post
    on pair.subscriber_player_id = subscriber_post.player_id
    and subscriber_post.analysis_period = 'post'
    and subscriber_post.is_subscriber
join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} control_pre
    on pair.control_player_id = control_pre.player_id
    and control_pre.analysis_period = 'pre'
    and not control_pre.is_subscriber
join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} control_post
    on pair.control_player_id = control_post.player_id
    and control_post.analysis_period = 'post'
    and not control_post.is_subscriber
