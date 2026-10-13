{{ config(tags=['live_strategy']) }}

select
    session_id,
    player_id,
    started_at_utc,
    started_at_utc::date as session_date_utc,
    ended_at_utc,
    case
        when not has_missing_end and not has_invalid_duration
            then duration_seconds
    end as duration_seconds,
    has_missing_end,
    has_invalid_duration,
    not has_missing_end and not has_invalid_duration as is_valid_completed_session,
    app_version,
    platform
from {{ ref('int_live_strategy__session_quality') }}
