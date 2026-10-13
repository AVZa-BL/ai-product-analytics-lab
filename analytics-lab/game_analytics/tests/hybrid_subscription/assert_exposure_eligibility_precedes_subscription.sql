select *
from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}
where is_incrementality_eligible
    and first_subscription_at_utc is not null
    and exposed_at_utc > first_subscription_at_utc
