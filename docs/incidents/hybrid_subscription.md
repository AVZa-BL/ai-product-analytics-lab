# Hybrid subscription data-quality incidents

## Purpose

This register documents known defects and semantic risks in the hybrid subscription scenario. Detection is performed by `mart_hybrid_subscription__data_quality_incidents`; downstream use is allowed only through the listed containment rules.

## Incident register

| Incident | Impact | Containment | Decision boundary |
|---|---|---|---|
| `duplicate_store_webhook` | Can overstate transaction counts and revenue. | Keep the latest ingested webhook per transaction while retaining source-row count and duplicate flags. | Use only the canonical transaction fact for revenue. |
| `mixed_timestamp_mismatch` | Can assign activity or revenue to the wrong day or analysis window. | Derive UTC from the local timestamp and named time zone; retain mismatch evidence. | Use canonical `*_at_utc` fields for all windows. |
| `missing_subscription_grant_link` | Prevents reliable attribution of granted currency to subscription payment. | Publish the ledger row, but set reconciled subscription currency to zero until linked. | Do not include unreconciled grants in subscription-value claims. |
| `post_subscription_exposure` | Creates reverse-timing bias in incrementality analysis. | Retain the raw exposure, mark it ineligible, and null approved exposure fields. | Only `is_incrementality_eligible` rows may enter exposure comparisons. |
| `cancellation_pending_expiry` | A cancellation event can be mistaken for immediate loss of access. | Preserve entitlement through contractual period end; cancellation only disables renewal. | Active-access metrics must use entitlement windows, not cancellation timestamps. |

## Ownership and response

- Analytics Engineering owns detection logic, canonicalization, and dbt controls.
- Product Analytics owns metric exclusions and interpretation boundaries.
- Monetization Engineering owns webhook idempotency and transaction-to-grant identifiers.
- CRM owns exposure timing and experiment assignment quality.

Any failed containment test blocks publication. A material increase in affected rows requires source-owner investigation before the corresponding metric is used for a product decision.

## Analytical interpretation

Contained rows remain visible for auditability. Containment makes governed metrics internally consistent; it does not make observational subscriber-versus-control differences causal. Engagement lift and store cannibalization still require design-aware analysis and explicit uncertainty.
