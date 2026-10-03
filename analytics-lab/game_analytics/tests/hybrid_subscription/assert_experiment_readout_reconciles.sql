-- Totals against independent recounts, the arm-share identity, bounds, and the containment
-- rule: no difference against control for the control arm or when the SRM check is flagged.
with readout as (
    select * from {{ ref('mart_hybrid_subscription__experiment_readout') }}
)
select 'assigned_total_mismatch' as failure
where (select sum(assigned_players) from readout)
    is distinct from (select count(*) from {{ ref('stg_hybrid_subscription__experiment_assignments') }})

union all

select 'eligible_total_mismatch'
where (select sum(eligible_players) from readout)
    is distinct from (select count(*) from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} where is_eligible)

union all

select 'assigned_share_does_not_sum_to_one'
from readout
group by experiment_id
having abs(sum(assigned_share) - 1) > 1e-9

union all

select 'concentration_out_of_bounds'
from readout
where revenue_top1pct_share < 0 or revenue_top1pct_share > 1

union all

select 'control_has_difference'
from readout
where arm = 'control'
    and (mean_sessions_7d_difference_vs_control is not null
        or purchase_rate_difference_vs_control is not null
        or mean_revenue_usd_7d_difference_vs_control is not null)

union all

select 'flagged_experiment_has_difference'
from readout
where is_srm_flagged
    and (mean_sessions_7d_difference_vs_control is not null
        or purchase_rate_difference_vs_control is not null
        or mean_revenue_usd_7d_difference_vs_control is not null)

union all

select 'unflagged_comparison_missing_difference'
from readout
where not is_srm_flagged and arm != 'control' and eligible_players > 0
    and mean_sessions_7d_difference_vs_control is null

union all

select 'config_change_flag_disagrees_with_assignments'
from readout
join (
    select experiment_id, arm, min(arm_config_version) != max(arm_config_version) as changed
    from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
    group by experiment_id, arm
) assignments using (experiment_id, arm)
where readout.has_config_change != assignments.changed
