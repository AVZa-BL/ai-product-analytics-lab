-- Snapshot-derived completeness proxy, not an operational completeness SLA.
-- Each outcome source must independently cover the full window and advance its
-- ingestion watermark beyond post_end plus its maximum observed ingestion lag.
with source_names as (
    select * from (values ('sessions'), ('store_transactions'),
        ('live_event_participation')) as names(source_name)
),
events as (
    select 'sessions' as source_name, started_at_utc as observed_at_utc, ingested_at_utc
    from {{ ref('stg_hybrid_subscription__sessions') }}
    union all
    select 'store_transactions', transaction_at_utc, ingested_at_utc
    from {{ ref('stg_hybrid_subscription__store_transactions') }}
    union all
    select 'live_event_participation', participated_at_utc, ingested_at_utc
    from {{ ref('stg_hybrid_subscription__live_event_participation') }}
),
source_bounds as (
    select names.source_name,
        count(events.source_name) as source_row_count,
        count(events.source_name) filter (
            where observed_at_utc is null or ingested_at_utc is null
               or not isfinite(observed_at_utc) or not isfinite(ingested_at_utc)
               or ingested_at_utc < observed_at_utc
        ) as invalid_timestamp_row_count,
        min(observed_at_utc) as observation_start_at_utc,
        max(observed_at_utc) as observation_end_at_utc,
        max(ingested_at_utc) as ingestion_watermark_at_utc,
        max(epoch(ingested_at_utc) - epoch(observed_at_utc)) filter (
            where ingested_at_utc >= observed_at_utc
                and isfinite(observed_at_utc) and isfinite(ingested_at_utc)
        ) as post_window_allowance_seconds
    from source_names names left join events using (source_name)
    group by names.source_name
)
select *,
    source_row_count > 0 and invalid_timestamp_row_count = 0 as is_source_valid,
    case when source_row_count > 0 and invalid_timestamp_row_count = 0 then
        to_timestamp(epoch(ingestion_watermark_at_utc) - post_window_allowance_seconds)
    end as ingestion_mature_through_at_utc
from source_bounds
