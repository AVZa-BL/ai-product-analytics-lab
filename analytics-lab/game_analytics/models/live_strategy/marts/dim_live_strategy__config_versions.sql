{{ config(tags=['live_strategy']) }}

select
    config_version_id,
    effective_from_utc,
    effective_to_utc,
    season_id,
    upgrade_cost_multiplier,
    event_reward_multiplier
from {{ ref('stg_live_strategy__config_versions') }}
