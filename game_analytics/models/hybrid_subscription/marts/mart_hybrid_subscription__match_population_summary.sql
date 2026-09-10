-- One governed control row even when no player is eligible or no pair is found.
select 'hybrid_subscription' as population_summary_id, summary.*,
    (select to_json(list(struct_pack(
        source_name := source_name,
        source_row_count := source_row_count,
        invalid_timestamp_row_count := invalid_timestamp_row_count,
        observation_start_at_utc := observation_start_at_utc,
        observation_end_at_utc := observation_end_at_utc,
        ingestion_watermark_at_utc := ingestion_watermark_at_utc,
        post_window_allowance_seconds := post_window_allowance_seconds,
        is_source_valid := is_source_valid,
        ingestion_mature_through_at_utc := ingestion_mature_through_at_utc
    ) order by source_name))
    from {{ ref('int_hybrid_subscription__source_watermarks') }}) as source_watermarks_json
from {{ ref('int_hybrid_subscription__match_population_summary') }} summary
