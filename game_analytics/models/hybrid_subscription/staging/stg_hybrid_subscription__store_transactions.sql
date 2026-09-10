with typed as (
    select
        cast(transaction_id as varchar) as transaction_id,
        cast(player_id as varchar) as player_id,
        cast(sku as varchar) as sku,
        cast(product_type as varchar) as product_type,
        cast(transaction_status as varchar) as transaction_status,
        cast(gross_amount_usd as decimal(18, 2)) as gross_amount_usd,
        cast(discount_amount_usd as decimal(18, 2)) as discount_amount_usd,
        cast(refund_amount_usd as decimal(18, 2)) as refund_amount_usd,
        cast(amount_usd as decimal(18, 2)) as net_amount_usd,
        cast(currency_code as varchar) as currency_code,
        cast(transaction_at_raw as varchar) as transaction_at_raw,
        cast(transaction_at_local as timestamp) as transaction_at_local,
        cast(transaction_at_timezone as varchar) as transaction_at_timezone,
        timezone(transaction_at_timezone, cast(transaction_at_local as timestamp)) as transaction_at_utc,
        cast(transaction_at_utc as timestamptz) as source_transaction_at_utc,
        timezone(transaction_at_timezone, cast(transaction_at_local as timestamp))
            != cast(transaction_at_utc as timestamptz) as has_timestamp_mismatch,
        cast(ingested_at_utc as timestamptz) as ingested_at_utc,
        cast(scenario_run_id as varchar) as scenario_run_id
    from {{ source('hybrid_subscription_raw', 'store_transactions') }}
),
ranked as (
    select
        *,
        count(*) over (partition by transaction_id) as source_webhook_rows,
        row_number() over (
            partition by transaction_id
            order by ingested_at_utc desc, scenario_run_id desc
        ) as webhook_rank
    from typed
)
select
    * exclude (webhook_rank),
    source_webhook_rows > 1 as is_duplicate_webhook
from ranked
where webhook_rank = 1
