# Hybrid Subscription: engagement and cannibalization decision memo

## Decision

Withhold broad expansion pending a randomized, pre-exposure intent-to-treat experiment. The synthetic matched diagnostic shows a favorable engagement association alongside a negative prior-payer total-net-revenue association. This is a risk-management recommendation, not a claim that subscription caused harm.

## Executive summary

Use the [regenerated diagnostic JSON](engagement_cannibalization_diagnostic_results.json) as the numerical authority. The tables below copy its fields verbatim; no prose-only recalculation or obsolete unpaired estimate is used. Distinguish standalone displacement from total net value: the standalone-store difference excludes subscription revenue, while total net revenue includes it. Neither quantity is profit or lifetime value. This observational analysis does not establish causality.

## Observed facts

Population counts come from `population` in the JSON:

| JSON field | Value |
| --- | --- |
| eligible_control_count | 157 |
| eligible_subscriber_count | 280 |
| matched_pair_count | 157 |
| matched_prior_payer_pair_count | 53 |
| unmatched_control_count | 0 |
| unmatched_subscriber_count | 123 |

Engagement uses all matched eligible subscriber/control pairs. Revenue uses only pairs where both players are prior payers. The unmatched subscribers and controls remain disclosed but do not contribute to either matched estimate; do not substitute unmatched players, pad controls, or interpret omitted outcomes as zero.

The following means are 28-day subscriber post-minus-pre changes minus the matched control's corresponding change. Session differences are sessions per pair; revenue differences are USD per pair.

| JSON field | Value |
| --- | --- |
| engagement_difference_in_differences | 3.337579617834395 |
| standalone_store_difference_in_differences | -17.627547169811322 |
| subscription_difference_in_differences | 9.99 |
| total_revenue_difference_in_differences | -7.637547169811319 |

Whole-pair bootstrap intervals are copied from `results.bootstrap_intervals`:

| JSON field | Interval |
| --- | --- |
| engagement_change_ci_95 | [2.9426751592356686, 3.700796178343948] |
| standalone_store_difference_in_differences_ci_95 | [-22.009778301886797, -13.06145754716981] |
| total_revenue_difference_in_differences_ci_95 | [-12.01977830188679, -3.0714575471698127] |

The JSON contains calendar-month KPIs and separate exposure-conversion / subscription-start retention cohorts under `context`. Those denominators are not the matched-pair population and their rates are not substitutes for these differences.

## Interpretation

The engagement association supports testing the proposition that a subscription can improve engagement. Standalone displacement identifies substitution risk; total net value, after including subscription cash, is the relevant revenue guardrail. Reward-track products and non-cash grants are excluded from both the total-value definition and its component accounting.

The matched comparison is not an established counterfactual. Subscriber status is self-selected and post-index; exact-strata matching on prior-payer status, platform, and acquisition channel does not remove unmeasured confounding. The negative total-revenue association motivates an experiment, not a causal-loss estimate.

## Assumptions and uncertainty

The index is each player's earliest incrementality-eligible exposure. A subscriber's first observed start must be strictly after index; a control has no observed subscription start. Unexposed or ineligible-index players are not assigned a fallback index.

Matching is deterministic greedy one-to-one nearest control without replacement. Subscribers sort by prior_payer_status, platform, acquisition_channel, pre_session_count, then player_id. Available exact-stratum controls sort by absolute pre_session_count distance, control pre_session_count, then control player_id. The order is part of the contract; unmatched handling is part of the population disclosure.

Pre windows are `[index - 28 days, index)`; post windows are `[index, index + 28 days)`. Both must lie within the global minimum/maximum governed session, transaction, and LiveOps timestamps, with one complete behavior row per player per period. Global maturity does not prove individual telemetry completeness. Cohort conversion and D30 rates are withheld until every date-cohort member's forward window matures; ratio denominators of zero produce NULL.

Bootstrap seed `42` and draws `2000` are the committed metadata. Whole-pair resampling conditions on selected matches: intervals quantify resampling variation, not confounding bias, rematching uncertainty, or proof of exchangeability/parallel trends. All inputs are deterministic synthetic lab data. The horizon does not establish real-product effects, profitability, or lifetime value.

## Data-quality qualification

The governed incident mart retains defects and containment decisions; containment does not prove absence of residual bias.

| Incident code | Affected rows | Decision status | Containment |
| --- | --- | --- | --- |
| cancellation_pending_expiry | 48 | contained | Preserve access through contractual period end; cancellation disables renewal only. |
| duplicate_store_webhook | 55 | contained | Use the latest ingested webhook per transaction and retain duplicate evidence. |
| missing_subscription_grant_link | 32 | contained | Set reconciled subscription currency to zero until a transaction link is present. |
| mixed_timestamp_mismatch | 0 | clear | Derive UTC from local timestamp plus named time zone and retain the source mismatch flag. |
| post_subscription_exposure | 20 | contained | Null approved exposure fields and exclude the row from incrementality analysis. |

Duplicate webhooks are canonicalized with evidence retained; cancellation alone preserves entitlement until expiry/revocation. Missing grant links are delivery-integrity defects, not direct cash-revenue losses. Ineligible post-subscription exposures stay visible for quality reporting while approved exposure fields are NULL.

## Recommended experiment

Randomize eligible players before exposure and analyse by assignment (intent-to-treat), not eventual subscription. Pre-specify stratification, allocation, sample size, minimum detectable effect, observation horizon, and a mature reporting boundary before launch. Use total net revenue as the primary value guardrail, session frequency as engagement evidence, standalone-store revenue as a substitution diagnostic, and cohort conversion/churn/retention as separately governed secondary outcomes.

Keep reward-track exclusion and refund accounting fixed; monitor exposure eligibility, webhook duplicates, grant reconciliation, and entitlement transitions. An expansion decision should require a pre-specified, practically meaningful total-value result without unacceptable quality or engagement guardrail breaches. No unsupported numerical launch threshold is inferred from this synthetic diagnostic.

## Reproducibility

The [tracked notebook source](../../notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py) queries `mart_hybrid_subscription__matched_incrementality` and reconciles it to the engagement/cannibalization aggregate marts before calculation. Pair lineage includes `fct_hybrid_subscription__player_behavior_28d`; the notebook does not reconstruct business metrics from raw or staging data.

The executed source version is `632094ba0a1f1eb085cb7e416e1c85e6f4431159`; execution time is `2026-09-10T21:14:23.916094Z`, both copied from the JSON metadata. The JSON is published by results commit `9932fe2e947d9eb7062e3e68dde719ddb6dae15a`.

The direct exact-source execution succeeded using a locally reconstructed governed snapshot with verified source blobs and an explicit remote-source SHA override. This is not a claim of a full dbt invocation or a real Git checkout. Jupyter kernel execution and real-checkout HEAD equivalence remain owner-run validations. The locally converted notebook is unexecuted; generated notebooks and figures are not published evidence and are not linked here.

Use the [audit](../../docs/ai-audit/hybrid_subscription.md), [metric catalogue](../../docs/metrics/hybrid_subscription.md), and JSON execution provenance for the exact validation boundary.
