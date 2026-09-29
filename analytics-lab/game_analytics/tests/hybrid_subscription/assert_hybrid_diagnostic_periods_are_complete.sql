with player_periods as (
    select
        player_id,
        count(*) as period_count,
        count(distinct analysis_period) as distinct_period_count,
        min(date_diff('day', period_start_at_utc, period_end_at_utc))
            as shortest_period_days,
        max(date_diff('day', period_start_at_utc, period_end_at_utc))
            as longest_period_days
    from {{ ref('fct_hybrid_subscription__player_behavior_28d') }}
    group by player_id
)
select *
from player_periods
where period_count != 2
    or distinct_period_count != 2
    or shortest_period_days != 28
    or longest_period_days != 28
