select client_event_id
from {{ ref('int_live_strategy__valid_gameplay_events') }}
group by 1
having count(*) <> 1

union all

select v.client_event_id
from {{ ref('int_live_strategy__valid_gameplay_events') }} v
inner join {{ ref('dim_live_strategy__players') }} p using (player_id)
where v.occurred_at_utc < p.installed_at_utc
