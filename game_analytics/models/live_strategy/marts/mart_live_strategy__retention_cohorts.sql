{{ config(tags=['live_strategy']) }}

with observation_window as (
    select max(activity_date_utc) as max_activity_date
    from {{ ref('fct_live_strategy__player_activity_daily') }}
),

update_boundary as (
    select min(effective_from_utc) as update_at_utc
    from {{ ref('dim_live_strategy__config_versions') }}
    where upgrade_cost_multiplier > 1.00
       or event_reward_multiplier < 1.00
),

installs as (
    select
        p.player_id,
        p.installed_at_utc,
        p.install_date_utc,
        p.platform,
        p.country_code,
        p.acquisition_channel,
        c.config_version_id,
        case
            when p.installed_at_utc < u.update_at_utc then 'pre_update'
            else 'post_update'
        end as period,
        o.max_activity_date
    from {{ ref('dim_live_strategy__players') }} p
    inner join {{ ref('dim_live_strategy__config_versions') }} c
        on p.installed_at_utc >= c.effective_from_utc
       and p.installed_at_utc < coalesce(
           c.effective_to_utc,
           timestamp '9999-12-31 00:00:00'
       )
    cross join observation_window o
    cross join update_boundary u
),

player_retention as (
    select
        i.*,
        i.install_date_utc <= i.max_activity_date - 1 as is_d1_eligible,
        i.install_date_utc <= i.max_activity_date - 7 as is_d7_eligible,
        exists (
            select 1
            from {{ ref('fct_live_strategy__player_activity_daily') }} a
            where a.player_id = i.player_id
              and a.activity_date_utc = i.install_date_utc + 1
        ) as is_retained_d1,
        exists (
            select 1
            from {{ ref('fct_live_strategy__player_activity_daily') }} a
            where a.player_id = i.player_id
              and a.activity_date_utc = i.install_date_utc + 7
        ) as is_retained_d7
    from installs i
)

select
    install_date_utc,
    period,
    platform,
    country_code,
    acquisition_channel,
    config_version_id,
    count(*) as installed_players,
    count(*) filter (where is_d1_eligible) as eligible_d1_players,
    count(*) filter (where is_d1_eligible and is_retained_d1) as retained_d1_players,
    count(*) filter (where is_d7_eligible) as eligible_d7_players,
    count(*) filter (where is_d7_eligible and is_retained_d7) as retained_d7_players,
    count(*) filter (where is_d1_eligible and is_retained_d1)::decimal(18, 6)
        / nullif(count(*) filter (where is_d1_eligible), 0) as d1_retention,
    count(*) filter (where is_d7_eligible and is_retained_d7)::decimal(18, 6)
        / nullif(count(*) filter (where is_d7_eligible), 0) as d7_retention
from player_retention
group by 1, 2, 3, 4, 5, 6
