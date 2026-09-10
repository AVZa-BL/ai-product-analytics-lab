{{ config(tags=['live_strategy']) }}

with refunds as (
    select
        purchase_id,
        -sum(amount) as refund_usd,
        max(occurred_at_utc) as refund_reconciled_at_utc
    from {{ ref('stg_live_strategy__economy_transactions') }}
    where transaction_type = 'refund'
      and purchase_id is not null
    group by 1
)

select
    p.purchase_id,
    p.player_id,
    case
        when p.purchase_status = 'cancelled' then 'cancelled'
        when coalesce(r.refund_usd, 0) = p.gross_usd then 'refunded'
        else 'completed'
    end as final_purchase_status,
    p.gross_usd,
    coalesce(r.refund_usd, 0) as refund_usd,
    p.gross_usd - coalesce(r.refund_usd, 0) as net_usd,
    r.refund_reconciled_at_utc
from {{ ref('stg_live_strategy__purchases') }} p
left join refunds r
    on p.purchase_id = r.purchase_id
