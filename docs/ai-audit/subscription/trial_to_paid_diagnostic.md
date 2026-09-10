# AI audit: subscription trial-to-paid diagnostic

## Proposed work

The AI proposed a mature-cohort comparison of trial-to-paid conversion, followed by cuts for acquisition channel, campaign, activation segment, payment-failure status, and plan. It also proposed standardizing the post-period rate to the pre-period channel mix and testing 2-day, 3-day, and 7-day conversion windows.

## Human validation

The reviewer checked the `trial_to_paid_conversion` metric contract, confirmed that the governed mart contains mature cohorts only, and verified that numerators and denominators are summed before rates are calculated. The reviewer checked the trial-level sensitivity query at one row per `subscription_id` and ensured that payment records are tested with `exists` rather than joined in a way that multiplies trials.

The aggregate values were reconciled to 33/104 pre-decline conversions and 21/76 post-decline conversions. Channel-standardized post conversion was recomputed from pre-period channel weights and post-period channel rates. The quality-audit counts were checked against the one-row audit model.

## Rejected output

Rejected: “The onboarding change caused the trial-to-paid conversion loss.”

This statement exceeds the evidence. No randomized exposure or credible causal identification links an onboarding change to the post-period cohorts, and activation behavior may itself be affected by user intent.

## Correction

Corrected: “Mature trial-to-paid conversion is lower after the designed decline date. The decline remains after holding acquisition-channel mix fixed, while activation and plan cuts show associations that require a controlled experiment before causal interpretation.”

## Provenance

- Scenario: deterministic synthetic subscription data, seed 42, start date January 1, 2026, 180 days, scale 1,000.
- Source models: `mart_subscription__trial_conversion_diagnostic`, `mart_subscription__kpis_daily`, `fct_subscription__payments`, `int_subscription__quality_audit`, `int_subscription__trial_cohorts`, and `dim_subscription__users`.
- Notebook: `notebooks/subscription/trial_to_paid_diagnostic.ipynb`.
- Metric contracts: `docs/metrics/subscription/`.
- Incident record: `docs/incidents/subscription/2026-08-27-subscription-data-quality.md`.
- Run date: recorded dynamically as `execution_date` in the notebook.
- Code version: recorded dynamically as `code_version` in the notebook; memo prepared from `4d95492`.
- Reviewer: Alexander Zatey.
