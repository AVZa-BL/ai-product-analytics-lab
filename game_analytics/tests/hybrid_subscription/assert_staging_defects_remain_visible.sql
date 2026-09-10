with checks as (
    select
        'duplicate_store_webhook' as defect,
        count(*) filter (where is_duplicate_webhook) as observed_rows
    from {{ ref('stg_hybrid_subscription__store_transactions') }}

    union all

    select
        'missing_subscription_grant_link' as defect,
        count(*) filter (where has_missing_subscription_link) as observed_rows
    from {{ ref('stg_hybrid_subscription__currency_ledger') }}

    union all

    select
        'post_subscription_exposure' as defect,
        count(*) as observed_rows
    from {{ ref('stg_hybrid_subscription__marketing_exposures') }} exposures
    join {{ ref('stg_hybrid_subscription__subscription_events') }} events
        on exposures.player_id = events.player_id
        and events.event_type = 'started'
        and exposures.exposed_at_utc > events.occurred_at_utc
)

select *
from checks
where observed_rows = 0
