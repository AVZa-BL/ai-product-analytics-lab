select
    cast(subscription_event_id as varchar) as subscription_event_id,
    cast(player_id as varchar) as player_id,
    cast(event_type as varchar) as event_type,
    cast(current_period_end_at_utc as timestamptz) as current_period_end_at_utc,
    cast(auto_renew_enabled as boolean) as auto_renew_enabled,
    cast(occurred_at_raw as varchar) as occurred_at_raw,
    cast(occurred_at_local as timestamp) as occurred_at_local,
    cast(occurred_at_timezone as varchar) as occurred_at_timezone,
    timezone(occurred_at_timezone, cast(occurred_at_local as timestamp)) as occurred_at_utc,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'subscription_events') }}
