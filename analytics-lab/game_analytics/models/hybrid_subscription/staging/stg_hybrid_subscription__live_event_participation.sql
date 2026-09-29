select
    cast(participation_id as varchar) as participation_id,
    cast(player_id as varchar) as player_id,
    cast(live_event_id as varchar) as live_event_id,
    cast(analysis_period as varchar) as analysis_period,
    cast(score as bigint) as score,
    cast(participated_at_raw as varchar) as participated_at_raw,
    cast(participated_at_local as timestamp) as participated_at_local,
    cast(participated_at_timezone as varchar) as participated_at_timezone,
    timezone(participated_at_timezone, cast(participated_at_local as timestamp)) as participated_at_utc,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'live_event_participation') }}
