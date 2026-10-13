{{ config(tags=['live_strategy']) }}

with ranked_arrivals as (
    select
        e.ingestion_event_id,
        e.client_event_id,
        e.player_id,
        e.session_id,
        e.occurred_at_utc,
        e.event_name,
        e.app_version,
        e.platform,
        e.live_event_id,
        p.installed_at_utc,
        row_number() over (
            partition by e.client_event_id
            order by e.ingestion_event_id
        ) as arrival_row_number
    from {{ ref('stg_live_strategy__gameplay_events') }} e
    left join {{ ref('stg_live_strategy__players') }} p
        on e.player_id = p.player_id
),

audited as (
    select
        *,
        arrival_row_number > 1 as is_duplicate_arrival,
        installed_at_utc is null as has_missing_player,
        occurred_at_utc < installed_at_utc as is_before_install
    from ranked_arrivals
)

select
    *,
    not is_duplicate_arrival
        and not has_missing_player
        and not is_before_install as is_valid_event,
    sum(case when is_duplicate_arrival then 1 else 0 end) over ()
        as rejected_duplicate_arrival_count,
    sum(case when is_before_install then 1 else 0 end) over ()
        as rejected_preinstall_event_count
from audited
