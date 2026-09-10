select activity_date_utc, platform, country_code, acquisition_channel
from {{ ref('mart_live_strategy__daily_kpis') }}
where abs(arpdau - net_revenue_usd / nullif(dau, 0)) > 0.0001
   or abs(
       payer_conversion
       - payers::decimal(18, 6) / nullif(dau, 0)
   ) > 0.0001
