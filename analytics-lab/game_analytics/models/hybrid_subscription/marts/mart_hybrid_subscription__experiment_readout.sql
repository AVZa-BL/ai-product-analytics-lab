-- One row per experiment and arm. Descriptive only: differences against control are point
-- differences with no uncertainty, and they are NULL for the control arm and for every arm
-- of an experiment whose sample-ratio check is flagged, because an arm comparison is not
-- valid then. Outcome figures cover eligible players only. The top 1% is the ceiling of
-- 1% of an arm's eligible players, computed in integers so it cannot be moved by rounding.
with arm_totals as (
    select
        experiment_id,
        arm,
        sum(assigned_players) as assigned_players,
        sum(eligible_players) as eligible_players,
        sum(excluded_players) as excluded_players,
        sum(sessions_7d_sum) as sessions_7d_sum,
        sum(purchasers) as purchasers,
        sum(revenue_usd_7d_sum) as revenue_usd_7d_sum,
        min(min_arm_config_version) as min_arm_config_version,
        max(max_arm_config_version) as max_arm_config_version
    from {{ ref('mart_hybrid_subscription__experiment_arm_daily') }}
    group by experiment_id, arm
),
ranked_revenue as (
    select
        population.experiment_id,
        population.arm,
        outcome.revenue_usd_7d,
        row_number() over (
            partition by population.experiment_id, population.arm
            order by outcome.revenue_usd_7d desc, population.player_id
        ) as revenue_rank,
        count(*) over (partition by population.experiment_id, population.arm) as arm_eligible_players
    from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} population
    join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
    where population.is_eligible
),
concentration as (
    select
        experiment_id,
        arm,
        sum(revenue_usd_7d) filter (where revenue_rank <= (arm_eligible_players + 99) // 100)
            / nullif(sum(revenue_usd_7d), 0) as revenue_top1pct_share
    from ranked_revenue
    group by experiment_id, arm
),
arm_rates as (
    select
        *,
        assigned_players / sum(assigned_players) over (partition by experiment_id) as assigned_share,
        min_arm_config_version != max_arm_config_version as has_config_change,
        sessions_7d_sum / nullif(eligible_players, 0) as mean_sessions_7d,
        purchasers / nullif(eligible_players, 0) as purchase_rate,
        revenue_usd_7d_sum / nullif(eligible_players, 0) as mean_revenue_usd_7d
    from arm_totals
)
select
    arm_rates.experiment_id,
    arm_rates.arm,
    arm_rates.assigned_players,
    arm_rates.assigned_share,
    arm_rates.eligible_players,
    arm_rates.excluded_players,
    srm.chi_square as experiment_srm_chi_square,
    srm.p_value as experiment_srm_p_value,
    srm.is_srm_flagged,
    arm_rates.has_config_change,
    arm_rates.mean_sessions_7d,
    arm_rates.purchase_rate,
    arm_rates.mean_revenue_usd_7d,
    concentration.revenue_top1pct_share,
    case when arm_rates.arm = 'control' or srm.is_srm_flagged then null
        else arm_rates.mean_sessions_7d
            - max(arm_rates.mean_sessions_7d) filter (where arm_rates.arm = 'control')
                over (partition by arm_rates.experiment_id)
    end as mean_sessions_7d_difference_vs_control,
    case when arm_rates.arm = 'control' or srm.is_srm_flagged then null
        else arm_rates.purchase_rate
            - max(arm_rates.purchase_rate) filter (where arm_rates.arm = 'control')
                over (partition by arm_rates.experiment_id)
    end as purchase_rate_difference_vs_control,
    case when arm_rates.arm = 'control' or srm.is_srm_flagged then null
        else arm_rates.mean_revenue_usd_7d
            - max(arm_rates.mean_revenue_usd_7d) filter (where arm_rates.arm = 'control')
                over (partition by arm_rates.experiment_id)
    end as mean_revenue_usd_7d_difference_vs_control
from arm_rates
join {{ ref('int_hybrid_subscription__experiment_srm') }} srm using (experiment_id)
left join concentration using (experiment_id, arm)
