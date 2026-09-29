{{ config(materialized='table') }}

with trial_outcomes as (
    select
        t.subscription_id,
        t.cohort_date,
        u.acquisition_channel,
        u.campaign_id,
        t.plan_id,
        case
            when u.activation_at >= u.signup_at
                and u.activation_at <= t.scheduled_trial_end_at
                then 'activated_before_trial_end'
            else 'not_activated_before_trial_end'
        end as activation_segment,
        coalesce(
            t.paid_start_at >= t.trial_start_at
            and t.paid_start_at <= t.scheduled_trial_end_at + interval '3 days',
            false
        ) as is_paid_conversion,
        exists (
            select 1
            from {{ ref('fct_subscription__payments') }} p
            where p.subscription_id = t.subscription_id
                and p.is_failed
                and p.payment_at >= t.trial_start_at
                and p.payment_at <= t.scheduled_trial_end_at + interval '3 days'
        ) as has_payment_failure,
        t.maturity_cutoff_date
    from {{ ref('int_subscription__trial_cohorts') }} t
    join {{ ref('dim_subscription__users') }} u using (user_id)
    where t.is_mature
)

select
    cohort_date,
    acquisition_channel,
    campaign_id,
    plan_id,
    activation_segment,
    count(*) as eligible_trials,
    count(*) filter (where is_paid_conversion) as paid_conversions,
    count(*) filter (where is_paid_conversion) * 1.0 / nullif(count(*), 0)
        as trial_to_paid_rate,
    count(*) filter (where has_payment_failure) as payment_failure_trials,
    max(maturity_cutoff_date) as maturity_cutoff_date
from trial_outcomes
group by 1, 2, 3, 4, 5
