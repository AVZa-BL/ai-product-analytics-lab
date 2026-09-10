{{ config(tags=['live_strategy']) }}

with event_days as (
    select
        date_trunc('day', occurred_at_utc)::date as activity_date_utc,
        player_id,
        true as has_gameplay_event
    from {{ ref('int_live_strategy__valid_gameplay_events') }}
    group by 1, 2
),

session_days as (
    select
        date_trunc('day', started_at_utc)::date as activity_date_utc,
        player_id,
        true as has_session_start
    from {{ ref('int_live_strategy__session_quality') }}
    group by 1, 2
)

select
    coalesce(e.activity_date_utc, s.activity_date_utc) as activity_date_utc,
    coalesce(e.player_id, s.player_id) as player_id,
    coalesce(e.has_gameplay_event, false) as has_gameplay_event,
    coalesce(s.has_session_start, false) as has_session_start,
    case
        when e.player_id is not null and s.player_id is not null then 'both'
        when e.player_id is not null then 'gameplay_event'
        else 'session_start'
    end as activity_evidence
from event_days e
full outer join session_days s
    on e.activity_date_utc = s.activity_date_utc
   and e.player_id = s.player_id
