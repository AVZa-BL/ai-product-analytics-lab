with lifecycle_rollup as (
    select
        subscription_id,
        any_value(user_id) as user_id,
        min(effective_at) filter (where event_type = 'trial_started') as trial_start_at,
        min(trial_end_at_utc) filter (where event_type = 'trial_started') as scheduled_trial_end_at,
        min(effective_at) filter (where event_type = 'paid_started') as paid_start_at,
        min(effective_at) filter (where event_type = 'cancelled') as cancellation_effective_at,
        min(effective_at) filter (where event_type = 'expired') as expired_at,
        coalesce(
            min(plan_id) filter (where event_type = 'paid_started'),
            min(plan_id) filter (where event_type = 'trial_started')
        ) as plan_id,
        coalesce(
            min(billing_period) filter (where event_type = 'paid_started'),
            min(billing_period) filter (where event_type = 'trial_started')
        ) as billing_period
    from {{ ref('stg_subscription__subscription_events') }}
    group by 1
),

trial_periods as (
    select
        subscription_id,
        user_id,
        trial_start_at as period_start_at,
        coalesce(paid_start_at, scheduled_trial_end_at) as period_end_at,
        scheduled_trial_end_at,
        paid_start_at,
        cancellation_effective_at,
        true as auto_renew_enabled,
        'trial' as lifecycle_status,
        plan_id,
        cast(0 as decimal(18, 6)) as monthly_recurring_revenue_usd
    from lifecycle_rollup
    where trial_start_at is not null
),

paid_periods as (
    select
        subscription_id,
        user_id,
        paid_start_at as period_start_at,
        coalesce(
            expired_at,
            case
                when billing_period = 'annual' then paid_start_at + interval '1 year'
                else paid_start_at + interval '1 month'
            end
        ) as period_end_at,
        scheduled_trial_end_at,
        paid_start_at,
        cancellation_effective_at,
        cancellation_effective_at is null as auto_renew_enabled,
        'paid' as lifecycle_status,
        plan_id,
        cast(
            case
                when billing_period = 'annual' then 79.99 / 12
                else 9.99
            end as decimal(18, 6)
        ) as monthly_recurring_revenue_usd
    from lifecycle_rollup
    where paid_start_at is not null
)

select * from trial_periods
union all
select * from paid_periods
