with observation as (
    select max(observed_at_utc) as as_of_at_utc
    from (
        select started_at_utc as observed_at_utc from {{ ref('fct_hybrid_subscription__sessions') }}
        union all
        select transaction_at_utc from {{ ref('fct_hybrid_subscription__store_transactions') }}
        union all
        select participated_at_utc from {{ ref('stg_hybrid_subscription__live_event_participation') }}
    ) timestamps
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
