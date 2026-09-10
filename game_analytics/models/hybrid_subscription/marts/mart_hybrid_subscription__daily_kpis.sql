with metric_rows as (
    select
        cast(session.started_at_utc as date) as metric_date,
        player.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        1 as session_count,
        session.duration_seconds as session_duration_seconds,
        0 as liveops_participation_count,
        0::decimal(18, 2) as standalone_store_net_revenue_usd,
        0::decimal(18, 2) as subscription_net_revenue_usd,
        0::decimal(18, 2) as discount_amount_usd,
        0 as new_subscription_count,
        0 as eligible_exposure_count,
        0 as rejected_exposure_count,
        0 as subscription_grant_count,
        0 as reconciled_subscription_grant_count
    from {{ ref('fct_hybrid_subscription__sessions') }} session
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)

    union all

    select
        cast(participation.participated_at_utc as date),
        player.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0
    from {{ ref('stg_hybrid_subscription__live_event_participation') }} participation
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)

    union all

    select
        cast(transaction.transaction_at_utc as date),
        transaction.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        0, 0, 0,
        case
            when transaction.is_standalone_store_revenue
                then transaction.recognized_net_revenue_usd
            else 0
        end,
        case
            when transaction.is_subscription_revenue
                then transaction.recognized_net_revenue_usd
            else 0
        end,
        transaction.discount_amount_usd,
        0, 0, 0, 0, 0
    from {{ ref('fct_hybrid_subscription__store_transactions') }} transaction
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)

    union all

    select
        cast(entitlement.entitlement_start_at_utc as date),
        player.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0
    from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} entitlement
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)

    union all

    select
        cast(exposure.exposed_at_utc as date),
        player.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        0, 0, 0, 0, 0, 0, 0,
        case when exposure.is_incrementality_eligible then 1 else 0 end,
        case when exposure.is_incrementality_eligible then 0 else 1 end,
        0, 0
    from {{ ref('fct_hybrid_subscription__marketing_exposures') }} exposure
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)

    union all

    select
        cast(grant.occurred_at_utc as date),
        player.prior_payer_status,
        null::varchar as active_subscriber_player_id,
        0, 0, 0, 0, 0, 0, 0, 0, 0,
        1,
        case when grant.is_reconciled then 1 else 0 end
    from {{ ref('fct_hybrid_subscription__currency_grants') }} grant
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)
    where grant.entry_type = 'subscription_grant'

    union all

    select
        subscriber.metric_date,
        player.prior_payer_status,
        subscriber.player_id,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    from {{ ref('fct_hybrid_subscription__subscriber_daily') }} subscriber
    join {{ ref('dim_hybrid_subscription__players') }} player using (player_id)
),
observation as (
    -- Same governed maximum timestamp used by the analysis population.
    select max(observed_at_utc) as as_of_at_utc
    from (
        select started_at_utc as observed_at_utc from {{ ref('fct_hybrid_subscription__sessions') }}
        union all select transaction_at_utc from {{ ref('fct_hybrid_subscription__store_transactions') }}
        union all select participated_at_utc from {{ ref('stg_hybrid_subscription__live_event_participation') }}
    ) timestamps
),
aggregated as (
    select
        metric_date,
        prior_payer_status,
        count(distinct active_subscriber_player_id) as active_subscriber_count,
        sum(session_count) as session_count,
        sum(session_duration_seconds) as session_duration_seconds,
        sum(liveops_participation_count) as liveops_participation_count,
        sum(standalone_store_net_revenue_usd) as standalone_store_net_revenue_usd,
        sum(subscription_net_revenue_usd) as subscription_net_revenue_usd,
        sum(standalone_store_net_revenue_usd)
            + sum(subscription_net_revenue_usd) as total_net_revenue_usd,
        sum(discount_amount_usd) as discount_amount_usd,
        sum(new_subscription_count) as new_subscription_count,
        sum(eligible_exposure_count) as eligible_exposure_count,
        sum(rejected_exposure_count) as rejected_exposure_count,
        sum(subscription_grant_count) as subscription_grant_count,
        sum(reconciled_subscription_grant_count) as reconciled_subscription_grant_count
    from metric_rows
    cross join observation
    where metric_date <= cast(as_of_at_utc as date)
    group by metric_date, prior_payer_status
)
select
    cast(metric_date as varchar) || '__' || prior_payer_status as daily_kpi_id,
    *,
    reconciled_subscription_grant_count::double
        / nullif(subscription_grant_count, 0) as subscription_grant_reconciliation_rate
from aggregated
