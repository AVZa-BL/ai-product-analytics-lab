with eligible_totals as (
    select
        count(*) filter (where is_subscriber) as eligible_subscriber_count,
        count(*) filter (where not is_subscriber) as eligible_control_count
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
    where analysis_period = 'pre'
),
matched_totals as (
    select count(*) as matched_pair_count
    from {{ ref('int_hybrid_subscription__matched_pairs') }}
)
-- Both ungrouped aggregates return one row even when their inputs are empty.
-- Keep population totals queryable without manufacturing a matched-pair row.
select
    eligible.eligible_subscriber_count,
    eligible.eligible_control_count,
    matched.matched_pair_count,
    eligible.eligible_subscriber_count - matched.matched_pair_count
        as unmatched_subscriber_count,
    eligible.eligible_control_count - matched.matched_pair_count
        as unmatched_control_count
from eligible_totals eligible
cross join matched_totals matched
