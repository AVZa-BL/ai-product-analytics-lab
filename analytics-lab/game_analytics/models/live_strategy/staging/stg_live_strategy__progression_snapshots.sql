{{ config(tags=['live_strategy']) }}

select
    cast(snapshot_id as varchar) as snapshot_id,
    cast(player_id as varchar) as player_id,
    cast(snapshot_at_utc as timestamp) as snapshot_at_utc,
    cast(level as bigint) as level,
    cast(power as bigint) as power,
    cast(upgrade_attempts as bigint) as upgrade_attempts,
    cast(upgrade_successes as bigint) as upgrade_successes
from {{ source('live_strategy_raw', 'progression_snapshots') }}
