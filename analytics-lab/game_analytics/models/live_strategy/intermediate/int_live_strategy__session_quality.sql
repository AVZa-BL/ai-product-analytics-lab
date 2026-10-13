{{ config(tags=['live_strategy']) }}

select
    session_id,
    player_id,
    started_at_utc,
    ended_at_utc,
    case
        when ended_at_utc >= started_at_utc
            then date_diff('second', started_at_utc, ended_at_utc)
    end as duration_seconds,
    ended_at_utc is null as has_missing_end,
    coalesce(ended_at_utc < started_at_utc, false) as has_invalid_duration,
    app_version,
    platform
from {{ ref('stg_live_strategy__sessions') }}
