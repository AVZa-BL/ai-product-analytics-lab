with lifecycle as (
    select *
    from {{ ref('stg_hybrid_subscription__subscription_events') }}
),
summarized as (
    select
        player_id,
        min(occurred_at_utc) filter (where event_type = 'started') as entitlement_start_at_utc,
        max(current_period_end_at_utc) as contractual_period_end_at_utc,
        min(occurred_at_utc) filter (where event_type = 'canceled') as canceled_at_utc,
        min(occurred_at_utc) filter (where event_type in ('expired', 'revoked')) as terminal_event_at_utc
    from lifecycle
    group by player_id
),
latest_state as (
    select
        player_id,
        event_type as latest_event_type,
        auto_renew_enabled,
        row_number() over (
            partition by player_id
            order by occurred_at_utc desc, ingested_at_utc desc
        ) as event_rank
    from lifecycle
)
select
    'subscription_' || summarized.player_id as subscription_id,
    summarized.player_id,
    summarized.entitlement_start_at_utc,
    case
        when summarized.terminal_event_at_utc is not null
            then least(
                summarized.contractual_period_end_at_utc,
                summarized.terminal_event_at_utc
            )
        else summarized.contractual_period_end_at_utc
    end as entitlement_end_at_utc,
    summarized.contractual_period_end_at_utc,
    summarized.canceled_at_utc,
    summarized.terminal_event_at_utc,
    latest_state.latest_event_type,
    latest_state.auto_renew_enabled,
    summarized.canceled_at_utc is not null
        and summarized.canceled_at_utc < summarized.contractual_period_end_at_utc
        as is_canceled_pending_expiry
from summarized
join latest_state using (player_id)
where latest_state.event_rank = 1
    and summarized.entitlement_start_at_utc is not null
