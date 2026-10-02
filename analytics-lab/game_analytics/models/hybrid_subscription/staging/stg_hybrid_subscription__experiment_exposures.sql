select
    cast(exposure_id as varchar) as exposure_id,
    cast(experiment_id as varchar) as experiment_id,
    cast(player_id as varchar) as player_id,
    cast(arm as varchar) as arm,
    cast(exposed_at_utc as timestamptz) as exposed_at_utc,
    cast(arm_config_version as integer) as arm_config_version,
    cast(exposure_surface as varchar) as exposure_surface,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'experiment_exposures') }}
