-- The population must carry each assigned player's own assignment attributes unchanged.
select population.player_id
from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} population
join {{ ref('stg_hybrid_subscription__experiment_assignments') }} assignment using (player_id)
where population.assignment_id is distinct from assignment.assignment_id
    or population.experiment_id is distinct from assignment.experiment_id
    or population.arm is distinct from assignment.arm
    or population.assigned_at_utc is distinct from assignment.assigned_at_utc
    or population.arm_config_version is distinct from assignment.arm_config_version
