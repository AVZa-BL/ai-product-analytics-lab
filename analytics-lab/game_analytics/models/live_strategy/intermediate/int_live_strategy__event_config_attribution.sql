{{ config(tags=['live_strategy']) }}

select
    e.client_event_id,
    e.player_id,
    e.session_id,
    e.occurred_at_utc,
    e.event_name,
    e.app_version,
    e.live_event_id,
    c.config_version_id,
    c.season_id,
    c.upgrade_cost_multiplier,
    c.event_reward_multiplier
from {{ ref('int_live_strategy__valid_gameplay_events') }} e
left join {{ ref('stg_live_strategy__config_versions') }} c
    on e.occurred_at_utc >= c.effective_from_utc
   and e.occurred_at_utc < coalesce(
       c.effective_to_utc,
       timestamp '9999-12-31 00:00:00'
   )
