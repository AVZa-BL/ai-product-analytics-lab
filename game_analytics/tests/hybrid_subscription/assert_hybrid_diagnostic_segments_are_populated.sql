with pairs as (
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
    from pairs
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
