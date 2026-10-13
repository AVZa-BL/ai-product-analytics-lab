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

union all

select
    'experiment_exposure_after_purchase' as incident_code,
    count(*) filter (where exclusion_reason = 'exposed_after_first_purchase') as affected_rows
from {{ ref('int_hybrid_subscription__experiment_eligible_population') }}

union all

select
    'experiment_sample_ratio_mismatch' as incident_code,
    cast(coalesce(sum(assigned_players) filter (where is_srm_flagged), 0) as bigint) as affected_rows
from {{ ref('int_hybrid_subscription__experiment_srm') }}

union all

select
    'experiment_mid_test_config_change' as incident_code,
    count(*) filter (where arm_config_version > initial_config_version) as affected_rows
from (
    select
        arm_config_version,
        min(arm_config_version) over (partition by experiment_id, arm) as initial_config_version
    from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
)
