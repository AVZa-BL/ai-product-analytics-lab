{{ config(tags=['live_strategy']) }}

select
    r.purchase_id,
    r.player_id,
    r.purchased_at_utc,
    r.purchased_at_utc::date as purchase_date_utc,
    r.platform_transaction_id,
    r.product_id,
    r.gross_amount,
    r.currency_code,
    r.final_purchase_status,
    r.gross_usd,
    r.refund_usd,
    r.net_usd,
    r.refund_reconciled_at_utc,
    p.platform,
    p.country_code,
    p.acquisition_channel,
    p.install_app_version
from {{ ref('int_live_strategy__purchase_reconciliation') }} r
inner join {{ ref('dim_live_strategy__players') }} p
    on r.player_id = p.player_id
