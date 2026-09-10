select player_id
from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
group by player_id
having count(*) != 2
   or count(distinct analysis_period) != 2
   or not bool_and(is_window_mature)
