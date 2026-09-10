{{ config(tags=['live_strategy']) }}

with ranked_snapshots as (
    select
        snapshot_id,
        player_id,
        snapshot_at_utc,
        snapshot_at_utc::date as progression_date_utc,
        level,
        power,
        upgrade_attempts,
        upgrade_successes,
        row_number() over (
            partition by player_id, snapshot_at_utc::date
            order by snapshot_at_utc desc, snapshot_id desc
        ) as snapshot_recency
    from {{ ref('stg_live_strategy__progression_snapshots') }}
)

select
    snapshot_id,
    progression_date_utc,
    player_id,
    snapshot_at_utc,
    level,
    power,
    upgrade_attempts,
    upgrade_successes
from ranked_snapshots
where snapshot_recency = 1
