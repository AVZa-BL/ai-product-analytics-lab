with pairs as (
    select * from {{ ref('int_hybrid_subscription__matched_pairs') }}
),
eligible_players as (
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
-- Reconstruct each choice from earlier published pairs, independently of
-- the matcher's recursive used-control list. Include unmatched subscribers.
expected_choices as (
    select
        subscriber.player_id as subscriber_player_id,
        chosen.player_id as control_player_id
    from ordered_subscribers subscriber
    left join lateral (
        select control.player_id
        from controls control
        where control.prior_payer_status = subscriber.prior_payer_status
          and control.platform = subscriber.platform
          and control.acquisition_channel = subscriber.acquisition_channel
          and not exists (
              select 1
              from pairs earlier_pair
              join ordered_subscribers earlier_subscriber
                on earlier_pair.subscriber_player_id = earlier_subscriber.player_id
              where earlier_pair.control_player_id = control.player_id
                and earlier_subscriber.subscriber_sequence
                    < subscriber.subscriber_sequence
          )
        order by
            abs(control.pre_session_count - subscriber.pre_session_count),
            control.pre_session_count,
            control.player_id
        limit 1
    ) chosen on true
),
violations as (
    select 'duplicate_pair' as violation, pair_id as row_id
    from pairs group by pair_id having count(*) != 1

    union all

    select 'duplicate_subscriber', subscriber_player_id
    from pairs group by subscriber_player_id having count(*) != 1

    union all

    select 'reused_control', control_player_id
    from pairs group by control_player_id having count(*) != 1

    union all

    select 'duplicate_sequence', cast(subscriber_sequence as varchar)
    from pairs group by subscriber_sequence having count(*) != 1

    union all

    select 'invalid_pair_attributes', pair.pair_id
    from pairs pair
    left join ordered_subscribers subscriber
        on pair.subscriber_player_id = subscriber.player_id
    left join controls control
        on pair.control_player_id = control.player_id
    where subscriber.player_id is null
       or control.player_id is null
       or pair.pair_id is distinct from
            pair.subscriber_player_id || '__' || pair.control_player_id
       or pair.subscriber_sequence is distinct from subscriber.subscriber_sequence
       or pair.subscriber_prior_payer_status
            is distinct from pair.control_prior_payer_status
       or pair.subscriber_platform is distinct from pair.control_platform
       or pair.subscriber_acquisition_channel
            is distinct from pair.control_acquisition_channel
       or pair.subscriber_prior_payer_status is distinct from subscriber.prior_payer_status
       or pair.control_prior_payer_status is distinct from control.prior_payer_status
       or pair.subscriber_platform is distinct from subscriber.platform
       or pair.control_platform is distinct from control.platform
       or pair.subscriber_acquisition_channel is distinct from subscriber.acquisition_channel
       or pair.control_acquisition_channel is distinct from control.acquisition_channel
       or pair.subscriber_pre_session_count is distinct from subscriber.pre_session_count
       or pair.control_pre_session_count is distinct from control.pre_session_count
       or pair.pre_session_count_distance is distinct from
            abs(subscriber.pre_session_count - control.pre_session_count)

    union all

    select 'incorrect_greedy_choice', expected.subscriber_player_id
    from expected_choices expected
    left join pairs pair
        on expected.subscriber_player_id = pair.subscriber_player_id
    where pair.control_player_id is distinct from expected.control_player_id
)
select * from violations
