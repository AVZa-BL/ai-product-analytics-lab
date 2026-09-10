select *
from {{ ref('int_hybrid_subscription__analysis_population') }}
where is_population_eligible
  and (
    eligible_exposure_at_utc is null
    or index_at_utc != eligible_exposure_at_utc
    or (is_subscriber and first_subscription_at_utc <= index_at_utc)
  )
