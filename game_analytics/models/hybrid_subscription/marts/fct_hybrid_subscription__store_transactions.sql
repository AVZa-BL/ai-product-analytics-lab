select
    transaction.transaction_id,
    transaction.player_id,
    transaction.sku,
    transaction.product_type,
    transaction.transaction_status,
    transaction.transaction_at_utc,
    transaction.gross_amount_usd,
    transaction.discount_amount_usd,
    transaction.refund_amount_usd,
    transaction.net_amount_usd,
    case
        when transaction.transaction_status in ('succeeded', 'refunded')
            then transaction.net_amount_usd - transaction.refund_amount_usd
        else 0
    end as recognized_net_revenue_usd,
    transaction.currency_code,
    transaction.source_webhook_rows,
    transaction.is_duplicate_webhook,
    transaction.has_timestamp_mismatch,
    player.prior_payer_status,
    transaction.scenario_run_id
from {{ ref('stg_hybrid_subscription__store_transactions') }} transaction
join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)
