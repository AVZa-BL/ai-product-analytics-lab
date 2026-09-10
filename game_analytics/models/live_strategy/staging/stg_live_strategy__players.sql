{{ config(tags=['live_strategy']) }}

select
    cast(player_id as varchar) as player_id,
    cast(installed_at_utc as timestamp) as installed_at_utc,
    lower(trim(cast(platform as varchar))) as platform,
    lower(trim(cast(country_code as varchar))) as country_code,
    lower(trim(cast(acquisition_channel as varchar))) as acquisition_channel,
    cast(install_app_version as varchar) as install_app_version
from {{ source('live_strategy_raw', 'players') }}
