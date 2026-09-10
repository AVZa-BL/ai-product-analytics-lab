select *
from {{ ref('int_hybrid_subscription__analysis_population') }}
where is_population_eligible
  and (
    eligible_exposure_at_utc is null
    or nullif(trim(player_id), '') is null
    or nullif(trim(prior_payer_status), '') is null
    or prior_payer_status not in ('prior_payer', 'prior_nonpayer')
    or nullif(trim(platform), '') is null
    or nullif(trim(acquisition_channel), '') is null
    or index_at_utc is distinct from eligible_exposure_at_utc
    or (is_subscriber and first_subscription_at_utc <= index_at_utc)
    or observation_start_at_utc is null
    or observation_end_at_utc is null
    or index_at_utc - interval '672 hours' < observation_start_at_utc
    or index_at_utc + interval '672 hours' > observation_end_at_utc
    or not coalesce(are_source_watermarks_valid, false)
    or ingestion_mature_through_at_utc is null
    or index_at_utc + interval '672 hours' > ingestion_mature_through_at_utc
  )
