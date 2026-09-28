{{ config(tags=['live_strategy']) }}

with player_install_config as (
    select
        p.player_id,
        p.install_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        c.config_version_id
    from {{ ref('dim_live_strategy__players') }} p
    inner join {{ ref('dim_live_strategy__config_versions') }} c
        on p.installed_at_utc >= c.effective_from_utc
       and p.installed_at_utc < coalesce(
           c.effective_to_utc,
           timestamp '9999-12-31 00:00:00'
       )
),

eligible_players as (
    select
        p.player_id,
        c.install_date_utc,
        c.period,
        c.platform,
        c.country_code,
        c.acquisition_channel,
        c.config_version_id
    from {{ ref('mart_live_strategy__retention_cohorts') }} c
    inner join player_install_config p
        on c.install_date_utc = p.install_date_utc
       and c.platform = p.platform
       and c.country_code = p.country_code
       and c.acquisition_channel = p.acquisition_channel
       and c.config_version_id = p.config_version_id
    where c.eligible_d7_players > 0
),

progression_by_player as (
    select
        e.player_id,
        sum(p.upgrade_attempts) as upgrade_attempts,
        (max(p.level) - min(p.level))::decimal(18, 6)
            / nullif(
                date_diff('day', min(p.snapshot_at_utc), max(p.snapshot_at_utc)),
                0
            ) as progression_velocity
    from eligible_players e
    left join {{ ref('fct_live_strategy__progression_daily') }} p
        on e.player_id = p.player_id
       and p.progression_date_utc between e.install_date_utc and e.install_date_utc + 7
    group by 1
),

player_signals as (
    select
        e.*,
        exists (
            select 1
            from {{ ref('fct_live_strategy__player_activity_daily') }} a
            where a.player_id = e.player_id
              and a.activity_date_utc = e.install_date_utc + 7
        ) as has_robust_activity_d7,
        exists (
            select 1
            from {{ ref('fct_live_strategy__sessions') }} s
            where s.player_id = e.player_id
              and s.session_date_utc = e.install_date_utc + 7
              and s.is_valid_completed_session
        ) as has_completed_session_d7,
        p.upgrade_attempts,
        p.progression_velocity
    from eligible_players e
    left join progression_by_player p
        on e.player_id = p.player_id
),

expanded_signals as (
    select
        *,
        'robust_activity' as retention_signal,
        has_robust_activity_d7 as is_retained
    from player_signals

    union all

    select
        *,
        'completed_session' as retention_signal,
        has_completed_session_d7 as is_retained
    from player_signals
)

select
    install_date_utc,
    period,
    platform,
    country_code,
    acquisition_channel,
    config_version_id,
    retention_signal,
    count(*) as eligible_players,
    count(*) filter (where is_retained) as retained_players,
    count(*) filter (where is_retained)::decimal(18, 6)
        / nullif(count(*), 0) as retention_rate,
    median(upgrade_attempts) as median_upgrade_attempts,
    median(progression_velocity) as median_progression_velocity
from expanded_signals
group by 1, 2, 3, 4, 5, 6, 7
