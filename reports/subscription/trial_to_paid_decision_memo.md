# Trial-to-paid conversion decision memo

## Executive Summary

- **Mature trial-to-paid conversion declined by 4.10 percentage points.** The seeded scenario produced 33 conversions from 104 mature pre-decline trials (31.73%) versus 21 from 76 post-decline trials (27.63%).
- **Acquisition-channel mix does not explain the decline.** Standardizing the post period to the pre-period channel mix yields 27.76%, leaving approximately 3.97 percentage points as a within-channel or otherwise unexplained decline.
- **Payment failures are not the leading explanation.** Failed-payment incidence fell from 5 of 104 pre-decline trials to 2 of 76 post-decline trials. Payment failure is a checkout outcome and must not be mislabeled as onboarding failure.
- **Do not claim causality.** The evidence is synthetic and observational. Repair activation instrumentation and test a reversible checkout/onboarding change before changing the product globally.

## Observed facts

The analysis covers synthetic signups generated from January 1 through June 29, 2026, using seed 42 and scale 1,000. It uses mature trial cohorts from the governed diagnostic mart and the three-day conversion definition. The analysis was prepared from code version `4d95492`; the executed notebook records the current commit SHA and execution timestamp.

Pre-decline mature conversion was 31.73% (33/104). Post-decline mature conversion was 27.63% (21/76), a decline of 4.10 percentage points. Holding the pre-decline acquisition-channel mix fixed produces a post rate of 27.76%. The resulting mix contribution is approximately -0.13 percentage points; approximately -3.97 percentage points remain within channels or unexplained by this decomposition.

The monthly-basic plan declined from 43.75% pre-period conversion to 26.32% post-period conversion. Annual-premium conversion increased from 21.43% to 28.95%. These plan cuts are descriptive and have limited sample sizes. The 2-day, 3-day, and 7-day conversion-window checks return the same aggregate rates because qualifying paid starts occur at scheduled trial end in the seeded data.

The quality audit records five duplicate webhook rows, six late cancellation rows, 60 users with missing campaign identifiers, 320 activation aliases requiring canonicalization, and 124 locally reported trial-end timestamps requiring timezone normalization. These records are retained and contained rather than silently removed.

## Inference

The aggregate decline is not primarily an acquisition-channel composition effect. The strongest visible heterogeneity is by plan, but plan assignment and cohort characteristics were not experimentally controlled, so the decomposition cannot identify a causal driver or reliably assign shares of the decline beyond the small channel-mix component.

Payment failures are unlikely to explain the decline because their observed incidence decreased post-period. Activation segmentation may reveal association with conversion, but activation is partly behavioral and therefore not a valid causal treatment without additional design.

## Assumptions and uncertainty

- The dataset is synthetic and designed to contain a decline; the estimates demonstrate analytical workflow, not real commercial performance.
- Cohort maturity is defined by the governed 21-day cutoff. Immature cohorts are excluded.
- The primary definition allows paid conversion through three days after scheduled trial end. Two-day and seven-day sensitivity results are shown in the notebook.
- Channel standardization controls only observed channel mix. It cannot control unobserved acquisition quality, creative mix, targeting, seasonality, or product exposure.
- Local-time trial ends are normalized upstream. Residual timezone errors could move boundary events between windows.
- Confidence intervals describe sampling uncertainty under a binomial approximation; they do not correct for confounding or prove causality.
- Segment estimates are not adjusted for multiple comparisons and should guide follow-up, not declare a winner.

## Recommendation

1. Repair measurement first: standardize the activation event contract at instrumentation time, monitor alias volume, and alert on unmapped activation names and local-time trial-end records.
2. Run one reversible, randomized checkout/onboarding experiment with stable eligibility, a pre-registered three-day conversion metric, payment-failure guardrails, and sufficient mature-cohort follow-up.
3. Keep plan and acquisition-channel splits as diagnostic cuts. Do not roll out a global change based on the observed plan difference alone.

## Further questions

- Did acquisition quality, creative, or targeting change within channels around April 19?
- Was plan exposure randomized or selected by user/product behavior?
- Which activation event definition is stable enough to use as a prospective experiment guardrail?
