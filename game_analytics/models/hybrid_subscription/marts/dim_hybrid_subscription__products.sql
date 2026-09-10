select
    sku,
    product_type,
    list_price_usd,
    subscriber_discount_rate,
    currency_code,
    scenario_run_id
from {{ ref('stg_hybrid_subscription__product_catalogue') }}
