# Hybrid Subscription metric catalogue

The ten approved KPI contracts below are governed by [dbt KPI metadata](../../game_analytics/models/hybrid_subscription/marts/kpi_schema.yml). All dates and timestamps are UTC. Calendar-month KPIs, exposure/start cohorts, and matched 28-day diagnostics have different populations and must not be substituted for one another. Product Analytics owns activity/cohort definitions; Monetization Analytics owns cash-value definitions; Data Platform owns canonicalization and incident containment.

## Shared population, matching, and accounting rules

The analysis index is the earliest incrementality-eligible exposure, not a fallback boundary for unexposed players. Governed exposure eligibility precedes the first observed subscription start; post-subscription exposures remain visible for incident reporting but their approved exposure fields are NULL. Subscriber candidates have a first start strictly after the index; controls have no observed subscription start.

Matching is deterministic greedy one-to-one nearest-control matching without replacement, exact on prior_payer_status, platform, and acquisition_channel. Subscribers sort by those strata, pre_session_count, then player_id. Within the same stratum, available controls sort by absolute pre_session_count distance, control pre_session_count, then control player_id. No rank-to-rank substitute or cross-stratum fallback is allowed. Unmatched subscribers and controls remain reported in the population summary but are excluded from pair estimates; never pad missing controls, reuse controls, or treat unmatched outcomes as zero.

Player identity and matching covariates must be non-null/nonblank; prior_payer_status must be prior_payer or prior_nonpayer. Invalid candidates are excluded before behavior and matching, with their reasons retained. `mart_hybrid_subscription__match_population_summary` always publishes one row with candidate, excluded-by-reason, eligible, matched and unmatched counts, including zero pairs. With no pairs, estimates/intervals are NULL and unsupported bootstrap/plots are skipped; with no prior-payer pairs, engagement remains available but revenue estimates do not.

Matched-window maturity uses each source separately, not the global observation maximum used for descriptive calendar/cohort context. `int_hybrid_subscription__source_watermarks` publishes event bounds and ingestion evidence for sessions, canonical transactions and LiveOps. Each source must be present, contain finite non-null event/ingestion times with nonnegative lag, cover `[index - 28 days, index + 28 days]` at source level, and have its maximum ingestion timestamp at least the post endpoint plus its maximum observed nonnegative ingestion lag. The allowed behavior windows themselves are half-open. This empirical post-window allowance is derived from existing ingestion timestamps, not a wall-clock boundary or fabricated telemetry. Missing/invalid/stale sources fail closed; reasons and source evidence remain in the summary and incident register.

This snapshot proxy is not an operational completeness SLA: unseen late events, ingestion outages not visible in the snapshot, and individual telemetry gaps remain possible. One complete behavior row per player per period is required. UTC is set on dbt/notebook connections; date/month operations explicitly use UTC and fixed 28/30-day horizons use 672/720 elapsed hours to remain invariant across DST. Matching does not establish causality, exchangeability, or parallel trends.

Recognized cash revenue comes from canonical succeeded/refunded transactions, with refunds netted; failed transactions contribute zero. Standalone-store excludes subscription and reward-track products. Total net revenue is standalone-store plus subscription revenue, excluding reward-track revenue and non-cash currency grants. Do not subtract discounts or refunds again. Ratios return NULL on a zero denominator; counts may legitimately be zero. Reaggregate ratios from summed numerators and denominators, not unweighted means of rates. Do not sum population-summary counts repeated on pair rows. Empty matched strata remain absent, not zero effects.

## MAU

**Source model:** mart_hybrid_subscription__monthly_kpis

**Grain:** One row per UTC calendar month.

**Numerator:** mau: count of distinct players with at least one canonical session in the month.

**Denominator:** Not applicable: distinct-player count, not a rate.

**Exclusions:** Players with no canonical session in the month; duplicate session rows do not create additional active players.

**Maturity:** Calendar month in UTC; governed as_of_at_utc is the minimum ingestion-mature-through timestamp across the three required valid outcome sources. The first partial coverage month is suppressed; before the next month, publish only facts at or before as_of_at_utc as month-to-date values labelled incomplete.

**Interpretation boundary:** Descriptive monthly activity, not daily active users summed across days and not evidence of a subscription effect.

## Active subscribers

**Source model:** mart_hybrid_subscription__daily_kpis; mart_hybrid_subscription__monthly_kpis; fct_hybrid_subscription__subscriber_daily; fct_hybrid_subscription__subscription_entitlements

**Grain:** UTC metric_date by prior_payer_status for daily counts; calendar month for opening and closing balances.

**Numerator:** Distinct entitled players: active_subscriber_count from subscriber_daily; month_start_active_subscriber_count at exactly 00:00 UTC on the first day; month_end_active_subscriber_count on the last calendar date.

**Denominator:** Not applicable: distinct-player count, not entitlement-record count.

**Exclusions:** Players outside governed entitlement state; never use eventual-subscriber status. Opening balance excludes starts later on the first day. Cancellation alone does not remove access before expiry/revocation.

