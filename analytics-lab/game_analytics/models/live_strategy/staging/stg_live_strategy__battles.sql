{{ config(tags=['live_strategy']) }}

select
    cast(battle_id as varchar) as battle_id,
    cast(player_id as varchar) as player_id,
    cast(occurred_at_utc as timestamp) as occurred_at_utc,
    lower(trim(cast(opponent_type as varchar))) as opponent_type,
    lower(trim(cast(outcome as varchar))) as outcome,
    cast(power_delta as bigint) as power_delta
from {{ source('live_strategy_raw', 'battles') }}
