select
    cast(spend_id as varchar) as spend_id,
    cast(spend_date as date) as spend_date,
    cast(campaign_id as varchar) as campaign_id,
    cast(channel as varchar) as channel,
    cast(country_code as varchar) as country_code,
    cast(spend_usd as decimal(18, 2)) as spend_usd
from {{ source('subscription_raw', 'subscription_marketing_spend') }}
