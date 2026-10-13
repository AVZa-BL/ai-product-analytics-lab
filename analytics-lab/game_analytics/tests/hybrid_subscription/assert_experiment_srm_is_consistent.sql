-- Recompute the statistic from staging with explicit per-arm columns and check the
-- model's chi-square, p-value and flag against it, within floating-point tolerance.
with counts as (
    select
        experiment_id,
        count(*) filter (where arm = 'control') as control_players,
        count(*) filter (where arm = 'variant_b') as variant_b_players,
        count(*) filter (where arm = 'variant_c') as variant_c_players
    from {{ ref('stg_hybrid_subscription__experiment_assignments') }}
    group by experiment_id
),
expected as (
    select
        *,
        (control_players + variant_b_players + variant_c_players) / 3.0 as expected_players
    from counts
)
select modelled.experiment_id
from {{ ref('int_hybrid_subscription__experiment_srm') }} modelled
join expected using (experiment_id)
where abs(
        modelled.chi_square - (
            power(control_players - expected_players, 2)
            + power(variant_b_players - expected_players, 2)
            + power(variant_c_players - expected_players, 2)
        ) / expected_players
    ) > 1e-9
    or abs(modelled.p_value - exp(-modelled.chi_square / 2)) > 1e-12
    or modelled.is_srm_flagged is distinct from (modelled.p_value < 0.001)
