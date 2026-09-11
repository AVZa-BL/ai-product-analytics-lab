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
