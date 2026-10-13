select user_id, calendar_date
from {{ ref('fct_subscription__daily_user_state') }}
group by 1, 2
having count(*) > 1
