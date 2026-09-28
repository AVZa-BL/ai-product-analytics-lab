# Live-strategy D7 retention decision memo

## Decision

Treat the post-update D7 decline as a monitored progression-friction risk, not as proof that the season update caused churn. Do not rebalance upgrade costs or rewards globally from this observational result. Restore a holdout-compatible, randomized upgrade-cost experiment and use governed robust-activity D7 retention as the primary outcome.

## Observed facts

The governed diagnostic covers install cohorts from **2026-01-01 through 2026-06-23**. It includes **491 eligible pre-update players** and **477 eligible post-update players**.

Robust-activity D7 retention moved from **22.00%** before the update to **18.03%** after it: an observed change of **-3.97 percentage points** (**-18.03% relative**). The stratified cohort-row bootstrap 95% interval for the difference is **[-9.10, +1.06] percentage points**, which includes zero, so the result is not statistically conclusive under this procedure.

Holding the pre-update acquisition-channel mix fixed gives a post-update rate of **19.76%**. The descriptive decomposition assigns **-1.74 percentage points** to acquisition mix and leaves a **-2.23 percentage-point within-channel association**. These components sum to the observed change apart from rounding.

On Android, the post-update completed-session definition is **7.49 percentage points lower** than robust activity. The cohort-level Spearman association between median upgrade attempts and D7 retention is **-0.050**. Progression-velocity association is not identifiable because the published cohort values have insufficient variation.

## Inference

Progression friction is an **unconfirmed hypothesis** worth testing, not a supported driver. The evidence does not identify the decline's cause. The confidence interval includes no change, the update was not randomized, acquisition mix shifted, and the remaining within-channel association can contain platform, country, configuration-version, and other cohort-composition changes.

The Android completed-session gap is measurement sensitivity, not evidence that Android players became less engaged. Missing session ends suppress a definition that requires completed sessions, while robust activity can still recognize canonical, post-install gameplay.

The near-zero upgrade-attempt correlation is an ecological cohort-level association. It neither rules progression friction in nor rules it out at player level.

## Assumptions and uncertainty

- The dataset is deterministic synthetic scenario data; the estimates demonstrate a governed diagnostic workflow rather than production commercial performance.
- Cohorts are D7-mature only when `eligible_d7_players > 0` under the governed observation cutoff.
- Mix standardization controls acquisition channel only. It does not control platform, country, configuration exposure, seasonality, or unobserved player quality.
- The bootstrap resamples aggregated cohort rows rather than individual players; its interval represents limited sampling uncertainty and does not correct confounding.
- Configuration timing and the acquisition-mix shift are observational confounders.
- Reconciled purchases are associated with their governed transaction records; no causal monetization effect is inferred here.
- The six contained incident classes are retained as known measurement context. Their existence does not imply that every reported estimate is biased by the same amount.
- The published figures are exact for the recorded execution platform only. A Linux/x86_64 run of the same commit, from byte-identical generated inputs, shifts the population by one player and the observed change from −3.97% to −3.19%. The Reproducibility section states the measured divergence in full.

## Data-quality qualification

The primary measure is robust-activity D7 retention from `mart_live_strategy__d7_diagnostic_inputs`. It is preferred to completed-session retention because it uses canonical, valid, post-install activity and is less sensitive to the known Android missing-session-end defect. Completed-session retention remains a named sensitivity check rather than being silently discarded.

All known incident classes are documented in the [live-strategy incident register](../../docs/incidents/live_strategy.md):

