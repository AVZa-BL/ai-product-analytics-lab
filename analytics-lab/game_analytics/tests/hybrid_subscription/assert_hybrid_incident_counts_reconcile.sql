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

    union all

    select 'analysis_population_exclusion', count(*) filter (where not is_population_eligible)
    from {{ ref('int_hybrid_subscription__analysis_population') }}

    union all

    select
        'experiment_exposure_after_purchase',
        count(*) filter (where first_exposed_at_utc > first_purchase_at_utc)
    from (
        select
            exposure.player_id,
            min(exposure.exposed_at_utc) as first_exposed_at_utc,
            max(outcome.first_purchase_at_utc) as first_purchase_at_utc
        from {{ ref('stg_hybrid_subscription__experiment_exposures') }} exposure
        join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
        group by exposure.player_id
    )

    union all

    select
        'experiment_sample_ratio_mismatch',
        cast(coalesce(sum(total) filter (where exp(-chi_square / 2) < 0.001), 0) as bigint)
    from (
        select
            c + b + v as total,
            (
                power(c - (c + b + v) / 3.0, 2)
                + power(b - (c + b + v) / 3.0, 2)
                + power(v - (c + b + v) / 3.0, 2)
            ) / ((c + b + v) / 3.0) as chi_square
        from (
            select
                count(*) filter (where arm = 'control') as c,
                count(*) filter (where arm = 'variant_b') as b,
                count(*) filter (where arm = 'variant_c') as v
            from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
            group by experiment_id
        )
    )

    union all

    select 'experiment_mid_test_config_change', count(*)
    from {{ ref('stg_hybrid_subscription__experiment_assignments') }} assignment
    join (
        select experiment_id, arm, min(arm_config_version) as initial_version
        from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
        group by experiment_id, arm
    ) initial using (experiment_id, arm)
    where assignment.arm_config_version > initial.initial_version
)
select
    coalesce(expected.incident_code, actual.incident_code) as incident_code,
    expected.affected_rows as expected_rows,
    actual.affected_rows as actual_rows
from expected
full outer join {{ ref('mart_hybrid_subscription__data_quality_incidents') }} actual
    using (incident_code)
where expected.affected_rows is distinct from actual.affected_rows
