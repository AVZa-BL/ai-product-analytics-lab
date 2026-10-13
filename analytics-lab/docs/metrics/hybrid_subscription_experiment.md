# Hybrid Subscription offer-page experiment readout

This is a **synthetic validation fixture**, not one of the ten approved KPIs in the [metric catalogue](hybrid_subscription.md). It gives the Referee results reviewer (milestone 4) a three-arm offer-page experiment with known problems planted at stated sizes, so the reviewer can be judged on finding those problems and nothing else.

The models are **descriptive only**. They publish counts, means, rates and point differences, with no p-values, intervals or verdicts for effects. The one test they run is the sample-ratio check of assigned counts, against an assumed equal split that the reviewer replaces with the registered allocation. Inference about effects belongs to the reviewer, so that SQL and the reviewer are not two sources of truth for them. A difference in the readout is not evidence of an effect.

All timestamps are UTC. The raw tables and the planted sizes are described in the [raw contract](../architecture/hybrid_subscription_raw_contract.md#synthetic-offer-page-experiment).

## Models and grain

| Model | Grain | Role |
| --- | --- | --- |
| `int_hybrid_subscription__experiment_first_exposure` | one row per assigned player | First-touch exposure, repeat-exposure count, and whether the first exposure came after the first purchase |
| `int_hybrid_subscription__experiment_eligible_population` | one row per assigned player | Segment attributes, a 28-day pre-assignment session count, and an eligibility verdict with a reason; excluded players are kept |
| `int_hybrid_subscription__experiment_srm` | one row per experiment | Chi-square sample-ratio check of assigned players against an equal split |
| `mart_hybrid_subscription__experiment_arm_daily` | experiment, arm, UTC assignment date | Daily counts, eligible-only outcome sums, means and rates |
| `mart_hybrid_subscription__experiment_readout` | experiment and arm | Arm totals, the sample-ratio flag, the config-change flag, concentration, and differences against control |

## Shared rules

- **Assigned versus eligible.** Assigned players are everyone with an assignment row. Eligible players are assigned players who were exposed and whose first exposure was not after their first purchase. Outcome figures cover eligible players only; counts of assigned and excluded players are always published beside them.
- **Allocation is an assumption.** The sample-ratio check compares assigned counts with an equal split across `control`, `variant_b` and `variant_c`. The warehouse holds no pre-registered allocation; the results reviewer will take it from the experiment spec.
- **Ratios.** Means and rates are NULL on a zero denominator, never zero. Reaggregate from the published sums and counts, not from averages of daily rates.
- **Outcome window.** Outcomes cover the seven days after assignment (`sessions_7d`, `purchases_7d`, `revenue_usd_7d`).
- **Pre-assignment window.** The 28-day session count uses 672 elapsed hours, half-open at the assignment time, so it does not move across daylight-saving changes. The dbt profile pins the session time zone to UTC, so no test can tell this apart from 28 calendar days.

## Assigned share and sample-ratio check

**Source model:** `int_hybrid_subscription__experiment_srm`; `mart_hybrid_subscription__experiment_readout`

**Grain:** One row per experiment for the statistic; the experiment-level value is repeated on each arm row of the readout.

**Numerator:** Chi-square of assigned players per arm against an equal split. With three arms the statistic has 2 degrees of freedom, so the p-value is exactly `exp(-chi_square / 2)`.

**Denominator:** Expected players per arm, the experiment's assigned players divided by three.

**Exclusions:** None. The check runs on every assigned player, eligible or not, because exclusions happen after assignment.

**Maturity:** None; assignment counts do not mature.

**Interpretation boundary:** Flagged when p is below 0.001. A flagged experiment has an invalid arm comparison, and the readout publishes no difference against control for any of its arms. The p-value is not summed or averaged across arm rows. The check is written for exactly `control`, `variant_b` and `variant_c`, because the exact formula holds only for 2 degrees of freedom. `arm_count` is 3 by construction, so its test fails only if the model's arm list is edited. Data with fewer arms is zero-filled and scored against the same three-way split, which is not a valid check for that design.

## Outcome means per eligible player

**Source model:** `mart_hybrid_subscription__experiment_arm_daily`; `mart_hybrid_subscription__experiment_readout`

**Grain:** Experiment, arm and UTC assignment date (arm-daily); experiment and arm (readout).

**Numerator:** Sum of `sessions_7d`, count of players with `purchases_7d > 0`, and sum of `revenue_usd_7d`, over eligible players.

**Denominator:** Eligible players in the row.

**Exclusions:** Players who were never exposed, and players first exposed after their first purchase.

**Maturity:** Each outcome is the seven days after that player's assignment.

**Interpretation boundary:** Excluding players who were exposed after buying removes some buyers from the denominator, a selection on a post-assignment event. The means describe the eligible players only.

## Revenue concentration

**Source model:** `mart_hybrid_subscription__experiment_readout`

**Grain:** Experiment and arm.

**Numerator:** Revenue of the arm's top 1% of eligible players, taken as the ceiling of 1% of the arm's eligible players (at least one player), computed in integers so rounding cannot move it.

**Denominator:** Total revenue of the arm's eligible players; NULL when the arm has none.

**Exclusions:** Ineligible players.

**Maturity:** Seven-day outcomes.

**Interpretation boundary:** A description of how skewed revenue is, not a test. With few players the top 1% is a handful of people and the figure is noisy; at the 1,000-player CI scale it is two players per arm.

## Difference against control

**Source model:** `mart_hybrid_subscription__experiment_readout`

**Grain:** Experiment and arm.

**Numerator:** The arm's mean sessions, purchase rate or mean revenue minus the control arm's.

**Denominator:** Not applicable; a difference of two per-player figures.

**Exclusions:** NULL for the control arm, and NULL for every arm of an experiment whose sample-ratio check is flagged.

**Maturity:** Seven-day outcomes.

**Interpretation boundary:** A point difference with no uncertainty. Pooled across configuration versions when `has_config_change` is true.

## Configuration change

**Source model:** `mart_hybrid_subscription__experiment_readout`; `mart_hybrid_subscription__experiment_arm_daily`

**Grain:** Experiment and arm (flag); experiment, arm and date (version range).

**Numerator:** True when assigned players in the arm carry more than one `arm_config_version`.

**Denominator:** Not applicable.

**Exclusions:** None; outcomes are not split by version.

**Maturity:** Not applicable.

**Interpretation boundary:** A flag, not a correction. The two versions are different treatments, and the readout does not separate them.

## Planted problems and where each shows

Figures are for seed 42 at the 5,000-player reference scale unless stated, measured on the committed generator. Two populations appear. **All assigned players** is what the generator produces, including the 198 players excluded for late exposure. **Eligible players** is what `mart_hybrid_subscription__experiment_arm_daily` and `mart_hybrid_subscription__experiment_readout` cover, so it is the figure a reader of the marts sees. A test recomputes the figures in this table, the CI-scale count in the revenue-concentration section and the correlation bound in the last section from the generator, for both populations, and requires their exact text to appear; the standard error and the correlation bound it checks as ranges. Statements about other seeds are not recomputed.

| Problem | Where it shows | Measured |
| --- | --- | --- |
| Sample-ratio mismatch in `variant_c` | `assigned_share`, `experiment_srm_p_value`, `is_srm_flagged`; `assigned_players` by date in arm-daily | Arms 997 / 1,046 / 781 of 2,824 assigned players, p = 6.7e-10, flagged. At the 1,000-player CI scale (561 assigned players) p = 0.031, not flagged. Across seeds 1 to 8 the largest p was 5.9e-05, below the alarm level in every one |
| Exposure after purchase | `excluded_players`; `exclusion_reason = 'exposed_after_first_purchase'` | 198 of 2,824 assigned players (7.0%), which is 35.4% of the 559 purchasers. At the CI scale, 42 of 561 (7.5%) |
| Heavy-tailed revenue | `revenue_top1pct_share` | All assigned players: the top 1% of players hold 46.8% of revenue, and revenue per player has excess kurtosis 312. Eligible players, per arm (`control` / `variant_b` / `variant_c`): the top 1% hold 54.6% / 51.2% / 61.7% of the arm's revenue |
| Novelty in `variant_b` | `mean_sessions_7d` by assignment date in arm-daily | `variant_b` minus control sessions by assignment week: +1.52, +0.64, -0.17 over all assigned players, each with a standard error of about 0.25, and +1.64, +0.64, -0.07 over eligible players, which is what arm-daily summed by assignment week gives. The week-3 value is within one standard error of zero in both, so the reversal to zero is visible but a sign change is not established |
| Configuration change in `variant_b` | `has_config_change`; in arm-daily the version columns step from 1 to 2 between consecutive dates | 445 of the 1,046 `variant_b` players carry version 2 |
| Bias from the bucketing bug | arm-daily means for `variant_c` after the bug starts | Among players assigned after the bug starts, `variant_c` minus control sessions is +0.56 for seed 42 over all assigned players and +0.58 over eligible players, and +0.10 to +0.60 (mean +0.34) across seeds 1 to 8 over all assigned players. Averaged over every player assigned, including those before the bug starts, it is typically smaller. Much smaller than the mismatch itself, which is what invalidates the arm |

The sample-ratio flag and the exposure exclusion are contained by the models. Novelty, heavy tails and the configuration change are shown but not contained; finding them is the reviewer's job.

## What this readout is not

- **Not an effect estimate.** There is no uncertainty, so no difference here supports a decision.
- **Not a CUPED fixture.** The 28-day pre-assignment session count carried on the eligible-population model (which holds all assigned players) has an absolute correlation below 0.03 with `sessions_7d`, with purchases and with revenue at the reference scale, because outcomes are generated independently of the `sessions` table. It carries no information about outcomes here, so variance reduction cannot be demonstrated with it. Making it useful would change the raw contract, as a separate change.
- **Not registered.** No pre-registered spec exists for this experiment; the reviewer receives its own.
- **Synthetic.** The planted sizes were tuned over a few seeds; a different seed can move a figure across a threshold.
