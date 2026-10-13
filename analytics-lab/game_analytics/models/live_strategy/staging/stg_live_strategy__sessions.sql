{{ config(tags=['live_strategy']) }}

select
    cast(session_id as varchar) as session_id,
    cast(player_id as varchar) as player_id,
    cast(started_at_utc as timestamp) as started_at_utc,
    cast(ended_at_utc as timestamp) as ended_at_utc,
    cast(app_version as varchar) as app_version,
    lower(trim(cast(platform as varchar))) as platform
from {{ source('live_strategy_raw', 'sessions') }}
