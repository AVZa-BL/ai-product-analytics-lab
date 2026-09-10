select
    exposure_id,
    player_id,
    campaign_id,
    experiment_arm,
    channel,
    exposed_at_utc,
    first_subscription_at_utc,
    is_pre_subscription_exposure,
    is_incrementality_eligible,
    ineligibility_reason,
    case when is_incrementality_eligible then campaign_id end as eligible_campaign_id,
    case when is_incrementality_eligible then experiment_arm end as eligible_experiment_arm,
    case when is_incrementality_eligible then exposed_at_utc end as eligible_exposed_at_utc,
    scenario_run_id
from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}
