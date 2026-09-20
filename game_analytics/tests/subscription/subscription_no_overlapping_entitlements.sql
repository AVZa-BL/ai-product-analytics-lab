with ordered as (
    select
        subscription_id,
        period_start_at,
        period_end_at,
        lag(period_end_at) over (
            partition by subscription_id order by period_start_at
        ) as prior_end_at
    from {{ ref('int_subscription__subscription_periods') }}
)

select *
from ordered
where prior_end_at > period_start_at
