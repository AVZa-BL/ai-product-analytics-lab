-- First-touch exposure per assigned player. Repeat exposures are counted, not kept.
-- Purchase timing comes from the experiment's own outcomes table.
with ranked_exposures as (
    select
        *,
        row_number() over (
            partition by player_id order by exposed_at_utc, exposure_id
        ) as exposure_rank,
        count(*) over (partition by player_id) as exposure_count
    from {{ ref('stg_hybrid_subscription__experiment_exposures') }}
),
first_exposures as (
    select * from ranked_exposures where exposure_rank = 1
)
select
    assignment.assignment_id,
    assignment.experiment_id,
    assignment.player_id,
    assignment.arm,
    assignment.assigned_at_utc,
    assignment.arm_config_version,
    first_exposure.exposure_id as first_exposure_id,
    first_exposure.exposed_at_utc as first_exposed_at_utc,
    first_exposure.exposure_surface as first_exposure_surface,
    coalesce(first_exposure.exposure_count, 0) as exposure_count,
    first_exposure.exposure_id is not null as is_exposed,
    outcome.first_purchase_at_utc,
    coalesce(
        first_exposure.exposed_at_utc > outcome.first_purchase_at_utc, false
    ) as is_exposed_after_first_purchase
from {{ ref('stg_hybrid_subscription__experiment_assignments') }} assignment
left join first_exposures first_exposure using (player_id)
left join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
