with first_trial as (
    select user_id, min(trial_start_at) as first_trial_at
    from {{ ref('int_subscription__trial_cohorts') }}
    group by 1
),

first_paid as (
    select user_id, min(paid_start_at) as first_paid_at
    from {{ ref('int_subscription__paid_cohorts') }}
    group by 1
)

select
    u.user_id,
    u.signup_at,
    cast(u.signup_at as date) as signup_date,
    u.country_code,
    u.platform,
    a.campaign_id,
    a.acquisition_channel,
    a.attribution_status,
    t.first_trial_at,
    p.first_paid_at,
    e.activation_at
from {{ ref('stg_subscription__users') }} u
join {{ ref('int_subscription__campaign_attribution') }} a using (user_id)
left join first_trial t using (user_id)
left join first_paid p using (user_id)
left join {{ ref('int_subscription__activation_events') }} e using (user_id)
