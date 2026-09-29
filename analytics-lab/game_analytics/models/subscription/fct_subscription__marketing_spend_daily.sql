select
    spend_date,
    coalesce(campaign_id, 'unknown') as campaign_id,
    country_code,
    cast(sum(spend_usd) as decimal(18, 2)) as spend_usd
from {{ ref('stg_subscription__marketing_spend') }}
group by 1, 2, 3
