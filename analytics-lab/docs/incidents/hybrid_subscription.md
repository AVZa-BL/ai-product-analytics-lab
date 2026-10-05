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
| `analysis_population_exclusion` | Invalid matching identity/covariates, exposure timing or incomplete source coverage can invalidate matched outcomes. | Exclude before behavior/matching; retain candidate and per-reason counts plus event/ingestion watermark evidence in the one-row population summary mart. | Every outcome source must cover the windows and pass its empirical ingestion allowance; no completeness SLA or causal claim follows. |
| `experiment_exposure_after_purchase` | The offer cannot have caused a purchase made before the player saw it, so including these players biases purchase and revenue comparisons. | Exclude the player from outcome figures, retain the row with the reason `exposed_after_first_purchase`, and publish assigned and excluded counts. | Outcome figures cover eligible players only. Excluding these players selects on a post-assignment event, so the means describe the eligible players, not everyone assigned. |
| `experiment_sample_ratio_mismatch` | Assigned counts depart from the equal split, so the arms may not be comparable. The bias this causes can be small while the arm is still invalid. | Publish the chi-square, p-value and flag, and set every difference against control to NULL for the experiment while it is flagged. | Flagged at p < 0.001 against an assumed equal split; the warehouse holds no registered allocation. At the 1,000-player CI scale the mismatch is present but not detectable (p about 0.03), so `clear` there does not mean absent. |
| `experiment_mid_test_config_change` | Two versions of one arm are different treatments, so pooling them mixes their effects. | Disclose, do not correct: publish `has_config_change` and the version columns by date. Outcomes stay pooled across versions. | Do not read a pooled arm figure as the effect of either version. For this incident `contained` means disclosed. |

Codes beginning `experiment_` concern the synthetic offer-page experiment described in the [experiment readout](../metrics/hybrid_subscription_experiment.md). The prefix keeps them apart from `post_subscription_exposure`, which concerns marketing-campaign exposure.

## Ownership and response

- Analytics Engineering owns detection logic, canonicalization, and dbt controls.
- Product Analytics owns metric exclusions and interpretation boundaries.
- Monetization Engineering owns webhook idempotency and transaction-to-grant identifiers.
- CRM owns exposure timing and experiment assignment quality.

Any failed containment test blocks publication. A material increase in affected rows requires source-owner investigation before the corresponding metric is used for a product decision.

## Analytical interpretation

Contained rows remain visible for auditability. Containment makes governed metrics internally consistent; it does not make observational subscriber-versus-control differences causal. Engagement lift and store cannibalization still require design-aware analysis and explicit uncertainty.
