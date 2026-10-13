-- No assigned player may disappear or be duplicated on the way to the eligible population.
select 'row_count_mismatch' as failure
from (
    select
        (select count(*) from {{ ref('int_hybrid_subscription__experiment_eligible_population') }}) as modelled,
        (select count(*) from {{ ref('stg_hybrid_subscription__experiment_assignments') }}) as staged
)
where modelled is distinct from staged
