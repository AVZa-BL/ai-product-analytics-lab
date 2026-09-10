with eligible_players as (
    select player_id, prior_payer_status, platform, acquisition_channel, is_subscriber
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
    where analysis_period = 'pre'
),
pairs as (
    select * from {{ ref('int_hybrid_subscription__matched_pairs') }}
),
published_summary as (
    select * from {{ ref('int_hybrid_subscription__match_population_summary') }}
),
summary_cardinality as (
    select count(*) as summary_row_count from published_summary
),
eligible_totals as (
    select
        count(*) filter (where is_subscriber) as eligible_subscriber_count,
        count(*) filter (where not is_subscriber) as eligible_control_count
    from eligible_players
),
matched_totals as (
    select
        count(*) as matched_pair_count,
        count(distinct subscriber_player_id) as matched_subscriber_count,
        count(distinct control_player_id) as matched_control_count
    from pairs
),
unmatched_totals as (
    select
        count(*) filter (
            where player.is_subscriber
              and not exists (
                  select 1 from pairs
                  where pairs.subscriber_player_id = player.player_id
              )
        ) as unmatched_subscriber_count,
        count(*) filter (
            where not player.is_subscriber
              and not exists (
                  select 1 from pairs
                  where pairs.control_player_id = player.player_id
              )
        ) as unmatched_control_count
    from eligible_players player
),
-- With no caliper, every non-null exact stratum must exhaust its smaller arm.
-- This source-derived expectation catches missing pairs even when pairs is empty.
stratum_counts as (
    select
        prior_payer_status,
        platform,
        acquisition_channel,
        count(*) filter (where is_subscriber) as subscriber_count,
        count(*) filter (where not is_subscriber) as control_count
    from eligible_players
    where prior_payer_status is not null
      and platform is not null
      and acquisition_channel is not null
    group by prior_payer_status, platform, acquisition_channel
),
expected_matches as (
    select coalesce(sum(least(subscriber_count, control_count)), 0) as matched_pair_count
    from stratum_counts
),
violations as (
    select 'invalid_summary_cardinality' as violation, null::varchar as pair_id
    from summary_cardinality
    where summary_row_count != 1

    union all

    select 'incorrect_summary_totals', null::varchar
    from published_summary summary
    cross join eligible_totals eligible
    cross join matched_totals matched
    cross join unmatched_totals unmatched
    where summary.eligible_subscriber_count is distinct from eligible.eligible_subscriber_count
       or summary.eligible_control_count is distinct from eligible.eligible_control_count
       or summary.matched_pair_count is distinct from matched.matched_pair_count
       or summary.unmatched_subscriber_count is distinct from unmatched.unmatched_subscriber_count
       or summary.unmatched_control_count is distinct from unmatched.unmatched_control_count

    union all

    -- Scalar aggregates always produce a control row, including empty populations.
    select 'population_does_not_reconcile' as violation, null::varchar as pair_id
    from eligible_totals eligible
    cross join matched_totals matched
    cross join unmatched_totals unmatched
    cross join expected_matches expected
    where matched.matched_pair_count != expected.matched_pair_count
       or matched.matched_pair_count != matched.matched_subscriber_count
       or matched.matched_pair_count != matched.matched_control_count
       or eligible.eligible_subscriber_count !=
            matched.matched_subscriber_count + unmatched.unmatched_subscriber_count
       or eligible.eligible_control_count !=
            matched.matched_control_count + unmatched.unmatched_control_count

    union all

    select 'incorrect_published_totals', pair.pair_id
    from pairs pair
    cross join eligible_totals eligible
    cross join matched_totals matched
    cross join unmatched_totals unmatched
    where pair.eligible_subscriber_count is distinct from eligible.eligible_subscriber_count
       or pair.eligible_control_count is distinct from eligible.eligible_control_count
       or pair.matched_pair_count is distinct from matched.matched_pair_count
       or pair.unmatched_subscriber_count is distinct from unmatched.unmatched_subscriber_count
       or pair.unmatched_control_count is distinct from unmatched.unmatched_control_count
)
select * from violations
