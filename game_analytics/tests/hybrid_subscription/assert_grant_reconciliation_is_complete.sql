select *
from {{ ref('int_hybrid_subscription__grant_reconciliation') }}
where not is_reconciled
    or grant_link_status = 'no_grant'
