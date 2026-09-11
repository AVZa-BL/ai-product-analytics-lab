with expected_pairs as (
    -- Independent oracle: never derive expectations from published mart deltas.
    select
        pair.pair_id,
        pair.subscriber_player_id,
        pair.control_player_id,
        pair.subscriber_prior_payer_status,
        pair.control_prior_payer_status,
        pair.subscriber_platform,
        pair.subscriber_acquisition_channel,
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
        subscriber_pre.liveops_participation_count as subscriber_pre_liveops_participation_count,
        subscriber_post.liveops_participation_count as subscriber_post_liveops_participation_count,
        subscriber_post.liveops_participation_count - subscriber_pre.liveops_participation_count
            as subscriber_liveops_participation_count_change,
        control_pre.liveops_participation_count as control_pre_liveops_participation_count,
        control_post.liveops_participation_count as control_post_liveops_participation_count,
        control_post.liveops_participation_count - control_pre.liveops_participation_count
            as control_liveops_participation_count_change,
        (subscriber_post.liveops_participation_count - subscriber_pre.liveops_participation_count)
            - (control_post.liveops_participation_count - control_pre.liveops_participation_count)
            as liveops_participation_count_difference_in_differences,
        subscriber_pre.standalone_store_net_revenue_usd as subscriber_pre_standalone_store_net_revenue_usd,
        subscriber_post.standalone_store_net_revenue_usd as subscriber_post_standalone_store_net_revenue_usd,
        subscriber_post.standalone_store_net_revenue_usd - subscriber_pre.standalone_store_net_revenue_usd
            as subscriber_standalone_store_net_revenue_usd_change,
        control_pre.standalone_store_net_revenue_usd as control_pre_standalone_store_net_revenue_usd,
        control_post.standalone_store_net_revenue_usd as control_post_standalone_store_net_revenue_usd,
        control_post.standalone_store_net_revenue_usd - control_pre.standalone_store_net_revenue_usd
            as control_standalone_store_net_revenue_usd_change,
        (subscriber_post.standalone_store_net_revenue_usd - subscriber_pre.standalone_store_net_revenue_usd)
            - (control_post.standalone_store_net_revenue_usd - control_pre.standalone_store_net_revenue_usd)
            as standalone_store_net_revenue_usd_difference_in_differences,
        subscriber_pre.subscription_net_revenue_usd as subscriber_pre_subscription_net_revenue_usd,
        subscriber_post.subscription_net_revenue_usd as subscriber_post_subscription_net_revenue_usd,
        subscriber_post.subscription_net_revenue_usd - subscriber_pre.subscription_net_revenue_usd
            as subscriber_subscription_net_revenue_usd_change,
        control_pre.subscription_net_revenue_usd as control_pre_subscription_net_revenue_usd,
        control_post.subscription_net_revenue_usd as control_post_subscription_net_revenue_usd,
        control_post.subscription_net_revenue_usd - control_pre.subscription_net_revenue_usd
            as control_subscription_net_revenue_usd_change,
        (subscriber_post.subscription_net_revenue_usd - subscriber_pre.subscription_net_revenue_usd)
            - (control_post.subscription_net_revenue_usd - control_pre.subscription_net_revenue_usd)
            as subscription_net_revenue_usd_difference_in_differences,
        subscriber_pre.total_net_revenue_usd as subscriber_pre_total_net_revenue_usd,
        subscriber_post.total_net_revenue_usd as subscriber_post_total_net_revenue_usd,
        subscriber_post.total_net_revenue_usd - subscriber_pre.total_net_revenue_usd
            as subscriber_total_net_revenue_usd_change,
        control_pre.total_net_revenue_usd as control_pre_total_net_revenue_usd,
        control_post.total_net_revenue_usd as control_post_total_net_revenue_usd,
        control_post.total_net_revenue_usd - control_pre.total_net_revenue_usd
            as control_total_net_revenue_usd_change,
        (subscriber_post.total_net_revenue_usd - subscriber_pre.total_net_revenue_usd)
            - (control_post.total_net_revenue_usd - control_pre.total_net_revenue_usd)
            as total_net_revenue_usd_difference_in_differences
    from {{ ref('int_hybrid_subscription__matched_pairs') }} pair
    left join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} subscriber_pre
        on pair.subscriber_player_id = subscriber_pre.player_id
        and subscriber_pre.analysis_period = 'pre'
        and subscriber_pre.is_subscriber
    left join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} subscriber_post
        on pair.subscriber_player_id = subscriber_post.player_id
        and subscriber_post.analysis_period = 'post'
        and subscriber_post.is_subscriber
    left join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} control_pre
        on pair.control_player_id = control_pre.player_id
        and control_pre.analysis_period = 'pre'
        and not control_pre.is_subscriber
    left join {{ ref('fct_hybrid_subscription__player_behavior_28d') }} control_post
        on pair.control_player_id = control_post.player_id
        and control_post.analysis_period = 'post'
        and not control_post.is_subscriber
),
invalid_pair_formulas as (
    select expected.pair_id
    from expected_pairs expected
    left join {{ ref('mart_hybrid_subscription__matched_incrementality') }} published
        on expected.pair_id = published.pair_id
    where published.pair_id is null
       or expected.subscriber_pre_session_count is null
       or published.subscriber_pre_session_count is distinct from expected.subscriber_pre_session_count
       or expected.subscriber_post_session_count is null
       or published.subscriber_post_session_count is distinct from expected.subscriber_post_session_count
       or expected.subscriber_session_count_change is null
       or published.subscriber_session_count_change is distinct from expected.subscriber_session_count_change
       or expected.control_pre_session_count is null
       or published.control_pre_session_count is distinct from expected.control_pre_session_count
       or expected.control_post_session_count is null
       or published.control_post_session_count is distinct from expected.control_post_session_count
       or expected.control_session_count_change is null
       or published.control_session_count_change is distinct from expected.control_session_count_change
       or expected.session_count_difference_in_differences is null
       or published.session_count_difference_in_differences is distinct from expected.session_count_difference_in_differences
       or expected.subscriber_pre_liveops_participation_count is null
       or published.subscriber_pre_liveops_participation_count is distinct from expected.subscriber_pre_liveops_participation_count
       or expected.subscriber_post_liveops_participation_count is null
       or published.subscriber_post_liveops_participation_count is distinct from expected.subscriber_post_liveops_participation_count
       or expected.subscriber_liveops_participation_count_change is null
       or published.subscriber_liveops_participation_count_change is distinct from expected.subscriber_liveops_participation_count_change
       or expected.control_pre_liveops_participation_count is null
       or published.control_pre_liveops_participation_count is distinct from expected.control_pre_liveops_participation_count
       or expected.control_post_liveops_participation_count is null
       or published.control_post_liveops_participation_count is distinct from expected.control_post_liveops_participation_count
       or expected.control_liveops_participation_count_change is null
       or published.control_liveops_participation_count_change is distinct from expected.control_liveops_participation_count_change
       or expected.liveops_participation_count_difference_in_differences is null
       or published.liveops_participation_count_difference_in_differences is distinct from expected.liveops_participation_count_difference_in_differences
       or expected.subscriber_pre_standalone_store_net_revenue_usd is null
       or published.subscriber_pre_standalone_store_net_revenue_usd is distinct from expected.subscriber_pre_standalone_store_net_revenue_usd
       or expected.subscriber_post_standalone_store_net_revenue_usd is null
       or published.subscriber_post_standalone_store_net_revenue_usd is distinct from expected.subscriber_post_standalone_store_net_revenue_usd
       or expected.subscriber_standalone_store_net_revenue_usd_change is null
       or published.subscriber_standalone_store_net_revenue_usd_change is distinct from expected.subscriber_standalone_store_net_revenue_usd_change
       or expected.control_pre_standalone_store_net_revenue_usd is null
       or published.control_pre_standalone_store_net_revenue_usd is distinct from expected.control_pre_standalone_store_net_revenue_usd
       or expected.control_post_standalone_store_net_revenue_usd is null
       or published.control_post_standalone_store_net_revenue_usd is distinct from expected.control_post_standalone_store_net_revenue_usd
       or expected.control_standalone_store_net_revenue_usd_change is null
       or published.control_standalone_store_net_revenue_usd_change is distinct from expected.control_standalone_store_net_revenue_usd_change
       or expected.standalone_store_net_revenue_usd_difference_in_differences is null
       or published.standalone_store_net_revenue_usd_difference_in_differences is distinct from expected.standalone_store_net_revenue_usd_difference_in_differences
       or expected.subscriber_pre_subscription_net_revenue_usd is null
       or published.subscriber_pre_subscription_net_revenue_usd is distinct from expected.subscriber_pre_subscription_net_revenue_usd
       or expected.subscriber_post_subscription_net_revenue_usd is null
       or published.subscriber_post_subscription_net_revenue_usd is distinct from expected.subscriber_post_subscription_net_revenue_usd
       or expected.subscriber_subscription_net_revenue_usd_change is null
       or published.subscriber_subscription_net_revenue_usd_change is distinct from expected.subscriber_subscription_net_revenue_usd_change
       or expected.control_pre_subscription_net_revenue_usd is null
       or published.control_pre_subscription_net_revenue_usd is distinct from expected.control_pre_subscription_net_revenue_usd
       or expected.control_post_subscription_net_revenue_usd is null
       or published.control_post_subscription_net_revenue_usd is distinct from expected.control_post_subscription_net_revenue_usd
       or expected.control_subscription_net_revenue_usd_change is null
       or published.control_subscription_net_revenue_usd_change is distinct from expected.control_subscription_net_revenue_usd_change
       or expected.subscription_net_revenue_usd_difference_in_differences is null
       or published.subscription_net_revenue_usd_difference_in_differences is distinct from expected.subscription_net_revenue_usd_difference_in_differences
       or expected.subscriber_pre_total_net_revenue_usd is null
       or published.subscriber_pre_total_net_revenue_usd is distinct from expected.subscriber_pre_total_net_revenue_usd
       or expected.subscriber_post_total_net_revenue_usd is null
       or published.subscriber_post_total_net_revenue_usd is distinct from expected.subscriber_post_total_net_revenue_usd
       or expected.subscriber_total_net_revenue_usd_change is null
       or published.subscriber_total_net_revenue_usd_change is distinct from expected.subscriber_total_net_revenue_usd_change
       or expected.control_pre_total_net_revenue_usd is null
       or published.control_pre_total_net_revenue_usd is distinct from expected.control_pre_total_net_revenue_usd
       or expected.control_post_total_net_revenue_usd is null
       or published.control_post_total_net_revenue_usd is distinct from expected.control_post_total_net_revenue_usd
       or expected.control_total_net_revenue_usd_change is null
       or published.control_total_net_revenue_usd_change is distinct from expected.control_total_net_revenue_usd_change
       or expected.total_net_revenue_usd_difference_in_differences is null
       or published.total_net_revenue_usd_difference_in_differences is distinct from expected.total_net_revenue_usd_difference_in_differences
),
pairs as (
    select * from {{ ref('mart_hybrid_subscription__matched_incrementality') }}
),
missing_pair_ids as (
    select pair_id, subscriber_player_id, control_player_id
    from {{ ref('int_hybrid_subscription__matched_pairs') }}
    except all
    select pair_id, subscriber_player_id, control_player_id from pairs
),
unexpected_pair_ids as (
    select pair_id, subscriber_player_id, control_player_id from pairs
    except all
    select pair_id, subscriber_player_id, control_player_id
    from {{ ref('int_hybrid_subscription__matched_pairs') }}
),
expected_engagement_segments as (
    select
        subscriber_prior_payer_status as prior_payer_status,
        subscriber_platform as platform,
        subscriber_acquisition_channel as acquisition_channel,
        count(*) as matched_pair_count,
        count(distinct subscriber_player_id) as matched_subscriber_count,
        count(distinct control_player_id) as matched_control_count,
        sum(subscriber_session_count_change) as subscriber_session_count_change_sum,
        sum(control_session_count_change) as control_session_count_change_sum,
        sum(session_count_difference_in_differences)
            as session_count_difference_in_differences_sum,
        avg(subscriber_session_count_change) as mean_subscriber_session_count_change,
        avg(control_session_count_change) as mean_control_session_count_change,
        avg(session_count_difference_in_differences)
            as mean_session_count_difference_in_differences,
        sum(subscriber_liveops_participation_count_change)
            as subscriber_liveops_participation_count_change_sum,
        sum(control_liveops_participation_count_change)
            as control_liveops_participation_count_change_sum,
        sum(liveops_participation_count_difference_in_differences)
            as liveops_participation_count_difference_in_differences_sum,
        avg(subscriber_liveops_participation_count_change)
            as mean_subscriber_liveops_participation_count_change,
        avg(control_liveops_participation_count_change)
            as mean_control_liveops_participation_count_change,
        avg(liveops_participation_count_difference_in_differences)
            as mean_liveops_participation_count_difference_in_differences
    from expected_pairs
    group by
        subscriber_prior_payer_status,
        subscriber_platform,
        subscriber_acquisition_channel
),
published_engagement_segments as (
    select
        prior_payer_status,
        platform,
        acquisition_channel,
        matched_pair_count,
        matched_subscriber_count,
        matched_control_count,
        subscriber_session_count_change_sum,
        control_session_count_change_sum,
        session_count_difference_in_differences_sum,
        mean_subscriber_session_count_change,
        mean_control_session_count_change,
        mean_session_count_difference_in_differences,
        subscriber_liveops_participation_count_change_sum,
        control_liveops_participation_count_change_sum,
        liveops_participation_count_difference_in_differences_sum,
        mean_subscriber_liveops_participation_count_change,
        mean_control_liveops_participation_count_change,
        mean_liveops_participation_count_difference_in_differences
    from {{ ref('mart_hybrid_subscription__engagement_lift_inputs') }}
),
missing_published_segments as (
    select * from expected_engagement_segments
    except all
    select * from published_engagement_segments
),
unexpected_published_segments as (
    select * from published_engagement_segments
    except all
    select * from expected_engagement_segments
),
segment_differences as (
    select * from missing_published_segments
    union all
    select * from unexpected_published_segments
),
pair_counts as (
    select
        count(*) as matched_pair_count,
        count(distinct subscriber_player_id) as matched_subscriber_count,
        count(distinct control_player_id) as matched_control_count,
        count(*) filter (where pair_id is null) as null_pair_id_count
    from pairs
),
published_counts as (
    select coalesce(sum(matched_pair_count), 0) as matched_pair_count
    from {{ ref('mart_hybrid_subscription__engagement_lift_inputs') }}
),
population_summary as (
    select matched_pair_count
    from {{ ref('int_hybrid_subscription__match_population_summary') }}
),
population_summary_cardinality as (
    select count(*) as row_count
    from population_summary
),
violations as (
    select 'invalid_pair_formula' as violation, pair_id as row_id
    from invalid_pair_formulas

    union all

    select 'missing_pair' as violation, pair_id as row_id from missing_pair_ids

    union all

    select 'unexpected_pair', pair_id from unexpected_pair_ids

    union all

    select 'invalid_segment_arm_counts' as violation, engagement_segment_id as row_id
    from {{ ref('mart_hybrid_subscription__engagement_lift_inputs') }}
    where matched_pair_count <= 0
       or matched_pair_count is distinct from matched_subscriber_count
       or matched_pair_count is distinct from matched_control_count

    union all

    select 'engagement_segment_does_not_reconcile' as violation,
        prior_payer_status || '__' || platform || '__' || acquisition_channel as row_id
    from segment_differences

    union all

    select 'invalid_pair_counts', null::varchar
    from pair_counts pairs
    cross join published_counts published
    cross join population_summary population
    where pairs.null_pair_id_count != 0
       or pairs.matched_pair_count != pairs.matched_subscriber_count
       or pairs.matched_pair_count != pairs.matched_control_count
       or pairs.matched_pair_count != published.matched_pair_count
       or pairs.matched_pair_count != population.matched_pair_count

    union all

    select 'invalid_population_summary_cardinality', null::varchar
    from population_summary_cardinality
    where row_count != 1
)
select * from violations
