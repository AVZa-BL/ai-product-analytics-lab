with modeled_calendar as (
    select max(date_day) as max_modeled_calendar_date
    from {{ ref('dim_dates') }}
),

trial_periods as (
    select
        subscription_id,
        user_id,
        period_start_at as trial_start_at,
        scheduled_trial_end_at,
        paid_start_at,
        plan_id
    from {{ ref('int_subscription__subscription_periods') }}
    where lifecycle_status = 'trial'
)

select
    trial_periods.subscription_id,
    trial_periods.user_id,
    trial_periods.trial_start_at,
    cast(trial_periods.trial_start_at as date) as cohort_date,
    trial_periods.scheduled_trial_end_at,
    trial_periods.paid_start_at,
    trial_periods.plan_id,
    cast(trial_periods.trial_start_at as date) + 21 as maturity_cutoff_date,
    cast(trial_periods.trial_start_at as date) + 21
        <= modeled_calendar.max_modeled_calendar_date as is_mature
from trial_periods
cross join modeled_calendar
