-- Every assigned player is kept; exclusions are flagged with a reason, not dropped.
-- The pre-assignment window is 672 elapsed hours so it does not move across DST.
with pre_assignment_sessions as (
    select
        exposure.player_id,
        count(pre_session.session_id) as pre_sessions_28d
    from {{ ref('int_hybrid_subscription__experiment_first_exposure') }} exposure
    left join {{ ref('stg_hybrid_subscription__sessions') }} pre_session
        on pre_session.player_id = exposure.player_id
        and pre_session.started_at_utc >= exposure.assigned_at_utc - interval '672 hours'
        and pre_session.started_at_utc < exposure.assigned_at_utc
    group by exposure.player_id
),
verdicts as (
    select
        exposure.*,
        player.platform,
        player.acquisition_channel,
        player.prior_payer_status,
        pre.pre_sessions_28d,
        case
            when not exposure.is_exposed then 'never_exposed'
            when exposure.is_exposed_after_first_purchase then 'exposed_after_first_purchase'
        end as exclusion_reason
    from {{ ref('int_hybrid_subscription__experiment_first_exposure') }} exposure
    left join {{ ref('stg_hybrid_subscription__players') }} player using (player_id)
    left join pre_assignment_sessions pre using (player_id)
)
select *, exclusion_reason is null as is_eligible
from verdicts
