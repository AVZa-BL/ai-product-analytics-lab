-- Deduplication to first touch must not lose exposure rows, and no exposure
-- may precede its player's assignment.
select 'exposure_count_mismatch' as failure, null as player_id
from (
    select
        (select sum(exposure_count) from {{ ref('int_hybrid_subscription__experiment_first_exposure') }}) as modelled,
        (select count(*) from {{ ref('stg_hybrid_subscription__experiment_exposures') }}) as staged
)
where modelled is distinct from staged

union all

select 'first_exposure_before_assignment', player_id
from {{ ref('int_hybrid_subscription__experiment_first_exposure') }}
where first_exposed_at_utc < assigned_at_utc

union all

-- The late-exposure flag, recomputed from staging without the model's own columns.
select 'late_exposure_flag_mismatch', modelled.player_id
from {{ ref('int_hybrid_subscription__experiment_first_exposure') }} modelled
join (
    select
        outcome.player_id,
        coalesce(min(exposure.exposed_at_utc) > min(outcome.first_purchase_at_utc), false) as expected_flag
    from {{ ref('stg_hybrid_subscription__experiment_outcomes') }} outcome
    left join {{ ref('stg_hybrid_subscription__experiment_exposures') }} exposure using (player_id)
    group by outcome.player_id
) expected using (player_id)
where modelled.is_exposed_after_first_purchase is distinct from expected.expected_flag