- [`duplicate_android_client_events`](../../docs/incidents/live_strategy.md#duplicate_android_client_events): canonical event selection prevents duplicate Android arrivals from multiplying activity.
- [`missing_android_session_ends`](../../docs/incidents/live_strategy.md#missing_android_session_ends): incomplete Android sessions can depress completed-session retention, motivating robust activity as the primary signal.
- [`purchase_refund_status_lag`](../../docs/incidents/live_strategy.md#purchase_refund_status_lag): governed purchase reconciliation prevents lagging status fields from overstating recognized revenue.
- [`events_before_install`](../../docs/incidents/live_strategy.md#events_before_install): pre-install events are excluded from valid gameplay and retention evidence.
- [`invalid_membership_interval`](../../docs/incidents/live_strategy.md#invalid_membership_interval): invalid alliance intervals are contained before daily membership expansion.
- [`ambiguous_intraday_configuration_join`](../../docs/incidents/live_strategy.md#ambiguous_intraday_configuration_join): exact timestamp, half-open configuration intervals prevent one event from receiving multiple configurations.

The incident controls were exercised by the scenario dbt build and targeted singular tests before this memo was authored. The notebook itself remains restricted to the governed diagnostic mart and does not independently query raw or staging relations.

## Recommended next actions

1. **Run a holdout-compatible upgrade-cost experiment.** Randomize eligible players before exposure; preserve an unchanged control; version the configuration; and keep assignment stable through the D7 window.
2. **Pre-register the decision rule.** Use robust-activity D7 retention as the primary outcome. Use completed-session D7 as an Android instrumentation sensitivity, plus upgrade attempts, progression velocity, payer conversion, and revenue as secondary diagnostics or guardrails.
3. **Stratify or block assignment.** Balance platform, country, acquisition channel, install cohort, and relevant configuration version so the experiment does not reproduce the observed mix problem.
4. **Repair session-end telemetry in parallel.** Alert on the missing-end rate and analyze completed-session retention only after the instrumentation contract is stable.
5. **Wait for maturity.** Make the product decision only after the pre-registered sample has completed its D7 observation window; report absolute effects with uncertainty rather than declaring a win from a point estimate.

## Reproducibility

- Input relation: `main_live_strategy.mart_live_strategy__d7_diagnostic_inputs`
- Results artifact: `reports/live_strategy/d7_retention_diagnostic_results.json`
- Executable analysis: `notebooks/live_strategy/01_d7_retention_diagnostic.py`
- Generated notebook: `notebooks/live_strategy/01_d7_retention_diagnostic.ipynb` (untracked local artifact; the results JSON is the published evidence)
- Execution timestamp: `2026-09-24T05:04:47.677706Z`
- Code version: `683ff9d581913949de6c5356bf43b743d4f7a8ea`
- Runtime: Python 3.12.14, pandas 2.3.3, DuckDB 1.5.5, NumPy 2.5.2
- Execution platform: macOS, arm64. The values above are platform-dependent; see below.
- Bootstrap: seed 42, 2,000 draws, stratified over governed cohort rows
- Metric definitions: [`docs/metrics/live_strategy.md`](../../docs/metrics/live_strategy.md)
- Incident context: [`docs/incidents/live_strategy.md`](../../docs/incidents/live_strategy.md)

### Reproducibility is exact within a platform, not across platforms

Re-running this analysis on the recorded platform reproduces every value above
exactly. Re-running it on Linux/x86_64 does not. The divergence was measured
directly and is stated here rather than left for a reader to discover:

| | macOS, arm64 (published) | Linux, x86_64 |
| --- | --- | --- |
| Post-update eligible players | 477 | 478 |
| Pre-update D7 retention | 0.219959 | 0.211813 |
| Post-update D7 retention | 0.180294 | 0.179916 |
| Observed D7 change | −0.039666 | −0.031896 |
| Bootstrap 95% CI | [−0.0910, +0.0106] | [−0.0810, +0.0169] |

The generated inputs are **not** the cause. The same seed produces byte-identical
Parquet on both platforms, verified by SHA-256 over `players.parquet`
(`6767331d224dc305`) and `sessions.parquet` (`097a4964e0bcf6c6`), with an identical
acquisition-channel mix of 498 organic, 352 paid social, 150 paid search. Identical
NumPy, pandas, pyarrow and DuckDB versions were also confirmed on both, and pinning
NumPy to the recorded 2.5.2 on Linux did not close the gap. The divergence therefore
arises downstream of generation, and which stage is responsible is not yet
established.

The qualitative finding is unaffected: D7 retention declines after the update by
roughly three to four percentage points, the acquisition-mix component explains
under half of it, and the bootstrap interval spans zero on both platforms. What is
not safe is quoting these figures to the sixth decimal without naming the platform.

Regenerate the runtime JSON and executed notebook from the repository root with:

```bash
./.venv/bin/python -m jupytext \
  --to notebook \
  --execute \
  notebooks/live_strategy/01_d7_retention_diagnostic.py \
  --output notebooks/live_strategy/01_d7_retention_diagnostic.ipynb
```
