select activity_date_utc, player_id
from {{ ref('fct_live_strategy__player_activity_daily') }}
group by 1, 2
having count(*) <> 1
   or max(activity_evidence) not in ('gameplay_event', 'session_start', 'both')
