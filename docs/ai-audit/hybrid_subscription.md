# AI audit: hybrid subscription engagement and cannibalization diagnostic

## Review scope and evidence authority

This audit separates proposed interpretation, executed evidence, and outstanding validation. The numerical authority is the [regenerated results JSON](../../reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json), published in results commit `9932fe2e947d9eb7062e3e68dde719ddb6dae15a`. Its executed source version is `632094ba0a1f1eb085cb7e416e1c85e6f4431159`, with execution timestamp `2026-09-10T21:14:23.916094Z`.

The [ten-KPI catalogue](../metrics/hybrid_subscription.md) and [dbt KPI metadata](../../game_analytics/models/hybrid_subscription/marts/kpi_schema.yml) define semantics. The JSON metadata identifies the governed inputs:

- `main_hybrid_subscription.mart_hybrid_subscription__matched_incrementality`
- `main_hybrid_subscription.mart_hybrid_subscription__engagement_lift_inputs`
- `main_hybrid_subscription.mart_hybrid_subscription__cannibalization_inputs`
- `main_hybrid_subscription.mart_hybrid_subscription__monthly_kpis`
- `main_hybrid_subscription.mart_hybrid_subscription__subscription_cohorts`
- `main_hybrid_subscription.mart_hybrid_subscription__data_quality_incidents`

The analysis module and notebook must use these governed diagnostic inputs, not raw/staging reads or independent pandas business metrics.

## Execution performed and limitations

The direct exact-source execution succeeded. The workflow materialized and verified branch source blobs, generated the documented deterministic synthetic fixture, rendered unchanged SQL with literal dbt ref/source substitutions in dependency order, and directly ran the [tracked notebook source](../../notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py). Pair counts and engagement/revenue aggregate controls reconciled before calculation.

The code-version path used an explicit remote-source SHA override, backed by verified source-file blobs; it was not a local `git rev-parse HEAD` equivalence claim. Local SQL reconstruction is not a claim that a full dbt build or the entire repository test suite ran in that environment.

Jupyter kernel execution and real-checkout HEAD equivalence remain owner-run validations. Jupytext execution first lacked nbconvert; a subsequent kernel attempt failed before kernel_info with an operation-not-permitted networking error. The permission failure was treated as a stop condition. Conversion alone produced an unexecuted local notebook; no executed-notebook claim is made. Generated notebooks and figures are untracked, not published evidence, and are not linked.

The owner must rerun the tracked source through a working Jupyter kernel in a real checkout and verify default `metadata.code_version == git rev-parse HEAD`. That rerun should preserve governed generation inputs and compare deterministic results; execution timestamps and package metadata need not be byte-identical.

## Accepted and corrected analytical decisions

| Review item | Evidence or contract | Outcome and correction |
| --- | --- | --- |
| Pair population and matching | JSON `population`, `metadata.filters`, and `metadata.pairing_rule` | Accepted deterministic greedy nearest-control matching without replacement, exact on prior_payer_status/platform/acquisition_channel. The ordered pre_session_count and player_id tie-breaks are binding. |
| Eligible index | Earliest incrementality-eligible exposure; subscriber first start strictly after index; controls have no observed start | Rejected fallback indexes for unexposed players and post-subscription exposure inclusion. Retain ineligible exposures in incident reporting. |
| Unmatched handling | matched_pair_count = 157; unmatched_subscriber_count = 123; unmatched_control_count = 0 | Exclude unmatched players from pair estimates but disclose counts; never pad, reuse, or silently drop population evidence. |
| Engagement causal claim | `results.engagement.engagement_difference_in_differences` = 3.337579617834395 | Rejected causal wording. Matching is observational and does not establish causality. |
| Standalone displacement as total value | Standalone difference = -17.627547169811322; subscription difference = 9.99; total difference = -7.637547169811319 | Corrected: standalone displacement is not total net value. Total cash includes subscription revenue, excludes reward-track products and non-cash grants, and is not profit or LTV. |
| Maturity and zero denominators | Global observation bounds for paired windows; all-members maturity for conversion/D30; NULL-on-zero rates | Rejected immature cohort rates, zero-filled undefined ratios, and treating global timestamp coverage as proof of individual telemetry completeness. |
| Experiment design | Governed exposure assignment precedes outcomes | Reject eventual-subscriber grouping as a randomized primary analysis. Recommend a pre-exposure randomized intent-to-treat experiment. |
| Raw data bypass or hiding incidents | Approved relations and governed incident containment | Refuse raw/staging analytical bypass and ad hoc DISTINCT that hides duplicate-webhook evidence. |

These outcomes record review decisions and automated evidence, not independent human domain-expert endorsement. Older unpaired figures and prior execution claims are superseded by the committed matched-pair results above.

## Trusted-agent evaluation

The [question suite](hybrid_subscription_questions.yaml) and [canonical answer fixtures](../../scripts/evaluation/hybrid_subscription_answers.json) cover all ten KPI definitions, pair provenance, eligible-exposure indexing, both unmatched counts, reward-track exclusion, NULL denominators, cohort maturity, observed numerical results, and causal/LTV/raw-bypass refusals. Definition cases carry grain, numerator, denominator, exclusions, source model, maturity, and interpretation boundary explicitly.

The [score report](../../reports/hybrid_subscription/agent_evaluation.json) is generated by the existing deterministic evaluator. It scores recorded answer metadata, numeric agreement, relation allowlists, uncertainty presence, and refusal flags; it does not semantically grade free-text definitions or certify a live agent. Companion tests enforce definition completeness, selected non-obvious boundaries, and agreement with committed JSON. Mutation tests verify rejection of wrong numeric results, unapproved provenance, and missing required refusals. Fixture latency/cost values are synthetic placeholders, not measurements of a live model. No autonomous-decision authorization follows from a passing fixture score.

## Final decision boundary

Whole-pair bootstrap intervals describe resampling variation conditional on selected matches, not confounding or rematching uncertainty. Self-selection and unverified parallel trends remain. The [memo](../../reports/hybrid_subscription/engagement_cannibalization_decision_memo.md) recommends withholding broad expansion pending a randomized test; it does not assert causal harm, real-product efficacy, profitability, or lifetime value.
