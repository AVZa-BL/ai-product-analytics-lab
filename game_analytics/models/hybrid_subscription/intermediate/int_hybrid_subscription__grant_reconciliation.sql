with subscription_transactions as (
    select *
    from {{ ref('stg_hybrid_subscription__store_transactions') }}
    where product_type = 'subscription'
        and transaction_status = 'succeeded'
),
linked as (
    select
        source_subscription_transaction_id as transaction_id,
        count(*) as linked_grant_count,
        sum(currency_amount) as linked_currency_amount
    from {{ ref('stg_hybrid_subscription__currency_ledger') }}
    where entry_type = 'subscription_grant'
        and source_subscription_transaction_id is not null
    group by source_subscription_transaction_id
),
unlinked_candidates as (
    select
        transaction.player_id,
        transaction.transaction_id,
        count(ledger.ledger_entry_id) as unlinked_candidate_count
    from subscription_transactions transaction
    left join {{ ref('stg_hybrid_subscription__currency_ledger') }} ledger
        on transaction.player_id = ledger.player_id
        and ledger.entry_type = 'subscription_grant'
        and ledger.source_subscription_transaction_id is null
        and abs(date_diff('hour', transaction.transaction_at_utc, ledger.occurred_at_utc)) <= 24
    group by transaction.player_id, transaction.transaction_id
)
select
    transaction.transaction_id,
    transaction.player_id,
    transaction.transaction_at_utc,
    transaction.net_amount_usd as subscription_net_revenue_usd,
    coalesce(linked.linked_grant_count, 0) as linked_grant_count,
    coalesce(linked.linked_currency_amount, 0) as linked_currency_amount,
    candidate.unlinked_candidate_count,
    case
        when coalesce(linked.linked_grant_count, 0) > 0 then 'linked'
        when candidate.unlinked_candidate_count > 0 then 'missing_link'
        else 'no_grant'
    end as grant_link_status,
    coalesce(linked.linked_grant_count, 0) > 0
        or candidate.unlinked_candidate_count > 0 as is_reconciled
from subscription_transactions transaction
left join linked using (transaction_id)
left join unlinked_candidates candidate using (player_id, transaction_id)
