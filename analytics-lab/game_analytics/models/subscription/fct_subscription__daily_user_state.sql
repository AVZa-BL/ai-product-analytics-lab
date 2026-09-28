{{ config(materialized='table') }}

-- UTC calendar-day state uses half-open [start date, end date) intervals.
-- Collapse entitlement rows before publishing the user/date grain.
with daily_entitlements as (
    select
        p.user_id,
        d.date_day as calendar_date,
        bool_or(p.lifecycle_status = 'trial') as is_trial_active,
        bool_or(p.lifecycle_status = 'paid') as is_paid_active,
        sum(case when p.lifecycle_status = 'paid'
            then p.monthly_recurring_revenue_usd else 0 end)
            as monthly_recurring_revenue_usd
    from {{ ref('int_subscription__subscription_periods') }} p
    join {{ ref('dim_dates') }} d
        on d.date_day >= cast(p.period_start_at as date)
       and d.date_day < cast(p.period_end_at as date)
    group by 1, 2
)

select
    u.user_id,
    d.date_day as calendar_date,
    true as is_signed_up,
    d.date_day <= u.signup_date + 7
        and (u.first_trial_at is null or d.date_day <= cast(u.first_trial_at as date))
        and (u.first_paid_at is null or d.date_day < cast(u.first_paid_at as date))
        as is_trial_eligible,
    coalesce(e.is_trial_active, false) as is_trial_active,
    coalesce(e.is_paid_active, false) as is_paid_active,
    coalesce(
        u.activation_at >= u.signup_at
        and u.activation_at <= u.signup_at + interval '7 days'
        and cast(u.activation_at as date) <= d.date_day,
        false
    ) as is_activated,
    u.campaign_id,
    cast(coalesce(e.monthly_recurring_revenue_usd, 0) as decimal(18, 6))
        as monthly_recurring_revenue_usd
from {{ ref('dim_subscription__users') }} u
join {{ ref('dim_dates') }} d on d.date_day >= u.signup_date
left join daily_entitlements e
    on u.user_id = e.user_id and d.date_day = e.calendar_date
