select *
from {{ ref('int_hybrid_subscription__analysis_population') }}
where is_population_eligible
  and (
    eligible_exposure_at_utc is null
    or index_at_utc is distinct from eligible_exposure_at_utc
    or (is_subscriber and first_subscription_at_utc <= index_at_utc)
    or observation_start_at_utc is null
    or observation_end_at_utc is null
    or index_at_utc - interval '28 days' < observation_start_at_utc
    or index_at_utc + interval '28 days' > observation_end_at_utc
  )
