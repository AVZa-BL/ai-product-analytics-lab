{{ config(tags=['live_strategy']) }}

select
    cast(membership_id as varchar) as membership_id,
    cast(player_id as varchar) as player_id,
    cast(alliance_id as varchar) as alliance_id,
    cast(valid_from_utc as timestamp) as valid_from_utc,
    cast(valid_to_utc as timestamp) as valid_to_utc,
    lower(trim(cast(membership_status as varchar))) as membership_status
from {{ source('live_strategy_raw', 'alliance_memberships') }}
