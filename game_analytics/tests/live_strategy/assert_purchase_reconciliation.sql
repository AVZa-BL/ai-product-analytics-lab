select purchase_id
from {{ ref('int_live_strategy__purchase_reconciliation') }}
where net_usd <> gross_usd - refund_usd
   or final_purchase_status not in ('completed', 'refunded', 'cancelled')