**Maturity:** Daily state follows governed date-grain entitlement coverage. The opening balance is point-in-time; month-end balance is NULL until as_of_at_utc reaches the next month.

**Interpretation boundary:** A stock of active access, not starts, billed customers, or a sum across dates. The daily fact uses start-date inclusive/end-date exclusive coverage; use exact entitlement timestamps for the monthly opening balance.

## Subscription conversion

**Source model:** mart_hybrid_subscription__subscription_cohorts

**Grain:** cohort_type = eligible_exposure and UTC date of each player's earliest incrementality-eligible exposure.

**Numerator:** converted_within_28d_player_count: distinct exposed players whose first entitlement starts strictly after exposure and before exposure plus 28 days, observed by as_of_at_utc.

**Denominator:** eligible_exposed_player_count: distinct eligible exposed players; no matching or mature pre-window requirement.

**Exclusions:** Ineligible exposures, starts at/before exposure or at/after exposure plus 28 days; subscription_start cohort rows are non-applicable.

**Maturity:** Rate is NULL until every member is mature: latest exact exposure in the date cohort plus 28 days <= as_of_at_utc; NULL for zero denominator and non-exposure rows.

**Interpretation boundary:** Observed forward conversion among eligible exposed players, not matched engagement lift or causal marketing incrementality.

## Subscriber churn

**Source model:** mart_hybrid_subscription__monthly_kpis

**Grain:** One row per UTC calendar month.

**Numerator:** expired_or_revoked_entitlement_count: distinct subscription_id values with an observed terminal expiry/revocation timestamp in the month.

**Denominator:** month_start_active_subscriber_count: distinct players entitled at exactly the opening instant.

**Exclusions:** Cancellation alone is not churn; ignore cancellation as a terminal event and exclude terminal timestamps after as_of_at_utc.

**Maturity:** Calendar month in UTC; governed as_of_at_utc is the minimum ingestion-mature-through timestamp across the three required valid outcome sources. The first partial coverage month is suppressed; before the next month, publish only facts at or before as_of_at_utc as month-to-date values labelled incomplete. NULL for zero opening denominator.

**Interpretation boundary:** An entitlement-event rate, not a capped player-loss probability: numerator counts entitlements and denominator counts opening players, so the rate may exceed one. Do not silently redefine it as distinct lost players.

## D30 subscriber retention

**Source model:** mart_hybrid_subscription__subscription_cohorts

**Grain:** cohort_type = subscription_start and UTC first-entitlement-start date.

**Numerator:** retained_at_d30_player_count: distinct mature starters entitled at exact start plus 30 days.

**Denominator:** mature_subscription_starter_count: distinct starters whose exact start plus 30 days <= as_of_at_utc.

**Exclusions:** Immature starters from the denominator; eligible_exposure rows are non-applicable. Entitlements are half-open: expiry exactly at D30 is not retained.

**Maturity:** Rate is NULL until every member of the date cohort is mature (latest exact start plus 30 days <= as_of_at_utc); NULL for zero denominator and non-start rows.

**Interpretation boundary:** Entitlement retention at an exact time, not activity retention, renewal intent, lifetime value, or a partial-cohort rate.

## ARPMAU

**Source model:** mart_hybrid_subscription__monthly_kpis

**Grain:** One row per UTC calendar month.

**Numerator:** total_net_revenue_usd = standalone_store_net_revenue_usd + subscription_net_revenue_usd, from canonical recognized transaction revenue net of refunds.

**Denominator:** mau: distinct monthly active players.

**Exclusions:** Reward-track revenue (reward-track products) and non-cash grants are excluded; failed transactions contribute zero recognized revenue; canonicalization contains duplicate webhooks.

**Maturity:** Calendar month in UTC; governed as_of_at_utc is the minimum ingestion-mature-through timestamp across the three required valid outcome sources. The first partial coverage month is suppressed; before the next month, publish only facts at or before as_of_at_utc as month-to-date values labelled incomplete. NULL for zero MAU.

**Interpretation boundary:** Descriptive cash revenue per MAU, not ARPPU, profit, causal value, or LTV. Revenue is not restricted to session-active payers even though the denominator is MAU.

## Incremental net revenue

**Source model:** mart_hybrid_subscription__matched_incrementality; mart_hybrid_subscription__cannibalization_inputs

**Grain:** One row per subscriber-control pair in matched_incrementality; prior_payer aggregate in cannibalization_inputs for the decision estimate.

**Numerator:** Sum of total_net_revenue_usd_difference_in_differences: each subscriber's post-minus-pre standalone-store plus subscription revenue change, minus the matched control's change.

**Denominator:** Actual matched_pair_count for pairs where both arms are prior_payer. Use component sums divided by summed pair counts; never sum repeated population totals on pair rows.

**Exclusions:** Unmatched and immature players; pairs not prior_payer in both arms for this revenue decision; reward-track revenue and non-cash grants; failed cash transactions contribute zero.

**Maturity:** Complete pre [index - 28 days, index) and post [index, index + 28 days) windows within every source's event coverage; each ingestion watermark must pass post endpoint plus its empirical maximum observed ingestion lag. One complete behavior row per player per period; missing/stale sources fail closed. This is not a completeness SLA. A zero pair denominator returns NULL; an absent stratum is not zero effect.

