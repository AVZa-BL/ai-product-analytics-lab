select
    cast(ledger_entry_id as varchar) as ledger_entry_id,
    cast(player_id as varchar) as player_id,
    cast(entry_type as varchar) as entry_type,
    cast(currency_amount as bigint) as currency_amount,
    cast(source_subscription_transaction_id as varchar) as source_subscription_transaction_id,
    cast(occurred_at_raw as varchar) as occurred_at_raw,
    cast(occurred_at_local as timestamp) as occurred_at_local,
    cast(occurred_at_timezone as varchar) as occurred_at_timezone,
    timezone(occurred_at_timezone, cast(occurred_at_local as timestamp)) as occurred_at_utc,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id,
    entry_type = 'subscription_grant'
        and source_subscription_transaction_id is null as has_missing_subscription_link
from {{ source('hybrid_subscription_raw', 'currency_ledger') }}
