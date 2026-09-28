select
    cast(sku as varchar) as sku,
    cast(product_type as varchar) as product_type,
    cast(list_price_usd as decimal(18, 2)) as list_price_usd,
    cast(subscriber_discount_rate as decimal(9, 4)) as subscriber_discount_rate,
    cast(currency_code as varchar) as currency_code,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'product_catalogue') }}
