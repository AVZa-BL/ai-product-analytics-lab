select client_event_id
from {{ ref('int_live_strategy__event_config_attribution') }}
group by 1
having count(*) <> 1
