select
    'duplicate_store_webhook' as incident_code,
    count(*) filter (where is_duplicate_webhook) as affected_rows
from {{ ref('stg_hybrid_subscription__store_transactions') }}

union all

select
    'mixed_timestamp_mismatch' as incident_code,
    (
        select count(*) filter (where has_timestamp_mismatch)
        from {{ ref('stg_hybrid_subscription__sessions') }}
    ) + (
        select count(*) filter (where has_timestamp_mismatch)
        from {{ ref('stg_hybrid_subscription__store_transactions') }}
    ) as affected_rows

union all

select
    'missing_subscription_grant_link' as incident_code,
    count(*) filter (where has_missing_subscription_link) as affected_rows
from {{ ref('stg_hybrid_subscription__currency_ledger') }}

union all

select
    'post_subscription_exposure' as incident_code,
    count(*) filter (where ineligibility_reason = 'exposure_after_subscription') as affected_rows
from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}

union all

select 'analysis_population_exclusion' as incident_code,
    count(*) filter (where not is_population_eligible) as affected_rows
from {{ ref('int_hybrid_subscription__analysis_population') }}
