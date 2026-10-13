select
    cast(assignment_id as varchar) as assignment_id,
    cast(experiment_id as varchar) as experiment_id,
    cast(player_id as varchar) as player_id,
    cast(arm as varchar) as arm,
    cast(assigned_at_utc as timestamptz) as assigned_at_utc,
    cast(arm_config_version as integer) as arm_config_version,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'experiment_assignments') }}
