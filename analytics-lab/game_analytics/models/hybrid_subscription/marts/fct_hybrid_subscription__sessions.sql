select
    session_id,
    player_id,
    started_at_utc,
    duration_seconds,
    scenario_run_id
from {{ ref('stg_hybrid_subscription__sessions') }}
