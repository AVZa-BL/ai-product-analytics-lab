{{ config(tags=['live_strategy']) }}

select
    client_event_id as participation_event_id,
    occurred_at_utc::date as participation_date_utc,
    occurred_at_utc,
    player_id,
    session_id,
    live_event_id
from {{ ref('int_live_strategy__valid_gameplay_events') }}
where event_name = 'live_event_joined'
