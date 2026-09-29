{{ config(tags=['live_strategy']) }}

select
    cast(alliance_id as varchar) as alliance_id,
    cast(created_at_utc as timestamp) as created_at_utc,
    lower(trim(cast(region as varchar))) as region,
    cast(leader_player_id as varchar) as leader_player_id
from {{ source('live_strategy_raw', 'alliances') }}
