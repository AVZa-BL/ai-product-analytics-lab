{{ config(tags=['live_strategy']) }}

select
    cast(live_event_id as varchar) as live_event_id,
    lower(trim(cast(event_name as varchar))) as event_name,
    cast(starts_at_utc as timestamp) as starts_at_utc,
    cast(ends_at_utc as timestamp) as ends_at_utc,
    lower(trim(cast(season_id as varchar))) as season_id,
    lower(trim(cast(reward_track as varchar))) as reward_track
from {{ source('live_strategy_raw', 'live_events') }}
