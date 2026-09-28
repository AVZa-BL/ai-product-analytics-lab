select
    p.payment_id,
    p.subscription_id,
    p.user_id,
    p.payment_at,
    cast(p.payment_at as date) as payment_date,
    p.amount_local,
    p.currency_code,
    p.amount_usd,
    p.payment_status,
    p.refund_at,
    p.payment_status = 'succeeded' as is_successful,
    p.payment_status = 'failed' as is_failed,
    p.refund_at is not null or p.payment_status = 'refunded' as is_refunded,
    cast(case
        when p.payment_status = 'succeeded' and p.refund_at is null then p.amount_usd
        else 0
    end as decimal(18, 2)) as recognized_gross_revenue_usd,
    u.campaign_id
from {{ ref('stg_subscription__payments') }} p
join {{ ref('dim_subscription__users') }} u using (user_id)
