select
    player_id || '__' || analysis_period as player_period_id,
    player_id,
    analysis_period,
    period_start_at_utc,
    period_end_at_utc,
    prior_payer_status,
    platform,
    acquisition_channel,
    is_subscriber,
    has_eligible_exposure,
    session_count,
    session_duration_seconds,
    liveops_participation_count,
    subscription_net_revenue_usd,
    standalone_store_net_revenue_usd,
    total_net_revenue_usd,
    discount_amount_usd
from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
