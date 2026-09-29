{{ config(tags=['live_strategy']) }}

with audited as (
    select
        *,
        valid_to_utc is not null
            and valid_to_utc < valid_from_utc as has_invalid_interval
    from {{ ref('stg_live_strategy__alliance_memberships') }}
),

rejected_counts as (
    select
        count(*) filter (where has_invalid_interval)
            as rejected_invalid_interval_count
    from audited
)

select
    a.membership_id,
    a.player_id,
    a.alliance_id,
    a.valid_from_utc,
    a.valid_to_utc,
    a.membership_status,
    false as has_invalid_interval,
    r.rejected_invalid_interval_count
from audited a
cross join rejected_counts r
where a.valid_to_utc is null
   or a.valid_to_utc >= a.valid_from_utc
