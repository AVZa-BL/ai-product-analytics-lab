{{ config(tags=['live_strategy']) }}

select
    cast(config_version_id as varchar) as config_version_id,
    cast(effective_from_utc as timestamp) as effective_from_utc,
    cast(effective_to_utc as timestamp) as effective_to_utc,
    lower(trim(cast(season_id as varchar))) as season_id,
    cast(upgrade_cost_multiplier as decimal(18, 4)) as upgrade_cost_multiplier,
    cast(event_reward_multiplier as decimal(18, 4)) as event_reward_multiplier
from {{ source('live_strategy_raw', 'config_versions') }}
