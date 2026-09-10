select
    player.player_id,
    player.country_code,
    player.platform,
    player.acquisition_channel,
    player.prior_payer_status,
    player.acquired_at_utc,
    population.first_subscription_at_utc,
    population.is_subscriber,
    player.scenario_run_id
from {{ ref('stg_hybrid_subscription__players') }} player
left join {{ ref('int_hybrid_subscription__analysis_population') }} population
    using (player_id)
