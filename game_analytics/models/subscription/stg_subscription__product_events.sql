with raw_events as (
    select
        cast(product_event_id as varchar) as product_event_id,
        cast(user_id as varchar) as user_id,
        cast(event_name as varchar) as event_name,
        cast(occurred_at as timestamp) as occurred_at,
        cast(ingested_at as timestamp) as ingested_at
    from {{ source('subscription_raw', 'subscription_product_events') }}
),

event_name_map as (
    select
        cast(raw_event_name as varchar) as raw_event_name,
        cast(canonical_event_name as varchar) as canonical_event_name,
        cast(is_activation_event as boolean) as is_activation_event
    from {{ ref('subscription_event_name_map') }}
)

select
    raw_events.product_event_id,
    raw_events.user_id,
    raw_events.event_name,
    coalesce(event_name_map.canonical_event_name, 'unmapped') as canonical_event_name,
    coalesce(event_name_map.is_activation_event, false) as is_activation_event,
    raw_events.occurred_at,
    raw_events.ingested_at
from raw_events
left join event_name_map
    on raw_events.event_name = event_name_map.raw_event_name
