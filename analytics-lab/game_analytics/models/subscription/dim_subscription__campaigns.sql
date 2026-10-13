with campaign_evidence as (
    select campaign_id, acquisition_channel
    from {{ ref('int_subscription__campaign_attribution') }}
    union all
    select coalesce(campaign_id, 'unknown'), channel
    from {{ ref('stg_subscription__marketing_spend') }}
    union all
    select 'unknown', 'unknown'
)

select
    campaign_id,
    case
        when campaign_id = 'unknown' then 'unknown'
        when count(distinct acquisition_channel) = 1 then min(acquisition_channel)
        else 'mixed'
    end as acquisition_channel,
    campaign_id <> 'unknown' as is_tracked_campaign
from campaign_evidence
group by 1
