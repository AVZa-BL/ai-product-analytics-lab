{{ config(materialized='table') }}

with calendar as (
    select date_day as metric_date, max(date_day) over () as max_calendar_date
    from {{ ref('dim_dates') }}
),

signup_cohorts as (
    select
        signup_date,
        count(*) as signups,
        count(*) filter (
            where first_trial_at >= signup_at
                and first_trial_at <= signup_at + interval '7 days'
        ) as trial_starts_within_7d,
        count(*) filter (
            where activation_at >= signup_at
                and activation_at <= signup_at + interval '7 days'
        ) as activations_within_7d,
        count(*) filter (where campaign_id = 'unknown') as unknown_campaign_signups
    from {{ ref('dim_subscription__users') }}
    group by 1
),

trial_cohorts as (
    select
        t.cohort_date,
        count(*) as trial_starts,
        count(*) filter (where t.is_mature) as mature_trials,
        count(*) filter (
            where t.is_mature and u.activation_at >= u.signup_at
                and u.activation_at <= t.scheduled_trial_end_at
        ) as activated_trials,
        count(*) filter (
            where t.is_mature and t.paid_start_at >= t.trial_start_at
                and t.paid_start_at <= t.scheduled_trial_end_at + interval '3 days'
        ) as paid_conversions
    from {{ ref('int_subscription__trial_cohorts') }} t
    join {{ ref('dim_subscription__users') }} u using (user_id)
    group by 1
),

first_paid as (
    select *
    from {{ ref('int_subscription__paid_cohorts') }}
    qualify row_number() over (
        partition by user_id order by paid_start_at, subscription_id
    ) = 1
),

paid_cohorts as (
    select
        p.cohort_date,
        count(*) as new_paid_users,
        count(*) filter (where u.campaign_id <> 'unknown') as attributed_new_paid_users,
        count(*) filter (where s.is_paid_active) as retained_paid_users_d30,
        count(*) filter (where exists (
            select 1
            from {{ ref('int_subscription__subscription_periods') }} e
            where e.subscription_id = p.subscription_id
                and e.cancellation_effective_at >= p.paid_start_at
                and e.cancellation_effective_at <= p.paid_start_at + interval '30 days'
        )) as early_paid_churn_users
    from first_paid p
    join {{ ref('dim_subscription__users') }} u using (user_id)
    left join {{ ref('fct_subscription__daily_user_state') }} s
        on p.user_id = s.user_id and s.calendar_date = p.cohort_date + 30
    group by 1
),

daily_state as (
    select
        calendar_date,
        count(*) filter (where is_paid_active) as paid_active_users,
        sum(case when is_paid_active then monthly_recurring_revenue_usd else 0 end) as mrr_usd
    from {{ ref('fct_subscription__daily_user_state') }}
    group by 1
),

month_start_cohorts as (
    select calendar_date as month_start_date, user_id, monthly_recurring_revenue_usd
    from {{ ref('fct_subscription__daily_user_state') }}
    where calendar_date = cast(date_trunc('month', calendar_date) as date)
        and is_paid_active and monthly_recurring_revenue_usd > 0
),

net_revenue_retention as (
    select
        c.metric_date,
        sum(m.monthly_recurring_revenue_usd) as nrr_starting_mrr_usd,
        sum(case when s.is_paid_active then s.monthly_recurring_revenue_usd else 0 end)
            as nrr_current_cohort_mrr_usd
    from calendar c
    join month_start_cohorts m
        on m.month_start_date = cast(date_trunc('month', c.metric_date) as date)
    left join {{ ref('fct_subscription__daily_user_state') }} s
        on m.user_id = s.user_id and c.metric_date = s.calendar_date
    group by 1
),

spend as (
    select spend_date, sum(spend_usd) as tracked_campaign_spend_usd
    from {{ ref('fct_subscription__marketing_spend_daily') }}
    where campaign_id <> 'unknown'
    group by 1
),

revenue as (
    select payment_date, sum(recognized_gross_revenue_usd) as recognized_gross_revenue_usd
    from {{ ref('fct_subscription__payments') }}
    group by 1
),

