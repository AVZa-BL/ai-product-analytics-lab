with invalid as (
    select transaction_id
    from {{ ref('fct_hybrid_subscription__store_transactions') }}
    where product_type = 'reward_track'
      and is_standalone_store_revenue
)
select * from invalid
