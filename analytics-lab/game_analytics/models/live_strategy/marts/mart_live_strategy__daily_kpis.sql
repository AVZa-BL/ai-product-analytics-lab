{{ config(tags=['live_strategy']) }}

with activity as (
    select
        a.activity_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        count(*) as dau
    from {{ ref('fct_live_strategy__player_activity_daily') }} a
    inner join {{ ref('dim_live_strategy__players') }} p
        on a.player_id = p.player_id
    group by 1, 2, 3, 4
),

installs as (
    select
        install_date_utc as activity_date_utc,
        platform,
        country_code,
        acquisition_channel,
        count(*) as new_installs
    from {{ ref('dim_live_strategy__players') }}
    group by 1, 2, 3, 4
),

retention as (
    select
        install_date_utc as activity_date_utc,
        platform,
        country_code,
        acquisition_channel,
        sum(eligible_d1_players) as eligible_d1_players,
        sum(retained_d1_players) as retained_d1_players,
        sum(eligible_d7_players) as eligible_d7_players,
        sum(retained_d7_players) as retained_d7_players
    from {{ ref('mart_live_strategy__retention_cohorts') }}
    group by 1, 2, 3, 4
),

sessions as (
    select
        s.session_date_utc as activity_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        count(*) as session_count,
        count(*) filter (where s.is_valid_completed_session) as qualifying_session_count,
        median(s.duration_seconds) filter (
            where s.is_valid_completed_session
        ) as median_session_duration_seconds
    from {{ ref('fct_live_strategy__sessions') }} s
    inner join {{ ref('dim_live_strategy__players') }} p using (player_id)
    group by 1, 2, 3, 4
),

purchase_by_player as (
    select
        purchase_date_utc as activity_date_utc,
        platform,
        country_code,
        acquisition_channel,
        player_id,
        sum(gross_usd) filter (
            where final_purchase_status in ('completed', 'refunded')
        ) as gross_revenue_usd,
        sum(refund_usd) as refunds_usd,
        sum(net_usd) as net_revenue_usd
    from {{ ref('fct_live_strategy__purchases') }}
    group by 1, 2, 3, 4, 5
),

revenue as (
    select
        r.activity_date_utc,
        r.platform,
        r.country_code,
        r.acquisition_channel,
        count(*) filter (
            where r.net_revenue_usd > 0 and a.player_id is not null
        ) as payers,
        sum(r.gross_revenue_usd) as gross_revenue_usd,
        sum(r.refunds_usd) as refunds_usd,
        sum(r.net_revenue_usd) as net_revenue_usd
    from purchase_by_player r
    left join {{ ref('fct_live_strategy__player_activity_daily') }} a
        on r.player_id = a.player_id
       and r.activity_date_utc = a.activity_date_utc
    group by 1, 2, 3, 4
),

event_participation as (
    select
        e.participation_date_utc as activity_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        count(distinct e.player_id) as event_participants
    from {{ ref('fct_live_strategy__live_event_participation') }} e
    inner join {{ ref('dim_live_strategy__players') }} p using (player_id)
    group by 1, 2, 3, 4
),

alliance_membership as (
    select
        a.membership_date_utc as activity_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        count(distinct a.player_id) as alliance_members
    from {{ ref('fct_live_strategy__alliance_membership_daily') }} a
    inner join {{ ref('fct_live_strategy__player_activity_daily') }} d
        on a.player_id = d.player_id
       and a.membership_date_utc = d.activity_date_utc
    inner join {{ ref('dim_live_strategy__players') }} p
        on a.player_id = p.player_id
    group by 1, 2, 3, 4
),

progression_changes as (
    select
        progression_date_utc as activity_date_utc,
        player_id,
        level,
        snapshot_at_utc,
        lag(level) over (partition by player_id order by snapshot_at_utc) as previous_level,
        lag(snapshot_at_utc) over (
            partition by player_id order by snapshot_at_utc
        ) as previous_snapshot_at_utc
    from {{ ref('fct_live_strategy__progression_daily') }}
),

progression as (
    select
        c.activity_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        avg(
            (c.level - c.previous_level)::decimal(18, 6)
            / nullif(
                date_diff('day', c.previous_snapshot_at_utc, c.snapshot_at_utc),
                0
            )
        ) as progression_velocity
    from progression_changes c
    inner join {{ ref('dim_live_strategy__players') }} p using (player_id)
    where c.previous_snapshot_at_utc is not null
    group by 1, 2, 3, 4
),

grain as (
    select activity_date_utc, platform, country_code, acquisition_channel from activity
    union
    select activity_date_utc, platform, country_code, acquisition_channel from installs
    union
    select activity_date_utc, platform, country_code, acquisition_channel from revenue
)

select
    g.activity_date_utc,
    g.platform,
    g.country_code,
    g.acquisition_channel,
    coalesce(i.new_installs, 0) as new_installs,
    coalesce(a.dau, 0) as dau,
    coalesce(r.eligible_d1_players, 0) as eligible_d1_players,
    coalesce(r.retained_d1_players, 0) as retained_d1_players,
    coalesce(r.eligible_d7_players, 0) as eligible_d7_players,
    coalesce(r.retained_d7_players, 0) as retained_d7_players,
    coalesce(r.retained_d1_players, 0)::decimal(18, 6)
        / nullif(r.eligible_d1_players, 0) as d1_retention,
    coalesce(r.retained_d7_players, 0)::decimal(18, 6)
        / nullif(r.eligible_d7_players, 0) as d7_retention,
    coalesce(s.session_count, 0)::decimal(18, 6)
        / nullif(a.dau, 0) as session_frequency,
    s.median_session_duration_seconds,
    coalesce(s.qualifying_session_count, 0) as qualifying_session_count,
    coalesce(v.payers, 0) as payers,
    coalesce(v.payers, 0)::decimal(18, 6) / nullif(a.dau, 0) as payer_conversion,
    coalesce(v.gross_revenue_usd, 0) as gross_revenue_usd,
    coalesce(v.refunds_usd, 0) as refunds_usd,
    coalesce(v.net_revenue_usd, 0) as net_revenue_usd,
    coalesce(v.net_revenue_usd, 0) / nullif(a.dau, 0) as arpdau,
    coalesce(e.event_participants, 0)::decimal(18, 6)
        / nullif(a.dau, 0) as event_participation_rate,
    coalesce(m.alliance_members, 0)::decimal(18, 6)
        / nullif(a.dau, 0) as alliance_adoption_rate,
    p.progression_velocity
from grain g
left join activity a using (activity_date_utc, platform, country_code, acquisition_channel)
left join installs i using (activity_date_utc, platform, country_code, acquisition_channel)
left join retention r using (activity_date_utc, platform, country_code, acquisition_channel)
left join sessions s using (activity_date_utc, platform, country_code, acquisition_channel)
left join revenue v using (activity_date_utc, platform, country_code, acquisition_channel)
left join event_participation e using (
    activity_date_utc, platform, country_code, acquisition_channel
)
left join alliance_membership m using (
    activity_date_utc, platform, country_code, acquisition_channel
)
left join progression p using (
    activity_date_utc, platform, country_code, acquisition_channel
)
