# Hybrid Subscription metric catalogue

This catalogue governs the decision metrics for the hybrid game subscription scenario. Calendar dates and timestamps use UTC. All 28-day behavior windows are half-open intervals `[window_start_at_utc, window_end_at_utc)`. Rates and per-player metrics must be recomputed from published numerators and denominators when segments are combined; do not average precomputed rates. A zero denominator produces `null`, not zero.

## 28-day engagement lift

**Source relation:** `mart_hybrid_subscription__engagement_lift_inputs`

**Grain:** One row per analysis period, eventual-subscriber flag, prior-payer status, platform, and acquisition channel.

**Population:** Governed players with complete pre- and post-index 28-day observation windows. The index is the first eligible marketing exposure, or the documented scenario boundary for unexposed players.

**Formula:** Absolute lift is the weighted post-period mean sessions per player minus the weighted pre-period mean sessions per player. Relative lift is the absolute lift divided by the weighted pre-period mean. Weight segment means by `eligible_player_count` when aggregating.

**Maturity rule:** Publish only after both 28-day windows are complete for every included player and the session ingestion watermark has passed the post-window end.

**Exclusions:** Invalid players, sessions outside governed windows, sessions failing canonical timestamp rules, and players without both mature periods.

**Owner:** Product Analytics.

**Interpretation boundary:** This is descriptive unless computed on a pre-specified randomized, incrementality-eligible exposure population. Eventual-subscriber segmentation is post-treatment and must not be interpreted as a causal subscription effect.

## Standalone-store net revenue per player

**Source relation:** `mart_hybrid_subscription__cannibalization_inputs`

**Grain:** One row per analysis period and subscriber status among prior payers.

**Population:** Governed prior payers with complete 28-day windows.

**Formula:** `standalone_store_net_revenue / eligible_player_count`, using canonical succeeded transactions net of linked refunds and excluding subscription and reward-track products.

**Maturity rule:** Publish after the full 28-day window and documented transaction/refund-lag allowance have elapsed.

**Exclusions:** Duplicate store webhooks, failed transactions, transactions outside the analysis window, subscription products, reward-track products, and rows failing product or player integrity checks.

**Owner:** Monetization Analytics.

**Interpretation boundary:** A decline measures displacement of standalone-store revenue only. It does not establish a decline in total player value or prove subscription cannibalization.

## Subscription net revenue per player

**Source relation:** `mart_hybrid_subscription__cannibalization_inputs`

**Grain:** One row per analysis period and subscriber status among prior payers.

**Population:** Governed prior payers with complete 28-day windows.

**Formula:** `subscription_net_revenue / eligible_player_count`, using canonical subscription-product transactions net of linked refunds.

**Maturity rule:** Publish after the full 28-day window and documented transaction/refund-lag allowance have elapsed.

**Exclusions:** Duplicate store webhooks, failed transactions, non-subscription products, transactions outside the analysis window, and rows failing product or player integrity checks.

**Owner:** Subscription Analytics.

**Interpretation boundary:** This is recognized subscription revenue inside the governed 28-day window, not recurring lifetime value, bookings, or currency-grant value.

## Total net revenue per player

**Source relation:** `mart_hybrid_subscription__cannibalization_inputs`

**Grain:** One row per analysis period and subscriber status among prior payers.

**Population:** Governed prior payers with complete 28-day windows.

**Formula:** `(standalone_store_net_revenue + subscription_net_revenue) / eligible_player_count`. Recompute from summed revenue and player counts when combining rows.

**Maturity rule:** Publish after the full 28-day window and documented transaction/refund-lag allowance have elapsed.

**Exclusions:** Duplicate store webhooks, failed transactions, reward-track products, transactions outside the analysis window, and rows failing product or player integrity checks. Currency grants are non-cash and excluded.

**Owner:** Monetization Analytics.

**Interpretation boundary:** This is the primary value guardrail for store displacement. It describes 28-day net revenue and does not identify causal lift, profitability, or lifetime value.

## Prior-payer standalone-store cannibalization

**Source relation:** `mart_hybrid_subscription__cannibalization_inputs`

**Grain:** A comparison across pre/post analysis periods and subscriber status for prior payers.

**Population:** Governed prior payers with mature pre- and post-index 28-day windows.

**Formula:** Difference-in-differences: `(subscriber post standalone-store revenue per player - subscriber pre) - (non-subscriber post - non-subscriber pre)`. Report the subscriber pre/post change separately and pair the result with total net revenue per player.

**Maturity rule:** All four comparison cells must contain eligible players with complete 28-day windows and mature transaction/refund data.

**Exclusions:** Players outside the governed prior-payer population and all transaction exclusions defined for standalone-store net revenue per player.

**Owner:** Monetization Analytics.

**Interpretation boundary:** Subscriber status is self-selected and the comparison remains observational. The estimate can indicate displacement risk but cannot prove that the subscription caused cannibalization.

## Subscription-grant reconciliation rate

**Source relation:** `mart_hybrid_subscription__daily_kpis`

**Grain:** One row per UTC metric date and prior-payer status.

**Population:** Governed subscription-grant ledger entries expected from eligible subscription transactions or entitlements.

**Formula:** `reconciled_subscription_grant_count / subscription_grant_count`. Aggregate by summing both counts before division.

**Maturity rule:** The ledger and transaction ingestion watermarks must be later than the measurement window end plus the documented four-minute fixture latency.

**Exclusions:** Non-subscription grant types, orphaned or duplicate ledger rows, transactions outside governed status rules, and entries outside the reporting window.

**Owner:** Data Platform Analytics.

**Interpretation boundary:** This is a delivery-integrity control, not a revenue or engagement KPI. A low rate blocks grant-dependent interpretation until reconciliation is restored.

## Incrementality-eligible exposure rate

**Source relation:** `fct_hybrid_subscription__marketing_exposures`

**Grain:** One row per canonical marketing exposure; report aggregates by UTC date and experiment arm.

**Population:** All governed subscription marketing exposures with a valid experiment arm and player identity.

**Formula:** `count(exposures where is_incrementality_eligible) / count(all governed exposures)`. Sum eligible and total exposure counts before division.

**Maturity rule:** Publish after the exposure ingestion watermark passes the reporting-window end and eligibility can be evaluated against entitlement state at exposure time.

**Exclusions:** Duplicate exposures, missing experiment arms, invalid players, and exposures that occur after subscription entitlement begins are ineligible for incrementality analysis.

**Owner:** CRM Analytics.

**Interpretation boundary:** This is an experiment-readiness and data-quality rate, not a treatment effect. Only eligible randomized exposures may support an incremental subscription or engagement claim.
