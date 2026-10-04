with detected as (
    select incident_code, affected_rows
    from {{ ref('int_hybrid_subscription__quality_audit') }}

    union all

    select
        'cancellation_pending_expiry' as incident_code,
        count(*) filter (where is_canceled_pending_expiry) as affected_rows
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }}
)
select
    incident_code as incident_id,
    incident_code,
    case incident_code
        when 'duplicate_store_webhook' then 'transaction_delivery'
        when 'mixed_timestamp_mismatch' then 'timestamp_normalization'
        when 'missing_subscription_grant_link' then 'grant_reconciliation'
        when 'post_subscription_exposure' then 'experiment_eligibility'
        when 'cancellation_pending_expiry' then 'entitlement_semantics'
        when 'analysis_population_exclusion' then 'analysis_eligibility'
        when 'experiment_exposure_after_purchase' then 'experiment_exposure_timing'
        when 'experiment_sample_ratio_mismatch' then 'experiment_assignment_integrity'
        when 'experiment_mid_test_config_change' then 'experiment_configuration'
    end as incident_category,
    case incident_code
        when 'missing_subscription_grant_link' then 'high'
        when 'post_subscription_exposure' then 'high'
        when 'mixed_timestamp_mismatch' then 'high'
        when 'experiment_exposure_after_purchase' then 'high'
        when 'experiment_sample_ratio_mismatch' then 'high'
        else 'medium'
    end as severity,
    affected_rows,
    case incident_code
        when 'duplicate_store_webhook' then 'recognized_net_revenue_usd'
        when 'mixed_timestamp_mismatch' then 'daily_and_windowed_metrics'
        when 'missing_subscription_grant_link' then 'reconciled_subscription_currency_amount'
        when 'post_subscription_exposure' then 'incrementality_eligibility'
        when 'cancellation_pending_expiry' then 'active_subscription_entitlement'
        when 'analysis_population_exclusion' then 'matched_outcome_estimates'
        when 'experiment_exposure_after_purchase' then 'eligible_population_outcomes'
        when 'experiment_sample_ratio_mismatch' then 'arm_comparison_validity'
        when 'experiment_mid_test_config_change' then 'pooled_arm_outcomes'
    end as affected_metric,
    case incident_code
        when 'duplicate_store_webhook'
            then 'Use the latest ingested webhook per transaction and retain duplicate evidence.'
        when 'mixed_timestamp_mismatch'
            then 'Derive UTC from local timestamp plus named time zone and retain the source mismatch flag.'
        when 'missing_subscription_grant_link'
            then 'Set reconciled subscription currency to zero until a transaction link is present.'
        when 'post_subscription_exposure'
            then 'Null approved exposure fields and exclude the row from incrementality analysis.'
        when 'cancellation_pending_expiry'
            then 'Preserve access through contractual period end; cancellation disables renewal only.'
        when 'analysis_population_exclusion'
            then 'Exclude invalid identity/covariates, ineligible exposure and incomplete source windows; retain all exclusion reasons and counts in population summary.'
        when 'experiment_exposure_after_purchase'
            then 'Exclude the player from outcome figures, retain the row with its exclusion reason, and publish assigned and excluded counts.'
        when 'experiment_sample_ratio_mismatch'
            then 'Publish the statistic and flag, and set every difference against control to NULL for the experiment.'
        when 'experiment_mid_test_config_change'
            then 'Disclose, do not correct: publish has_config_change and the version columns by date; outcomes stay pooled across versions.'
    end as containment_rule,
    case
        when affected_rows > 0 then 'contained'
        else 'clear'
    end as decision_status
from detected
