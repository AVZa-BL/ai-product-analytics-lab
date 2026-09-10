with lifecycle_quality as (
    select
        cast(sum(source_webhook_duplicate_count - 1) as bigint) as duplicate_webhook_rows,
        cast(count(*) filter (
            where event_type = 'cancelled'
              and ingested_at > effective_at + interval '1 day'
        ) as bigint) as late_cancellation_rows,
        cast(count(*) filter (
            where event_type = 'trial_started'
              and trial_timezone <> 'UTC'
        ) as bigint) as local_time_trial_end_rows
    from {{ ref('stg_subscription__subscription_events') }}
),

user_quality as (
    select
        cast(count(*) filter (where campaign_id is null) as bigint) as missing_campaign_users
    from {{ ref('stg_subscription__users') }}
),

activation_quality as (
    select
        cast(count(*) filter (
            where canonical_event_name = 'unmapped'
               or (is_activation_event and event_name <> canonical_event_name)
        ) as bigint) as unmapped_activation_events
    from {{ ref('stg_subscription__product_events') }}
)

select
    lifecycle_quality.duplicate_webhook_rows,
    lifecycle_quality.late_cancellation_rows,
    user_quality.missing_campaign_users,
    activation_quality.unmapped_activation_events,
    lifecycle_quality.local_time_trial_end_rows
from lifecycle_quality
cross join user_quality
cross join activation_quality
