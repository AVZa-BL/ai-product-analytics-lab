select
    cast(user_id as varchar) as user_id,
    cast(signup_at as timestamp) as signup_at,
    cast(country_code as varchar) as country_code,
    cast(platform as varchar) as platform,
    cast(campaign_id as varchar) as campaign_id,
    cast(acquisition_channel as varchar) as acquisition_channel
from {{ source('subscription_raw', 'subscription_users') }}
