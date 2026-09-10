with expected as (
    select
        'duplicate_store_webhook' as incident_code,
        count(*) filter (where is_duplicate_webhook) as affected_rows
    from {{ ref('stg_hybrid_subscription__store_transactions') }}

    union all

    select
        'mixed_timestamp_mismatch',
        (
            select count(*) filter (where has_timestamp_mismatch)
            from {{ ref('stg_hybrid_subscription__sessions') }}
        ) + (
            select count(*) filter (where has_timestamp_mismatch)
            from {{ ref('stg_hybrid_subscription__store_transactions') }}
        )

    union all

    select
        'missing_subscription_grant_link',
        count(*) filter (where has_missing_subscription_link)
    from {{ ref('stg_hybrid_subscription__currency_ledger') }}

    union all

    select
        'post_subscription_exposure',
        count(*) filter (where ineligibility_reason = 'exposure_after_subscription')
    from {{ ref('int_hybrid_subscription__marketing_exposure_eligibility') }}

    union all

    select
        'cancellation_pending_expiry',
        count(*) filter (where is_canceled_pending_expiry)
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }}
)
select
    coalesce(expected.incident_code, actual.incident_code) as incident_code,
    expected.affected_rows as expected_rows,
    actual.affected_rows as actual_rows
from expected
full outer join {{ ref('mart_hybrid_subscription__data_quality_incidents') }} actual
    using (incident_code)
where expected.affected_rows is distinct from actual.affected_rows
