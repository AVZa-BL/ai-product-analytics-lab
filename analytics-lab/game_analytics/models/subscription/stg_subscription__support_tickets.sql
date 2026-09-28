select
    cast(ticket_id as varchar) as ticket_id,
    cast(user_id as varchar) as user_id,
    cast(created_at as timestamp) as created_at,
    cast(ticket_category as varchar) as ticket_category,
    cast(ticket_status as varchar) as ticket_status
from {{ source('subscription_raw', 'subscription_support_tickets') }}
