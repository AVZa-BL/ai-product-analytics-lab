-- One fail-closed boundary shared by every forward-looking hybrid analysis.
-- Coverage begins only when every required source is present, and maturity ends
-- at the least-advanced source after accounting for its observed ingestion lag.
select
    count(*) = 3
        and bool_and(is_source_valid)
        and count(ingestion_mature_through_at_utc) = 3
        as are_source_watermarks_valid,
    max(observation_start_at_utc) as observation_start_at_utc,
    min(observation_end_at_utc) as observation_end_at_utc,
    min(ingestion_mature_through_at_utc) as as_of_at_utc
from {{ ref('int_hybrid_subscription__source_watermarks') }}