governed_counts as (
    select
        c.metric_date,
        c.max_calendar_date as observation_end_date,
        coalesce(s.signups, 0) as signups,
        case when c.metric_date + 7 <= c.max_calendar_date
            then coalesce(s.trial_starts_within_7d, 0) end as signup_to_trial_numerator,
        case when c.metric_date + 7 <= c.max_calendar_date
            then coalesce(s.signups, 0) end as signup_to_trial_denominator,
        case when c.metric_date + 7 <= c.max_calendar_date
            then coalesce(s.activations_within_7d, 0) end as activation_numerator,
        case when c.metric_date + 7 <= c.max_calendar_date
            then coalesce(s.signups, 0) end as activation_denominator,
        coalesce(t.trial_starts, 0) as trial_starts,
        case when c.metric_date + 21 <= c.max_calendar_date
            then coalesce(t.activated_trials, 0) end as trial_activation_numerator,
        case when c.metric_date + 21 <= c.max_calendar_date
            then coalesce(t.mature_trials, 0) end as trial_activation_denominator,
        case when c.metric_date + 21 <= c.max_calendar_date
            then coalesce(t.paid_conversions, 0) end as trial_to_paid_numerator,
        case when c.metric_date + 21 <= c.max_calendar_date
            then coalesce(t.mature_trials, 0) end as trial_to_paid_denominator,
        coalesce(p.new_paid_users, 0) as new_paid_users,
        coalesce(r.retained_paid_users_d30, 0) as d30_paid_retention_numerator,
        coalesce(r.new_paid_users, 0) as d30_paid_retention_denominator,
        case when c.metric_date + 30 <= c.max_calendar_date
            then coalesce(p.early_paid_churn_users, 0) end as early_paid_churn_numerator,
        case when c.metric_date + 30 <= c.max_calendar_date
            then coalesce(p.new_paid_users, 0) end as early_paid_churn_denominator,
        coalesce(ds.paid_active_users, 0) as paid_active_users,
        coalesce(ds.mrr_usd, 0) as mrr_usd,
        coalesce(n.nrr_current_cohort_mrr_usd, 0) as nrr_numerator_usd,
        coalesce(n.nrr_starting_mrr_usd, 0) as nrr_denominator_usd,
        coalesce(sp.tracked_campaign_spend_usd, 0) as cac_numerator_usd,
        coalesce(p.attributed_new_paid_users, 0) as cac_denominator,
        coalesce(rv.recognized_gross_revenue_usd, 0) as recognized_gross_revenue_usd,
        coalesce(s.unknown_campaign_signups, 0) as unknown_campaign_numerator,
        coalesce(s.signups, 0) as unknown_campaign_denominator,
        case when coalesce(q.duplicate_webhook_rows, 0) > 0
            or coalesce(q.late_cancellation_rows, 0) > 0
            or coalesce(q.missing_campaign_users, 0) > 0
            or coalesce(q.unmapped_activation_events, 0) > 0
            or coalesce(q.local_time_trial_end_rows, 0) > 0
            then 'review_required' else 'passed' end as data_quality_status
    from calendar c
    left join signup_cohorts s on c.metric_date = s.signup_date
    left join trial_cohorts t on c.metric_date = t.cohort_date
    left join paid_cohorts p on c.metric_date = p.cohort_date
    left join paid_cohorts r on c.metric_date = r.cohort_date + 30
    left join daily_state ds on c.metric_date = ds.calendar_date
    left join net_revenue_retention n on c.metric_date = n.metric_date
    left join spend sp on c.metric_date = sp.spend_date
    left join revenue rv on c.metric_date = rv.payment_date
    -- Task 3 exposes a one-row scenario audit, not date-specific incident counts.
    cross join {{ ref('int_subscription__quality_audit') }} q
)

select
    *,
    signup_to_trial_numerator * 1.0 / nullif(signup_to_trial_denominator, 0)
        as signup_to_trial_rate,
    activation_numerator * 1.0 / nullif(activation_denominator, 0) as activation_rate,
    trial_activation_numerator * 1.0 / nullif(trial_activation_denominator, 0)
        as trial_activation_rate,
    trial_to_paid_numerator * 1.0 / nullif(trial_to_paid_denominator, 0) as trial_to_paid_rate,
    d30_paid_retention_numerator * 1.0 / nullif(d30_paid_retention_denominator, 0)
        as d30_paid_retention_rate,
    early_paid_churn_numerator * 1.0 / nullif(early_paid_churn_denominator, 0)
        as early_paid_churn_rate,
    nrr_numerator_usd * 1.0 / nullif(nrr_denominator_usd, 0) as nrr,
    cac_numerator_usd * 1.0 / nullif(cac_denominator, 0) as cac_usd,
    unknown_campaign_numerator * 1.0 / nullif(unknown_campaign_denominator, 0)
        as unknown_campaign_share
from governed_counts
