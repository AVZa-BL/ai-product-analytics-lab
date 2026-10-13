{{ config(tags=['live_strategy']) }}

select
    cast(purchase_id as varchar) as purchase_id,
    cast(player_id as varchar) as player_id,
    cast(purchased_at_utc as timestamp) as purchased_at_utc,
    lower(trim(cast(purchase_status as varchar))) as purchase_status,
    cast(platform_transaction_id as varchar) as platform_transaction_id,
    lower(trim(cast(product_id as varchar))) as product_id,
    cast(gross_amount as decimal(18, 4)) as gross_amount,
    lower(trim(cast(currency_code as varchar))) as currency_code,
    cast(gross_usd as decimal(18, 4)) as gross_usd
from {{ source('live_strategy_raw', 'purchases') }}
