select
    cast(experiment_id as varchar) as experiment_id,
    cast(player_id as varchar) as player_id,
    cast(window_start_utc as timestamptz) as window_start_utc,
    cast(window_end_utc as timestamptz) as window_end_utc,
    cast(sessions_7d as integer) as sessions_7d,
    cast(purchases_7d as integer) as purchases_7d,
    cast(revenue_usd_7d as double) as revenue_usd_7d,
    cast(first_purchase_at_utc as timestamptz) as first_purchase_at_utc,
    cast(scenario_run_id as varchar) as scenario_run_id
from {{ source('hybrid_subscription_raw', 'experiment_outcomes') }}
