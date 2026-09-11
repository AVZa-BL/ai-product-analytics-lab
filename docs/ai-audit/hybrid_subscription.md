# AI audit: hybrid subscription engagement and cannibalization diagnostic

## Review scope and evidence authority

This audit separates proposed interpretation, executed evidence, and validation boundaries. The numerical authority is the [regenerated results JSON](../../reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json), refreshed after the source repair and clean exact-snapshot validation. Its executed source version is `e45a19cf48a6b08f27f5c13c71c2d999857c194f`, with execution timestamp `2026-09-11T19:09:28.834708Z`.

The [ten-KPI catalogue](../metrics/hybrid_subscription.md) and [dbt KPI metadata](../../game_analytics/models/hybrid_subscription/marts/kpi_schema.yml) define semantics. The JSON metadata identifies the governed inputs:

- `main_hybrid_subscription.mart_hybrid_subscription__matched_incrementality`
- `main_hybrid_subscription.mart_hybrid_subscription__match_population_summary`
- `main_hybrid_subscription.mart_hybrid_subscription__engagement_lift_inputs`
- `main_hybrid_subscription.mart_hybrid_subscription__cannibalization_inputs`
- `main_hybrid_subscription.mart_hybrid_subscription__monthly_kpis`
- `main_hybrid_subscription.mart_hybrid_subscription__subscription_cohorts`
- `main_hybrid_subscription.mart_hybrid_subscription__data_quality_incidents`

The analysis module and notebook must use these governed diagnostic inputs, not raw/staging reads or independent pandas business metrics.

## Execution performed and limitations

The direct exact-source execution succeeded. A clean reconstruction generated the documented deterministic synthetic fixture at scale 1000, ran native dbt parse/build, and executed the [tracked notebook source](../../notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py) against the resulting governed DuckDB artifact. The [machine-readable validation record](../../reports/hybrid_subscription/native_validation.json) reports PASS=311 tests, SUCCESS=36 models, WARN=0, ERROR=0, SKIP=0, TOTAL=347. Pair counts, candidate/exclusion totals and engagement/revenue aggregate controls reconciled before calculation. UTC is enforced on dbt profiles and notebook connections, and date/fixed-window operations are explicitly UTC-safe.

The final artifact used the default local Git version path: `metadata.code_version` equals `git rev-parse HEAD`, and `metadata.code_version_source` is `local git HEAD`. Owner-run Jupyter kernel execution and real-checkout HEAD equivalence therefore supersede the earlier remote reconstruction and its explicit override. The recorded package versions and database hash describe the owner's native execution environment.

The executed notebook and figures remain local generated artifacts: they are untracked, are not published evidence, and are not linked. The committed JSON is the machine-readable evidence artifact; it retains the governed inputs, canonical counts, execution metadata, results, uncertainty and limitations.

## Accepted and corrected analytical decisions

| Review item | Evidence or contract | Outcome and correction |
| --- | --- | --- |
| Pair population and matching | JSON `population`, `metadata.filters`, and `metadata.pairing_rule` | Accepted deterministic greedy nearest-control matching without replacement, exact on prior_payer_status/platform/acquisition_channel. The ordered pre_session_count and player_id tie-breaks are binding. |
| Eligible index | Earliest incrementality-eligible exposure; subscriber first start strictly after index; controls have no observed start | Rejected fallback indexes for unexposed players and post-subscription exposure inclusion. Retain ineligible exposures in incident reporting. |
| Unmatched handling | matched_pair_count = 157; unmatched_subscriber_count = 123; unmatched_control_count = 0 | Exclude unmatched players from pair estimates but disclose counts; never pad, reuse, or silently drop population evidence. |
| Engagement causal claim | `engagement_difference_in_differences = 3.337579617834395` | Rejected causal wording. Matching is observational and does not establish causality. |
| Standalone displacement as total value | `standalone_store_difference_in_differences = -17.627547169811322`; `subscription_difference_in_differences = 9.99`; `total_revenue_difference_in_differences = -7.637547169811319` | Corrected: standalone displacement is not total net value. Total cash includes subscription revenue, excludes reward-track products and non-cash grants, and is not profit or LTV. |
| Maturity and zero denominators | Every paired-outcome source covers both windows and passes post endpoint plus maximum observed ingestion lag; all-members maturity for conversion/D30; NULL-on-zero rates | Rejected immature rates, missing/stale source maturity and zero-filled undefined ratios. Empirical ingestion allowances are not operational completeness SLAs or proof of individual telemetry completeness. An independent one-row summary preserves valid empty populations and per-reason exclusions; absent estimates remain unavailable. |
| Experiment design | Governed exposure assignment precedes outcomes | Reject eventual-subscriber grouping as a randomized primary analysis. Recommend a pre-exposure randomized intent-to-treat experiment. |
| Raw data bypass or hiding incidents | Approved relations and governed incident containment | Refuse raw/staging analytical bypass and ad hoc DISTINCT that hides duplicate-webhook evidence. |

These outcomes record review decisions and automated evidence, not independent human domain-expert endorsement. Older unpaired figures and prior execution claims are superseded by the committed matched-pair results above.

## Trusted-agent evaluation

The [question suite](hybrid_subscription_questions.yaml) and [canonical answer fixtures](../../scripts/evaluation/hybrid_subscription_answers.json) cover all ten KPI definitions, pair provenance, eligible-exposure indexing, both unmatched counts, reward-track exclusion, NULL denominators, per-source ingestion maturity, zero-pair/zero-prior-payer handling, cohort maturity, observed numerical results, and causal/LTV/raw-bypass refusals. Definition cases carry grain, numerator, denominator, exclusions, source model, maturity, and interpretation boundary explicitly.

The [score report](../../reports/hybrid_subscription/agent_evaluation.json) is generated by the existing deterministic evaluator. It scores recorded answer metadata, numeric agreement, relation allowlists, uncertainty presence, and refusal flags; it does not semantically grade free-text definitions or certify a live agent. Companion tests enforce definition completeness, selected non-obvious boundaries, and agreement with committed JSON. Mutation tests verify rejection of wrong numeric results, unapproved provenance, and missing required refusals. Fixture latency/cost values are synthetic placeholders, not measurements of a live model. No autonomous-decision authorization follows from a passing fixture score.

## Final decision boundary

Whole-pair bootstrap intervals describe resampling variation conditional on selected matches, not confounding or rematching uncertainty. Self-selection and unverified parallel trends remain. The [memo](../../reports/hybrid_subscription/engagement_cannibalization_decision_memo.md) recommends withholding broad expansion pending a randomized test; it does not assert causal harm, real-product efficacy, profitability, or lifetime value.
