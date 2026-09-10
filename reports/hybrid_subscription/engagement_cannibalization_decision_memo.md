# Engagement rose, but current subscription economics do not justify expansion

## Decision

Do not use the current observational result to expand the subscription offer globally. The engagement signal is favorable, but the measured prior-payer total-net-revenue association remains materially negative after subscription revenue is included. Preserve a holdout-compatible population and make the next rollout decision from a pre-registered randomized experiment.

This is a provisional product decision under uncertainty. The analysis **does not establish causality**: subscriber status is self-selected, and the parallel-trends assumption required for a causal difference-in-differences interpretation has not been demonstrated.

## Executive summary

- Across 200 paired players, mean 28-day engagement increased by **+1.85 sessions per player**. Subscribers increased by **+2.97**, compared with **+1.09** among non-subscribers.
- Among 70 prior payers, the standalone-store difference-in-differences was **-$24.66 per player**. Subscription revenue recovered **+$9.99**, leaving a total-net-revenue difference-in-differences of **-$14.67 per player**.
- The player-cluster bootstrap 95% interval for the total-net-revenue estimate was **[-$19.56, -$9.82]**. This interval measures sampling variation in the synthetic population; it does not remove selection bias or validate causality.
- Engagement improvement is therefore insufficient evidence for expansion. The commercial decision should be governed by randomized total net revenue, with engagement as a secondary outcome and store displacement as a guardrail.

## Observed facts

The governed player-period fact contains **200 players** with complete pre and post 28-day windows. The prior-payer revenue population contains **70 players**.

Mean sessions per paired player moved from **6.685** before the index to **8.530** after it, a change of **+1.845 sessions** (**+27.60% relative**). The subscriber group moved from **8.000** to **10.975** sessions per player; the non-subscriber group moved from **5.808** to **6.900**. The descriptive difference between those changes is **+1.883 sessions per player**.

For prior payers, the subscriber standalone-store change was **-$21.00 per player**, while the non-subscriber change was **+$3.66**. Their difference-in-differences was **-$24.66**, with a bootstrap 95% interval of **[-$29.55, -$19.81]**.

Subscription revenue contributed a **+$9.99 per-player** difference-in-differences. That did not offset the standalone-store movement: the total-net-revenue difference-in-differences was **-$14.67 per player**, with a bootstrap 95% interval of **[-$19.56, -$9.82]**.

The notebook reconciled the player-level facts to both published diagnostic marts before calculating results. The complete hybrid dbt selector build passed **176 of 176** nodes and tests before notebook execution.

## Interpretation

The observed engagement movement is directionally favorable. It supports testing whether the offer can create incremental engagement, but it does not show that the subscription produced the increase. Subscribers were already more engaged in the pre period, and their eventual subscriber status is a post-index classification.

The standalone-store result is evidence of a serious displacement risk, not proof that the subscription caused cannibalization. More importantly for the rollout decision, the subscription-revenue contribution did not restore total 28-day net revenue in this comparison. Store cannibalization and total value remain separate metrics: the former diagnoses substitution; the latter determines whether the measured substitution is economically offset.

The negative total-value interval makes immediate expansion a poor risk-adjusted choice even though causality is unresolved. Randomization could weaken, remove, or strengthen the estimate; until then, broader exposure would scale an unquantified downside.

## Assumptions and uncertainty

- The data is deterministic and synthetic. The figures demonstrate a governed analytical workflow rather than real commercial performance.
- Pre and post periods are complete, half-open 28-day windows, and only paired players are included.
- Revenue is recognized from canonical transactions net of linked refunds; currency grants are non-cash and excluded from revenue.
- The difference-in-differences calculation assumes the non-subscriber movement is a useful counterfactual. Parallel trends were not established, so the estimate remains descriptive.
- Subscriber self-selection, acquisition mix, platform, prior payer behavior, and unobserved player quality can confound the comparison.
- Bootstrap intervals resample players within subscriber strata. They quantify sampling variation but not confounding, measurement bias, or model-specification risk.
- The observation window excludes renewal value, longer-term retention, profitability, and lifetime value.

## Data-quality qualification

The analysis reads only governed relations, led by `main_hybrid_subscription.fct_hybrid_subscription__player_behavior_28d`, and reconciles them to `mart_hybrid_subscription__engagement_lift_inputs` and `mart_hybrid_subscription__cannibalization_inputs`.

The governed incident mart reports four detected-and-contained issues:

- `duplicate_store_webhook`: **11 rows**; deterministic canonicalization prevents duplicated revenue.
- `missing_subscription_grant_link`: **6 rows**; unreconciled subscription currency is set to zero.
- `post_subscription_exposure`: **4 rows**; these exposures are excluded from incrementality analysis.
- `cancellation_pending_expiry`: **10 rows**; access is preserved through contractual period end.

`mixed_timestamp_mismatch` reports **0 affected rows** and is correctly classified as `clear`. Incident containment protects the governed measures but does not turn the observational comparison into an experiment.

## Recommended experiment

1. **Randomize before exposure.** Assign incrementality-eligible players to offer and control before any subscription marketing exposure. Keep assignment stable through the outcome window.
2. **Use player-level intent-to-treat.** Analyze every assigned player in the original arm, regardless of subscription conversion. Do not segment the primary estimate by eventual subscriber status.
3. **Pre-register the primary decision metric.** Use 28-day total net revenue per eligible player. Require its lower confidence bound to exceed a business-approved non-inferiority margin before expansion.
4. **Keep engagement secondary.** Measure sessions per player and live-event participation, but do not trade away material total value solely for engagement without an explicit, approved valuation model.
5. **Enforce guardrails.** Monitor standalone-store net revenue, refund-adjusted subscription revenue, entitlement correctness, grant reconciliation, and incrementality-eligible exposure rate.
6. **Balance important strata.** Block or stratify by prior-payer status, platform, and acquisition channel. Report heterogeneous effects without replacing the pre-registered overall estimate.
7. **Wait for maturity.** Decide only after every included player completes the 28-day window and the documented refund and grant-ingestion allowances have elapsed.

## Reproducibility

- Player-level input: `main_hybrid_subscription.fct_hybrid_subscription__player_behavior_28d`
- Engagement control: `main_hybrid_subscription.mart_hybrid_subscription__engagement_lift_inputs`
- Revenue control: `main_hybrid_subscription.mart_hybrid_subscription__cannibalization_inputs`
- Incident context: `main_hybrid_subscription.mart_hybrid_subscription__data_quality_incidents`
- Results artifact: `reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json`
- Executable analysis: `notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py`
- Generated notebook: `notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.ipynb`
- Execution timestamp: `2026-09-10T15:47:28.570410Z`
- Code version: `f5e3288a3c1a519c2d5716de0d61f091020a1320`
- Runtime: Python 3.12.14, pandas 2.3.3, DuckDB 1.5.5, NumPy 2.5.3
- Bootstrap: seed 42, 2,000 player-cluster draws stratified by subscriber status
- Metric definitions: [`docs/metrics/hybrid_subscription.md`](../../docs/metrics/hybrid_subscription.md)
- Incident register: [`docs/incidents/hybrid_subscription.md`](../../docs/incidents/hybrid_subscription.md)

Regenerate the results and executed notebook from the repository root with:

```bash
./.venv/bin/python -m jupytext \
  --to notebook \
  --execute \
  notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py \
  --output notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.ipynb
```
