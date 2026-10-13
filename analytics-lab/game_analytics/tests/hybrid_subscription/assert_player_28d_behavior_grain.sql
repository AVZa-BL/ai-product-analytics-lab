select player_id, analysis_period
from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
group by player_id, analysis_period
having count(*) != 1
