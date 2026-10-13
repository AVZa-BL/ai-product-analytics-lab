select
    'duplicate_store_webhook' as incident_code,
    transaction_id as record_id
from {{ ref('fct_hybrid_subscription__store_transactions') }}
where source_webhook_rows > 1 and not is_duplicate_webhook

union all

select
    'missing_subscription_grant_link',
    ledger_entry_id
from {{ ref('fct_hybrid_subscription__currency_grants') }}
where entry_type = 'subscription_grant'
    and not is_reconciled
    and reconciled_subscription_currency_amount != 0

union all

select
    'post_subscription_exposure',
    exposure_id
from {{ ref('fct_hybrid_subscription__marketing_exposures') }}
where not is_incrementality_eligible
    and (
        eligible_campaign_id is not null
        or eligible_experiment_arm is not null
        or eligible_exposed_at_utc is not null
    )

union all

select
    'cancellation_pending_expiry',
    subscription_id
from {{ ref('fct_hybrid_subscription__subscription_entitlements') }}
where is_canceled_pending_expiry
    and entitlement_end_at_utc != contractual_period_end_at_utc

union all

select
    'experiment_exposure_after_purchase',
    player_id
from {{ ref('int_hybrid_subscription__experiment_eligible_population') }}
where is_exposed_after_first_purchase
    and is_eligible

union all

select
    'experiment_sample_ratio_mismatch',
    experiment_id || ':' || arm
from {{ ref('mart_hybrid_subscription__experiment_readout') }}
where is_srm_flagged
    and (
        mean_sessions_7d_difference_vs_control is not null
        or purchase_rate_difference_vs_control is not null
        or mean_revenue_usd_7d_difference_vs_control is not null
    )

union all

select
    'experiment_mid_test_config_change',
    readout.experiment_id || ':' || readout.arm
from {{ ref('mart_hybrid_subscription__experiment_readout') }} readout
join (
    select experiment_id, arm, count(distinct arm_config_version) as versions
    from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
    group by experiment_id, arm
) assignments using (experiment_id, arm)
where assignments.versions > 1
    and not readout.has_config_change
