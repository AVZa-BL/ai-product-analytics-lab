select player_id, analysis_period, count(*) as row_count
from {{ ref('fct_hybrid_subscription__player_behavior_28d') }}
group by player_id, analysis_period
having count(*) != 1
