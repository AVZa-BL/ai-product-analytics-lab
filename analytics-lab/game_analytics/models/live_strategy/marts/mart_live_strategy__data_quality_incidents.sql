{{ config(tags=['live_strategy']) }}

with intraday_change_dates as (
    select distinct effective_from_utc::date as change_date_utc
    from {{ ref('dim_live_strategy__config_versions') }}
    where cast(effective_from_utc as time) <> time '00:00:00'
),

date_level_config_matches as (
    select
        e.client_event_id,
        count(distinct c.config_version_id) as matching_config_versions
    from {{ ref('int_live_strategy__valid_gameplay_events') }} e
    inner join intraday_change_dates d
        on e.occurred_at_utc::date = d.change_date_utc
    inner join {{ ref('dim_live_strategy__config_versions') }} c
        on e.occurred_at_utc::date between
            c.effective_from_utc::date and c.effective_to_utc::date
    group by 1
),

incident_counts as (
    select
        'duplicate_android_client_events' as incident_code,
        'high' as severity,
        count(*) as affected_record_count,
        'int_live_strategy__valid_gameplay_events' as contained_relation,
        'duplicate_client_event_id' as detection_query_id
    from {{ ref('int_live_strategy__event_dedup_audit') }}
    where is_duplicate_arrival
      and platform = 'android'

    union all

    select
        'missing_android_session_ends' as incident_code,
        'medium' as severity,
        count(*) as affected_record_count,
        'fct_live_strategy__sessions' as contained_relation,
        'missing_android_session_end' as detection_query_id
    from {{ ref('int_live_strategy__session_quality') }}
    where has_missing_end
      and platform = 'android'
      and app_version = '4.12.0'

    union all

    select
        'purchase_refund_status_lag' as incident_code,
        'high' as severity,
        count(distinct r.purchase_id) as affected_record_count,
        'fct_live_strategy__purchases' as contained_relation,
        'refund_supersedes_store_status' as detection_query_id
    from {{ ref('int_live_strategy__purchase_reconciliation') }} r
    inner join {{ ref('stg_live_strategy__purchases') }} p using (purchase_id)
    where r.final_purchase_status = 'refunded'
      and p.purchase_status <> 'refunded'
      and r.refund_reconciled_at_utc > r.purchased_at_utc

    union all

    select
        'events_before_install' as incident_code,
        'high' as severity,
        count(distinct client_event_id) as affected_record_count,
        'int_live_strategy__valid_gameplay_events' as contained_relation,
        'event_timestamp_before_install' as detection_query_id
    from {{ ref('int_live_strategy__event_dedup_audit') }}
    where is_before_install

    union all

    select
        'invalid_membership_interval' as incident_code,
        'medium' as severity,
        count(*) as affected_record_count,
        'int_live_strategy__valid_alliance_memberships' as contained_relation,
        'membership_valid_to_before_valid_from' as detection_query_id
    from {{ ref('stg_live_strategy__alliance_memberships') }}
    where valid_to_utc is not null
      and valid_to_utc < valid_from_utc

    union all

    select
        'ambiguous_intraday_configuration_join' as incident_code,
        'high' as severity,
        count(*) as affected_record_count,
        'int_live_strategy__event_config_attribution' as contained_relation,
        'date_level_config_join_fanout' as detection_query_id
    from date_level_config_matches
    where matching_config_versions > 1
)

select
    current_date as incident_date_utc,
    incident_code,
    severity,
    affected_record_count,
    contained_relation,
    detection_query_id
from incident_counts
