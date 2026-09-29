select
    cast(onboarding_event_id as varchar) as onboarding_event_id,
    cast(user_id as varchar) as user_id,
    cast(event_name as varchar) as event_name,
    cast(occurred_at as timestamp) as occurred_at,
    cast(ingested_at as timestamp) as ingested_at
from {{ source('subscription_raw', 'subscription_onboarding_events') }}
