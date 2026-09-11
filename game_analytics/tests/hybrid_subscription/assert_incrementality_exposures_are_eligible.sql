select *
from {{ ref('fct_hybrid_subscription__marketing_exposures') }}
where (
        is_incrementality_eligible
        and (
            eligible_campaign_id is null
            or eligible_experiment_arm is null
            or eligible_exposed_at_utc is null
            or eligible_exposed_at_utc > first_subscription_at_utc
        )
    )
    or (
        not is_incrementality_eligible
        and (
            eligible_campaign_id is not null
            or eligible_experiment_arm is not null
            or eligible_exposed_at_utc is not null
        )
    )
