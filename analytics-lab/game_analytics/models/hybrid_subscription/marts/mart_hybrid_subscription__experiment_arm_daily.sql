-- Daily arm totals by assignment date (UTC). Outcome sums cover eligible players only;
-- assigned and excluded counts stay so that a shrinking arm remains visible. The sums
-- allow reaggregation across days; means and rates are NULL on a zero denominator.
select
    population.experiment_id,
    population.arm,
    cast(timezone('UTC', population.assigned_at_utc) as date) as assigned_date_utc,
    count(*) as assigned_players,
    count(*) filter (where population.is_eligible) as eligible_players,
    count(*) filter (where not population.is_eligible) as excluded_players,
    coalesce(sum(outcome.sessions_7d) filter (where population.is_eligible), 0) as sessions_7d_sum,
    count(*) filter (where population.is_eligible and outcome.purchases_7d > 0) as purchasers,
    coalesce(sum(outcome.revenue_usd_7d) filter (where population.is_eligible), 0.0) as revenue_usd_7d_sum,
    sum(outcome.sessions_7d) filter (where population.is_eligible)
        / nullif(count(*) filter (where population.is_eligible), 0) as mean_sessions_7d,
    count(*) filter (where population.is_eligible and outcome.purchases_7d > 0)
        / nullif(count(*) filter (where population.is_eligible), 0) as purchase_rate,
    sum(outcome.revenue_usd_7d) filter (where population.is_eligible)
        / nullif(count(*) filter (where population.is_eligible), 0) as mean_revenue_usd_7d,
    min(population.arm_config_version) as min_arm_config_version,
    max(population.arm_config_version) as max_arm_config_version
from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} population
left join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
group by population.experiment_id, population.arm, cast(timezone('UTC', population.assigned_at_utc) as date)
