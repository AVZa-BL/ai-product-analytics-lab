{{ config(tags=['live_strategy']) }}

select
    player_id,
    installed_at_utc,
    installed_at_utc::date as install_date_utc,
    platform,
    country_code,
    acquisition_channel,
    install_app_version
from {{ ref('stg_live_strategy__players') }}
