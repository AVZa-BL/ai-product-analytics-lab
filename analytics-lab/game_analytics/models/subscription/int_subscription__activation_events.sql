select
    user_id,
    min(occurred_at) as activation_at
from {{ ref('stg_subscription__product_events') }}
where is_activation_event
group by 1
