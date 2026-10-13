-- Grain, totals against independent recounts, outcome coverage and NULL-on-zero-denominator.
with daily as (
    select * from {{ ref('mart_hybrid_subscription__experiment_arm_daily') }}
),
eligible_outcomes as (
    select outcome.*
    from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} population
    join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
    where population.is_eligible
)
select 'duplicate_grain' as failure
from daily
group by experiment_id, arm, assigned_date_utc
having count(*) > 1

union all

select 'assigned_total_mismatch'
where (select sum(assigned_players) from daily)
    is distinct from (select count(*) from {{ ref('stg_hybrid_subscription__experiment_assignments') }})

union all

select 'eligible_total_mismatch'
where (select sum(eligible_players) from daily)
    is distinct from (select count(*) from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} where is_eligible)

union all

select 'sessions_total_mismatch'
where (select sum(sessions_7d_sum) from daily)
    is distinct from (select sum(sessions_7d) from eligible_outcomes)

union all

select 'revenue_total_mismatch'
where abs((select sum(revenue_usd_7d_sum) from daily) - (select sum(revenue_usd_7d) from eligible_outcomes)) > 1e-6

union all

select 'eligible_player_without_outcome'
from {{ ref('int_hybrid_subscription__experiment_eligible_population') }} population
left join {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome using (player_id)
where population.is_eligible and outcome.player_id is null

union all

select 'zero_denominator_not_null'
from daily
where eligible_players = 0
    and (mean_sessions_7d is not null or purchase_rate is not null or mean_revenue_usd_7d is not null)
