with ranked as (
    select
        *,
        count(*) over (
            partition by webhook_id
        ) as source_webhook_duplicate_count,
        row_number() over (
            partition by webhook_id
            order by ingested_at desc, occurred_at desc
        ) as duplicate_rank
    from {{ source('subscription_raw', 'subscription_lifecycle_events') }}
)

select
    cast(webhook_id as varchar) as webhook_id,
    cast(subscription_id as varchar) as subscription_id,
    cast(user_id as varchar) as user_id,
    cast(event_type as varchar) as event_type,
    cast(occurred_at as timestamp) as occurred_at,
    cast(effective_at as timestamp) as effective_at,
    cast(ingested_at as timestamp) as ingested_at,
    cast(trial_end_at_reported_utc as timestamp) as raw_trial_end_at_reported_utc,
    cast(trial_timezone as varchar) as trial_timezone,
    timezone(
        'UTC',
        timezone(
            cast(trial_timezone as varchar),
            cast(trial_end_at_reported_utc as timestamp)
        )
    ) as trial_end_at_utc,
    source_webhook_duplicate_count,
    cast(plan_id as varchar) as plan_id,
    cast(billing_period as varchar) as billing_period
from ranked
where duplicate_rank = 1
