select
    subscriber_prior_payer_status || '__' || subscriber_platform || '__'
        || subscriber_acquisition_channel as engagement_segment_id,
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
from {{ ref('mart_hybrid_subscription__matched_incrementality') }}
group by
    subscriber_prior_payer_status,
    subscriber_platform,
    subscriber_acquisition_channel
