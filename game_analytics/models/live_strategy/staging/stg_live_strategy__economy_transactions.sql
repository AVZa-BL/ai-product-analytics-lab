{{ config(tags=['live_strategy']) }}

select
    cast(ledger_entry_id as varchar) as ledger_entry_id,
    cast(player_id as varchar) as player_id,
    cast(occurred_at_utc as timestamp) as occurred_at_utc,
    lower(trim(cast(transaction_type as varchar))) as transaction_type,
    cast(amount as decimal(18, 4)) as amount,
    lower(trim(cast(currency_type as varchar))) as currency_type,
    cast(purchase_id as varchar) as purchase_id
from {{ source('live_strategy_raw', 'economy_transactions') }}
