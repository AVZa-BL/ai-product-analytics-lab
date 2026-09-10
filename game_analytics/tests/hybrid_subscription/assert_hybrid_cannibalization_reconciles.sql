select *
from {{ ref('mart_hybrid_subscription__cannibalization_inputs') }}
where abs(
    total_net_revenue_usd
    - standalone_store_net_revenue_usd
    - subscription_net_revenue_usd
) > 0.01
    or abs(
        mean_total_net_revenue_per_player_usd
        - total_net_revenue_usd / nullif(eligible_player_count, 0)
    ) > 0.01
