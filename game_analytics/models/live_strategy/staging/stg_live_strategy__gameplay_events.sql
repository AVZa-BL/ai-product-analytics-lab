{{ config(tags=['live_strategy']) }}

select
    cast(ingestion_event_id as varchar) as ingestion_event_id,
    cast(client_event_id as varchar) as client_event_id,
    cast(player_id as varchar) as player_id,
    cast(session_id as varchar) as session_id,
    cast(occurred_at_utc as timestamp) as occurred_at_utc,
    lower(trim(cast(event_name as varchar))) as event_name,
    cast(app_version as varchar) as app_version,
    lower(trim(cast(platform as varchar))) as platform,
    cast(live_event_id as varchar) as live_event_id
from {{ source('live_strategy_raw', 'gameplay_events') }}
