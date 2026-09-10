select
    ledger.ledger_entry_id,
    ledger.player_id,
    ledger.entry_type,
    ledger.currency_amount,
    ledger.occurred_at_utc,
    ledger.source_subscription_transaction_id,
    case
        when ledger.entry_type != 'subscription_grant' then 'not_applicable'
        when ledger.source_subscription_transaction_id is null then 'missing_link'
        when reconciliation.transaction_id is not null then 'linked'
        else 'orphaned_link'
    end as grant_link_status,
    ledger.entry_type != 'subscription_grant'
        or reconciliation.transaction_id is not null as is_reconciled,
    case
        when ledger.entry_type = 'subscription_grant'
            and reconciliation.transaction_id is not null
            then ledger.currency_amount
        else 0
    end as reconciled_subscription_currency_amount,
    ledger.has_missing_subscription_link,
    ledger.scenario_run_id
from {{ ref('stg_hybrid_subscription__currency_ledger') }} ledger
left join {{ ref('int_hybrid_subscription__grant_reconciliation') }} reconciliation
    on ledger.source_subscription_transaction_id = reconciliation.transaction_id
