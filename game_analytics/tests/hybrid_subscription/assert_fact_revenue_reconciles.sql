with fact_total as (
    select coalesce(sum(recognized_net_revenue_usd), 0) as amount
    from {{ ref('fct_hybrid_subscription__store_transactions') }}
),
source_total as (
    select coalesce(sum(
        case
            when transaction_status in ('succeeded', 'refunded')
                then net_amount_usd - refund_amount_usd
            else 0
        end
    ), 0) as amount
    from {{ ref('stg_hybrid_subscription__store_transactions') }}
)
select fact_total.amount as fact_amount, source_total.amount as source_amount
from fact_total
cross join source_total
where abs(fact_total.amount - source_total.amount) > 0.01
