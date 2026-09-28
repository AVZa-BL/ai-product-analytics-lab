select
    cast(exposure_id as varchar) as exposure_id,
    cast(player_id as varchar) as player_id,
    cast(campaign_id as varchar) as campaign_id,
    cast(experiment_arm as varchar) as experiment_arm,
    cast(channel as varchar) as channel,
    cast(exposed_at_raw as varchar) as exposed_at_raw,
    cast(exposed_at_local as timestamp) as exposed_at_local,
    cast(exposed_at_timezone as varchar) as exposed_at_timezone,
    timezone(exposed_at_timezone, cast(exposed_at_local as timestamp)) as exposed_at_utc,
    cast(ingested_at_utc as timestamptz) as ingested_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'marketing_exposures') }}
