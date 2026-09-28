{{ config(tags=['live_strategy']) }}

with expanded_memberships as (
    select
        d.date_day as membership_date_utc,
        m.player_id,
        m.alliance_id,
        m.membership_id,
        m.valid_from_utc,
        m.valid_to_utc,
        m.membership_status,
        m.has_invalid_interval,
        m.rejected_invalid_interval_count,
        row_number() over (
            partition by d.date_day, m.player_id
            order by m.valid_from_utc desc, m.membership_id desc
        ) as membership_recency
    from {{ ref('int_live_strategy__valid_alliance_memberships') }} m
    inner join {{ ref('dim_dates') }} d
        on d.date_day >= m.valid_from_utc::date
       and d.date_day < coalesce(m.valid_to_utc::date, date '9999-12-31')
)

select
    membership_date_utc,
    player_id,
    alliance_id,
    membership_id,
    valid_from_utc,
    valid_to_utc,
    membership_status,
    has_invalid_interval,
    rejected_invalid_interval_count
from expanded_memberships
where membership_recency = 1
