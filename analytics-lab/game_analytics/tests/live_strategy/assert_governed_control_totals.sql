select 'player_total' as control_name
where (
    select count(*) from {{ ref('dim_live_strategy__players') }}
) <> (
    select count(*) from {{ ref('stg_live_strategy__players') }}
)

union all

select 'purchase_total'
where (
    select count(*) from {{ ref('fct_live_strategy__purchases') }}
) <> (
    select count(*) from {{ ref('int_live_strategy__purchase_reconciliation') }}
)

union all

select 'refunded_purchase_total'
where (
    select count(*)
    from {{ ref('fct_live_strategy__purchases') }}
    where final_purchase_status = 'refunded'
) <> (
    select count(*)
    from {{ ref('int_live_strategy__purchase_reconciliation') }}
    where final_purchase_status = 'refunded'
)
