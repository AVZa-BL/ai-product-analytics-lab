select
    analysis_period || '__' || prior_payer_status || '__'
        || platform || '__' || acquisition_channel || '__'
        || cast(is_subscriber as varchar) as engagement_segment_id,
    analysis_period,
    is_subscriber,
    prior_payer_status,
    platform,
    acquisition_channel,
    count(*) as eligible_player_count,
    sum(case when has_eligible_exposure then 1 else 0 end) as exposed_player_count,
    avg(session_count) as mean_sessions_per_player,
    avg(session_duration_seconds) as mean_session_seconds_per_player,
    avg(liveops_participation_count) as mean_liveops_participations_per_player
from {{ ref('fct_hybrid_subscription__player_behavior_28d') }}
group by
    analysis_period,
    is_subscriber,
    prior_payer_status,
    platform,
    acquisition_channel
