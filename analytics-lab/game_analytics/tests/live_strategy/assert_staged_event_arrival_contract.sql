select ingestion_event_id
from {{ ref('stg_live_strategy__gameplay_events') }}
group by 1
having count(*) <> 1

union all

select ingestion_event_id
from {{ ref('stg_live_strategy__gameplay_events') }}
where occurred_at_utc is null
   or client_event_id is null
   or player_id is null
