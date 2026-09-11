with observation as (
    select min(ingestion_mature_through_at_utc) as as_of_at_utc
    from {{ ref('int_hybrid_subscription__source_watermarks') }}
    having count(*) = 3 and bool_and(is_source_valid)
        and count(ingestion_mature_through_at_utc) = 3
)
select cohort.subscription_cohort_id
from {{ ref('mart_hybrid_subscription__subscription_cohorts') }} cohort
cross join observation
where cohort.as_of_at_utc is distinct from observation.as_of_at_utc
   or (cohort.cohort_type = 'eligible_exposure' and (
       cohort.is_conversion_mature is distinct from coalesce(
           cohort.cohort_latest_at_utc + interval '672 hours' <= observation.as_of_at_utc, false)
       or (cohort.cohort_latest_at_utc + interval '672 hours' > observation.as_of_at_utc
           and cohort.subscription_conversion_rate is not null)))
   or (cohort.cohort_type = 'subscription_start' and (
       cohort.is_d30_mature is distinct from coalesce(
           cohort.cohort_latest_at_utc + interval '720 hours' <= observation.as_of_at_utc, false)
       or (cohort.cohort_latest_at_utc + interval '720 hours' > observation.as_of_at_utc
           and cohort.d30_subscriber_retention_rate is not null)))
   or (not cohort.is_conversion_mature and cohort.subscription_conversion_rate is not null)
   or (not cohort.is_d30_mature and cohort.d30_subscriber_retention_rate is not null)
