-- Sample-ratio check of assigned players against an equal split across the three arms.
-- With three arms the chi-square has 2 degrees of freedom, whose survival function is
-- exp(-x / 2), so no statistics library is needed. The equal split is an assumption:
-- the warehouse holds no pre-registered allocation. Flagged at p < 0.001.
with arm_spine as (
    select * from (values ('control'), ('variant_b'), ('variant_c')) as spine(arm)
),
observed as (
    select
        experiment.experiment_id,
        arm_spine.arm,
        count(assignment.assignment_id) as assigned_players
    from (
        select distinct experiment_id
        from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
    ) experiment
    cross join arm_spine
    left join {{ ref('stg_hybrid_subscription__experiment_assignments') }} assignment
        on assignment.experiment_id = experiment.experiment_id
        and assignment.arm = arm_spine.arm
    group by experiment.experiment_id, arm_spine.arm
),
with_expected as (
    select
        *,
        cast(sum(assigned_players) over (partition by experiment_id) as double)
            / count(*) over (partition by experiment_id) as expected_players
    from observed
),
statistics as (
    select
        experiment_id,
        cast(sum(assigned_players) as integer) as assigned_players,
        cast(count(*) as integer) as arm_count,
        sum(power(assigned_players - expected_players, 2) / expected_players) as chi_square
    from with_expected
    group by experiment_id
)
select
    *,
    exp(-chi_square / 2) as p_value,
    exp(-chi_square / 2) < 0.001 as is_srm_flagged
from statistics
