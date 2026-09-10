with recursive
eligible_players as (
    -- Behavior already has one mature eligible row per player and period.
    -- Restricting to pre yields one player row without post-treatment inputs.
    select
        player_id,
        prior_payer_status,
        platform,
        acquisition_channel,
        is_subscriber,
        session_count as pre_session_count
    from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
    where analysis_period = 'pre'
),
ordered_subscribers as (
    select
        *,
        row_number() over (
            order by prior_payer_status, platform, acquisition_channel,
                     pre_session_count, player_id
        ) as subscriber_sequence
    from eligible_players
    where is_subscriber
),
controls as (
    select * from eligible_players where not is_subscriber
),
matching as (
    select
        0::bigint as subscriber_sequence,
        null::varchar as subscriber_player_id,
        null::varchar as control_player_id,
        []::varchar[] as used_control_ids

    union all

    select
        subscriber.subscriber_sequence,
        subscriber.player_id,
        chosen.player_id,
        case
            when chosen.player_id is null then matching.used_control_ids
            else list_append(matching.used_control_ids, chosen.player_id)
        end
    from matching
    join ordered_subscribers subscriber
        on subscriber.subscriber_sequence = matching.subscriber_sequence + 1
    left join lateral (
        select control.player_id
        from controls control
        where control.prior_payer_status = subscriber.prior_payer_status
          and control.platform = subscriber.platform
          and control.acquisition_channel = subscriber.acquisition_channel
          and not list_contains(matching.used_control_ids, control.player_id)
        order by
            abs(control.pre_session_count - subscriber.pre_session_count),
            control.pre_session_count,
            control.player_id
        limit 1
    ) chosen on true
),
selected_pairs as (
    select subscriber_sequence, subscriber_player_id, control_player_id
    from matching
    where subscriber_sequence > 0
      and control_player_id is not null
),
population_totals as (
    select
        count(*) filter (where is_subscriber) as eligible_subscriber_count,
        count(*) filter (where not is_subscriber) as eligible_control_count
    from eligible_players
),
match_totals as (
    select count(*) as matched_pair_count
    from selected_pairs
)
select
    pair.subscriber_player_id || '__' || pair.control_player_id as pair_id,
    pair.subscriber_sequence,
    pair.subscriber_player_id,
    pair.control_player_id,
    subscriber.prior_payer_status as subscriber_prior_payer_status,
    control.prior_payer_status as control_prior_payer_status,
    subscriber.platform as subscriber_platform,
    control.platform as control_platform,
    subscriber.acquisition_channel as subscriber_acquisition_channel,
    control.acquisition_channel as control_acquisition_channel,
    subscriber.pre_session_count as subscriber_pre_session_count,
    control.pre_session_count as control_pre_session_count,
    abs(subscriber.pre_session_count - control.pre_session_count) as pre_session_count_distance,
    population_totals.eligible_subscriber_count,
    population_totals.eligible_control_count,
    match_totals.matched_pair_count,
    population_totals.eligible_subscriber_count - match_totals.matched_pair_count
        as unmatched_subscriber_count,
    population_totals.eligible_control_count - match_totals.matched_pair_count
        as unmatched_control_count
from selected_pairs pair
join ordered_subscribers subscriber
    on pair.subscriber_player_id = subscriber.player_id
join controls control
    on pair.control_player_id = control.player_id
cross join population_totals
cross join match_totals
