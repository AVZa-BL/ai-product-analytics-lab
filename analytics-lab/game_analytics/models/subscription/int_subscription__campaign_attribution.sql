select
    user_id,
    coalesce(campaign_id, 'unknown') as campaign_id,
    acquisition_channel,
    case
        when campaign_id is null then 'missing_campaign'
        else 'attributed'
    end as attribution_status
from {{ ref('stg_subscription__users') }}
