-- Matching without replacement exhausts a stratum's control pool, and the unmatched
-- subscribers are then chosen by the deterministic pre_session_count ordering rather
-- than at random. Unmatched counts alone therefore do not describe the selection.
-- Whenever both arms are non-empty the balance evidence must be present and the
-- published gap must reconcile with the two means.
--
-- The standardized mean difference is deliberately not required to be non-null: it is
-- legitimately undefined when the pooled variance is zero.
select
    matched_pair_count,
    unmatched_subscriber_count,
    mean_matched_subscriber_pre_session_count,
    mean_unmatched_subscriber_pre_session_count,
    pre_session_count_selection_gap
from {{ ref('mart_hybrid_subscription__match_population_summary') }}
where matched_pair_count > 0
  and unmatched_subscriber_count > 0
  and (
      mean_matched_subscriber_pre_session_count is null
      or mean_unmatched_subscriber_pre_session_count is null
      or pre_session_count_selection_gap is null
      or abs(
          pre_session_count_selection_gap
          - (
              mean_unmatched_subscriber_pre_session_count
              - mean_matched_subscriber_pre_session_count
          )
      ) > 0.000000001
  )
