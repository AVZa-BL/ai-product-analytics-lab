select
    cast(player_id as varchar) as player_id,
    cast(country_code as varchar) as country_code,
    cast(platform as varchar) as platform,
    cast(acquisition_channel as varchar) as acquisition_channel,
    cast(prior_payer_status as varchar) as prior_payer_status,
    cast(acquired_at_utc as timestamptz) as acquired_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'players') }}
