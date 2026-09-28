{{ config(tags=['live_strategy']) }}

select
    client_event_id,
    player_id,
    session_id,
    occurred_at_utc,
    event_name,
    app_version,
    live_event_id
from {{ ref('int_live_strategy__event_dedup_audit') }}
where is_valid_event
