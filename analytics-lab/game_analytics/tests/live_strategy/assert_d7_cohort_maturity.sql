select
    install_date_utc,
    platform,
    country_code,
    acquisition_channel,
    config_version_id
from {{ ref('mart_live_strategy__retention_cohorts') }}
where eligible_d7_players > 0
  and install_date_utc > (
      select max(activity_date_utc) - 7
      from {{ ref('fct_live_strategy__player_activity_daily') }}
  )
