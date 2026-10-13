select
    cast(payment_id as varchar) as payment_id,
    cast(subscription_id as varchar) as subscription_id,
    cast(user_id as varchar) as user_id,
    cast(payment_at as timestamp) as payment_at,
    cast(amount_local as decimal(18, 2)) as amount_local,
    cast(currency_code as varchar) as currency_code,
    cast(amount_usd as decimal(18, 2)) as amount_usd,
    cast(payment_status as varchar) as payment_status,
    cast(refund_at as timestamp) as refund_at
from {{ source('subscription_raw', 'subscription_payments') }}
