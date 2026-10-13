with duplicate_daily as (
    select daily_kpi_id as grain_id
    from {{ ref('mart_hybrid_subscription__daily_kpis') }}
    group by daily_kpi_id
    having count(*) != 1
),
duplicate_engagement as (
    select engagement_segment_id as grain_id
    from {{ ref('mart_hybrid_subscription__engagement_lift_inputs') }}
    group by engagement_segment_id
    having count(*) != 1
),
duplicate_cannibalization as (
    select cannibalization_segment_id as grain_id
    from {{ ref('mart_hybrid_subscription__cannibalization_inputs') }}
    group by cannibalization_segment_id
    having count(*) != 1
)
select 'daily' as model_name, grain_id from duplicate_daily
union all
select 'engagement', grain_id from duplicate_engagement
union all
select 'cannibalization', grain_id from duplicate_cannibalization
