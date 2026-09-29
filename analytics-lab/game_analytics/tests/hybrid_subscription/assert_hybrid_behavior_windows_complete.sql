with eligible_population as (
    select
        player_id,
        index_at_utc,
        eligible_exposure_at_utc,
        observation_start_at_utc,
        observation_end_at_utc
    from {{ ref('int_hybrid_subscription__analysis_population') }}
    where is_population_eligible
),
behavior as (
    select *
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
)
select population.player_id
from eligible_population population
left join behavior
    on population.player_id = behavior.player_id
group by
    population.player_id,
    population.index_at_utc,
    population.eligible_exposure_at_utc,
    population.observation_start_at_utc,
    population.observation_end_at_utc
having count(behavior.player_id) != 2
    or count(*) filter (where behavior.analysis_period = 'pre') != 1
    or count(*) filter (where behavior.analysis_period = 'post') != 1
    or population.index_at_utc is null
    or population.observation_start_at_utc is null
    or population.observation_end_at_utc is null
    or population.index_at_utc - interval '672 hours'
        < population.observation_start_at_utc
    or population.index_at_utc + interval '672 hours'
        > population.observation_end_at_utc
    or count(*) filter (
        where behavior.player_id is not null
          and (
            behavior.index_at_utc is distinct from population.index_at_utc
            or behavior.eligible_exposure_at_utc
                is distinct from population.eligible_exposure_at_utc
            or behavior.is_population_eligible is distinct from true
            or behavior.is_window_mature is distinct from true
            or behavior.period_start_at_utc is null
            or behavior.period_end_at_utc is null
            or (
                behavior.analysis_period = 'pre'
                and (
                    behavior.period_start_at_utc is distinct from
                        population.index_at_utc - interval '672 hours'
                    or behavior.period_end_at_utc
                        is distinct from population.index_at_utc
                )
            )
            or (
                behavior.analysis_period = 'post'
                and (
                    behavior.period_start_at_utc
                        is distinct from population.index_at_utc
                    or behavior.period_end_at_utc is distinct from
                        population.index_at_utc + interval '672 hours'
                )
            )
            or behavior.period_start_at_utc
                < population.observation_start_at_utc
            or behavior.period_end_at_utc
                > population.observation_end_at_utc
          )
    ) > 0