**Interpretation boundary:** The approved name denotes a matched observational difference-in-differences diagnostic and does not establish causality. Standalone displacement and total net value are separate; not profit or lifetime value.

## Discount utilization

**Source model:** mart_hybrid_subscription__monthly_kpis

**Grain:** One row per UTC calendar month.

**Numerator:** discounted_standalone_transaction_count: canonical succeeded/refunded standalone-store transaction rows with discount_amount_usd > 0.

**Denominator:** eligible_standalone_transaction_count: all canonical succeeded/refunded standalone-store transaction rows.

**Exclusions:** Failed transactions, subscription and reward-track products; duplicate webhooks contained by canonicalization.

**Maturity:** Calendar month in UTC; governed as_of_at_utc is the minimum ingestion-mature-through timestamp across the three required valid outcome sources. The first partial coverage month is suppressed; before the next month, publish only facts at or before as_of_at_utc as month-to-date values labelled incomplete. NULL for zero eligible transaction denominator.

**Interpretation boundary:** Transaction utilization rate, not discount dollars divided by revenue and not distinct discounted customers. Refunded eligible transactions remain in both applicable counts.

## Engagement lift

**Source model:** mart_hybrid_subscription__matched_incrementality; mart_hybrid_subscription__engagement_lift_inputs

**Grain:** One row per subscriber-control pair; exact prior_payer_status/platform/acquisition_channel stratum in engagement_lift_inputs.

**Numerator:** Sum of session_count_difference_in_differences: subscriber post-minus-pre session_count minus matched-control post-minus-pre session_count.

**Denominator:** Actual matched_pair_count across all eligible matched pairs, including prior payers and prior nonpayers.

**Exclusions:** Unmatched players, immature windows, ineligible exposure indexes, and sessions outside half-open windows.

**Maturity:** Complete pre [index - 28 days, index) and post [index, index + 28 days) windows within every source's event coverage; each ingestion watermark must pass post endpoint plus its empirical maximum observed ingestion lag. One complete behavior row per player per period; missing/stale sources fail closed. This is not a completeness SLA. NULL for zero pair denominator; an absent stratum is not zero lift.

**Interpretation boundary:** A matched observational 28-day session-count difference, not relative lift or an unpaired pre/post average. Self-selection remains; does not establish causality.

## LiveOps participation

**Source model:** mart_hybrid_subscription__monthly_kpis

**Grain:** One row per UTC calendar month.

**Numerator:** liveops_participant_count: distinct MAU players with at least one governed LiveOps participation in the same calendar month.

**Denominator:** mau: distinct players with at least one canonical session in that month.

**Exclusions:** Participants without a same-month canonical session and participations outside the month.

**Maturity:** Calendar month in UTC; governed as_of_at_utc is the minimum ingestion-mature-through timestamp across the three required valid outcome sources. The first partial coverage month is suppressed; before the next month, publish only facts at or before as_of_at_utc as month-to-date values labelled incomplete. NULL for zero MAU.

**Interpretation boundary:** Participant rate among MAU, not daily event counts or matched 28-day participation-count change; does not identify a causal engagement effect.

## Supporting diagnostics and quality controls

These support the ten KPIs; they do not replace their denominators.

| Diagnostic | Governed source and grain | Numerator / denominator | Boundary |
| --- | --- | --- | --- |
| Standalone-store displacement | `mart_hybrid_subscription__cannibalization_inputs`, matched prior-payer stratum | `standalone_store_net_revenue_usd_difference_in_differences_sum / matched_pair_count` | Mature pairs only; excludes subscription and reward-track revenue. Displacement is not total value or causal loss. |
| Subscription revenue contribution | Same prior-payer matched stratum | `subscription_net_revenue_usd_difference_in_differences_sum / matched_pair_count` | Recognized subscription cash only, net of refunds; excludes non-cash grants. Not LTV. |
| Total net value guardrail | Same prior-payer matched stratum | `total_net_revenue_usd_difference_in_differences_sum / matched_pair_count` | Store plus subscription, reward-track excluded. Observational, not profitability. |
| Subscription-grant reconciliation rate | `mart_hybrid_subscription__daily_kpis`, UTC metric_date by prior_payer_status | `reconciled_subscription_grant_count / subscription_grant_count` | Canonical subscription-grant rows only; zero denominator is NULL. Missing transaction links remain incidents and reconciled currency is zero until linked. Non-cash delivery integrity, not revenue loss. |
| Incrementality-eligible exposure rate | `fct_hybrid_subscription__marketing_exposures`, canonical exposure | Eligible exposure count / all canonical exposure count | Ineligible rows stay in denominator and incident reporting, not analysis indexes. Exposure readiness, not a treatment effect. |

Quality controls describe the observed governed snapshot. Empirical ingestion allowances do not guarantee future refund-lag or unseen-event completeness. Consult the [incident register](../incidents/hybrid_subscription.md) and [regenerated evidence](../../reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json) before decisions.
