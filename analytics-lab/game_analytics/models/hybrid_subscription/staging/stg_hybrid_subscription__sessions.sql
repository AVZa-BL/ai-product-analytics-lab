select
    cast(session_id as varchar) as session_id,
    cast(player_id as varchar) as player_id,
    cast(analysis_period as varchar) as analysis_period,
    cast(duration_seconds as integer) as duration_seconds,
    cast(started_at_raw as varchar) as started_at_raw,
    cast(started_at_local as timestamp) as started_at_local,
    cast(started_at_timezone as varchar) as started_at_timezone,
    timezone(started_at_timezone, cast(started_at_local as timestamp)) as started_at_utc,
    cast(started_at_utc as timestamptz) as source_started_at_utc,
    timezone(started_at_timezone, cast(started_at_local as timestamp))
        != cast(started_at_utc as timestamptz) as has_timestamp_mismatch,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'sessions') }}
