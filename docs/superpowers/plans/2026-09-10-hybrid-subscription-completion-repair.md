# Hybrid Subscription Completion Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unmatched, subscription-indexed Hybrid Subscription diagnostic with an eligible-exposure-indexed matched analysis and publish the complete governed KPI surface required by the repository design.

**Architecture:** Governed canonical facts feed an eligible-exposure population, mature player-period behavior, and deterministic one-to-one nearest-control matching. Pair-level incrementality, cohort, daily, and monthly marts publish recomputable numerators and denominators; Python reads only those governed relations, validates them, and produces a deterministic evidence artifact with explicit observational limits.

**Tech Stack:** dbt Core 1.12.3, dbt-duckdb 1.11.0, DuckDB SQL, Python 3.12, pandas, NumPy, pytest, Ruff, Jupytext.

**Spec:** `docs/superpowers/specs/2026-09-10-hybrid-subscription-completion-repair-design.md`

## Global Constraints

- Index diagnostic players at their first incrementality-eligible marketing exposure.
- Match one subscriber to one non-subscriber without replacement on exact prior-payer status, platform, and acquisition channel, then nearest pre-index session count with stable player-ID tie-breaking.
- Use half-open 28-day windows `[index - 28 days, index)` and `[index, index + 28 days)` and publish only mature outcomes.
- Standalone-store revenue excludes both `subscription` and `reward_track`; total net revenue is eligible standalone-store plus subscription net revenue.
- Zero denominators yield `null`, never zero.
- Bootstrap resampling is at matched-pair grain with seed `42` and `2_000` draws.
- Results remain observational and must not be described as causal or as lifetime-value estimates.
- Commit the executable `.py` notebook and deterministic results JSON; keep generated `.ipynb` and figures untracked.

## File structure

| Responsibility | Files |
| --- | --- |
| Canonical activity/subscriber facts | Create `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__sessions.sql`, `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__subscriber_daily.sql`; modify `game_analytics/models/hybrid_subscription/marts/schema.yml` |
| Eligible population and mature behavior | Modify `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__analysis_population.sql`, `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__player_28d_behavior.sql`, `game_analytics/models/hybrid_subscription/intermediate/schema.yml`, `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__player_behavior_28d.sql` |
| Deterministic matching | Create `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__matched_pairs.sql`; modify intermediate schema |
| Pair-level published analysis | Create `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__matched_incrementality.sql`; modify engagement/cannibalization input marts and KPI schema |
| Cohort and monthly KPI layer | Create `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__subscription_cohorts.sql`, `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__monthly_kpis.sql`; modify daily KPI mart and KPI schema |
| Executable dbt invariants | Create focused singular tests under `game_analytics/tests/hybrid_subscription/` |
| Python calculations and notebook | Modify `src/analytics_lab/analysis/hybrid_subscription_diagnostic.py`, `tests/analysis/test_hybrid_subscription_diagnostic.py`, `notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py` |
| Contracts, docs, evaluation, evidence | Modify dbt contract tests, metric catalogue, memo, AI audit, question/answer catalogues, evaluation test, README; commit regenerated JSON/evaluation outputs |

---

### Task 1: Lock the expanded dbt surface with failing contract tests

**Files:**
- Modify: `tests/dbt/test_hybrid_subscription_marts_contract.py`
- Modify: `tests/dbt/test_hybrid_subscription_intermediate_contract.py`
- Modify: `tests/dbt/test_hybrid_subscription_kpi_marts_contract.py`

**Interfaces:**
- Consumes: current model directories and YAML contracts.
- Produces: exact required model and singular-test names used by every later task.

- [ ] **Step 1: Expand the expected model sets**

Add the canonical facts to `EXPECTED_MODELS` in the marts contract:

```python
"fct_hybrid_subscription__sessions",
"fct_hybrid_subscription__subscriber_daily",
```

Add the matching model to the intermediate contract:

```python
"int_hybrid_subscription__matched_pairs",
```

Replace the KPI contract set with:

```python
EXPECTED_MODELS = {
    "mart_hybrid_subscription__daily_kpis",
    "mart_hybrid_subscription__monthly_kpis",
    "mart_hybrid_subscription__subscription_cohorts",
    "mart_hybrid_subscription__matched_incrementality",
    "mart_hybrid_subscription__engagement_lift_inputs",
    "mart_hybrid_subscription__cannibalization_inputs",
}
EXPECTED_TESTS = {
    "assert_hybrid_analysis_population_eligible.sql",
    "assert_hybrid_behavior_windows_complete.sql",
    "assert_hybrid_matched_pairs_valid.sql",
    "assert_hybrid_matched_population_reconciles.sql",
    "assert_hybrid_reward_track_excluded.sql",
    "assert_hybrid_kpis_reconcile.sql",
    "assert_hybrid_zero_denominators_are_null.sql",
    "assert_hybrid_cohort_maturity.sql",
}
```

- [ ] **Step 2: Run the three contract modules and verify they fail for missing resources**

Run:

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/dbt/test_hybrid_subscription_marts_contract.py \
  tests/dbt/test_hybrid_subscription_intermediate_contract.py \
  tests/dbt/test_hybrid_subscription_kpi_marts_contract.py -v
```

Expected: FAIL showing the new facts, matching model, KPI marts, and singular tests are absent.

- [ ] **Step 3: Commit only the failing contract tests**

```bash
git add tests/dbt/test_hybrid_subscription_marts_contract.py \
  tests/dbt/test_hybrid_subscription_intermediate_contract.py \
  tests/dbt/test_hybrid_subscription_kpi_marts_contract.py
git commit -m "test: require complete hybrid subscription analytics surface"
```

### Task 2: Canonicalize sessions, subscriber days, and product revenue

**Files:**
- Create: `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__sessions.sql`
- Create: `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__subscriber_daily.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__store_transactions.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/schema.yml`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_reward_track_excluded.sql`

**Interfaces:**
- Consumes: `stg_hybrid_subscription__sessions`, `fct_hybrid_subscription__subscription_entitlements`, `fct_hybrid_subscription__store_transactions`, and `dim_dates`.
- Produces: canonical session rows; player-date entitlement rows; transaction flags `is_subscription_revenue`, `is_standalone_store_revenue`, and `is_reward_track_revenue`.

- [ ] **Step 1: Write the reward-track exclusion test**

```sql
with invalid as (
    select transaction_id
    from {{ ref('fct_hybrid_subscription__store_transactions') }}
    where product_type = 'reward_track'
      and is_standalone_store_revenue
)
select * from invalid
```

Run `cd game_analytics && dbt test --select assert_hybrid_reward_track_excluded`; expect a compilation failure because the classification field does not exist.

- [ ] **Step 2: Publish canonical sessions**

Create the fact as a strict projection of the staged unique session grain:

```sql
select
    session_id,
    player_id,
    started_at_utc,
    ended_at_utc,
    duration_seconds,
    platform,
    scenario_run_id
from {{ ref('stg_hybrid_subscription__sessions') }}
```

Document `session_id` as unique/not-null and `player_id` as a relationship to `dim_hybrid_subscription__players`.

- [ ] **Step 3: Publish end-of-day subscriber state**

Use the date spine and half-open entitlement intervals:

```sql
select
    entitlement.player_id || '__' || cast(date.date_day as varchar) as player_date_id,
    entitlement.player_id,
    date.date_day as metric_date,
    entitlement.subscription_id,
    entitlement.entitlement_start_at_utc,
    entitlement.entitlement_end_at_utc
from {{ ref('fct_hybrid_subscription__subscription_entitlements') }} entitlement
join {{ ref('dim_dates') }} date
  on date.date_day >= cast(entitlement.entitlement_start_at_utc as date)
 and date.date_day < cast(entitlement.entitlement_end_at_utc as date)
```

Document `player_date_id` as unique/not-null and test the player relationship.

- [ ] **Step 4: Add mutually exclusive transaction classifications**

Add these expressions to the store fact:

```sql
product_type = 'subscription' as is_subscription_revenue,
product_type not in ('subscription', 'reward_track') as is_standalone_store_revenue,
product_type = 'reward_track' as is_reward_track_revenue
```

Keep `recognized_net_revenue_usd` unchanged so incident and source reconciliations still expose every canonical cash transaction.

- [ ] **Step 5: Run focused dbt tests**

```bash
cd game_analytics
dbt build --select \
  fct_hybrid_subscription__sessions \
  fct_hybrid_subscription__subscriber_daily \
  fct_hybrid_subscription__store_transactions \
  assert_hybrid_reward_track_excluded
```

Expected: all selected models and tests PASS.

- [ ] **Step 6: Commit the canonical facts**

```bash
git add game_analytics/models/hybrid_subscription/marts \
  game_analytics/tests/hybrid_subscription/assert_hybrid_reward_track_excluded.sql
git commit -m "feat: govern hybrid activity and revenue classification"
```

### Task 3: Rebuild the eligible-exposure population and mature behavior windows

**Files:**
- Modify: `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__analysis_population.sql`
- Modify: `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__player_28d_behavior.sql`
- Modify: `game_analytics/models/hybrid_subscription/intermediate/schema.yml`
- Modify: `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__player_behavior_28d.sql`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_analysis_population_eligible.sql`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_behavior_windows_complete.sql`

**Interfaces:**
- Consumes: first eligible exposure, first subscription start, canonical sessions, canonical store transactions, LiveOps participation.
- Produces: `index_at_utc`, `is_population_eligible`, `exclusion_reason`, maturity flags, and corrected pre/post player metrics.

- [ ] **Step 1: Write population and maturity failures first**

Population test:

```sql
select *
from {{ ref('int_hybrid_subscription__analysis_population') }}
where is_population_eligible
  and (
    eligible_exposure_at_utc is null
    or index_at_utc != eligible_exposure_at_utc
    or (is_subscriber and first_subscription_at_utc <= index_at_utc)
  )
```

Window test:

```sql
select player_id
from {{ ref('int_hybrid_subscription__player_28d_behavior') }}
group by player_id
having count(*) != 2
   or count(distinct analysis_period) != 2
   or not bool_and(is_window_mature)
```

Run both tests; expect compilation failures for the new contract fields.

- [ ] **Step 2: Replace the index logic**

Set `index_at_utc = eligible_exposure_at_utc` for every candidate. Derive:

```sql
case
  when eligible_exposure_at_utc is null then 'no_eligible_exposure'
  when first_subscription_at_utc is not null
   and first_subscription_at_utc <= eligible_exposure_at_utc
    then 'subscription_not_after_exposure'
  when eligible_exposure_at_utc - interval '28 days' < observation_start_at_utc
    then 'immature_pre_window'
  when eligible_exposure_at_utc + interval '28 days' > observation_end_at_utc
    then 'immature_post_window'
  else null
end as exclusion_reason
```

Derive `is_population_eligible` as `exclusion_reason is null`. Calculate observation bounds from the minimum and maximum timestamps published by the governed session, transaction, and participation inputs rather than the wall clock.

- [ ] **Step 3: Filter behavior to eligible, mature players and corrected cash categories**

Start `population_periods` with `where population.is_population_eligible`. Aggregate sessions from `fct_hybrid_subscription__sessions`, transactions from `fct_hybrid_subscription__store_transactions`, and use:

```sql
sum(recognized_net_revenue_usd) filter (where is_subscription_revenue)
  as subscription_net_revenue_usd,
sum(recognized_net_revenue_usd) filter (where is_standalone_store_revenue)
  as standalone_store_net_revenue_usd,
sum(recognized_net_revenue_usd) filter (where is_reward_track_revenue)
  as reward_track_net_revenue_usd
```

Set `total_net_revenue_usd` to standalone plus subscription only. Add `discounted_standalone_transaction_count` and `standalone_transaction_count` for later utilization metrics.

- [ ] **Step 4: Expose the contract through the fact and YAML**

Project `index_at_utc`, `eligible_exposure_at_utc`, `is_population_eligible`, `is_window_mature`, reward-track revenue, and both standalone transaction counts through `fct_hybrid_subscription__player_behavior_28d`. Update descriptions and column tests in both schemas.

- [ ] **Step 5: Build and test the repaired population slice**

```bash
cd game_analytics
dbt build --select \
  int_hybrid_subscription__analysis_population+ \
  assert_hybrid_analysis_population_eligible \
  assert_hybrid_behavior_windows_complete \
  assert_hybrid_reward_track_excluded
```

Expected: PASS, with exactly two mature rows per eligible player.

- [ ] **Step 6: Commit the population repair**

```bash
git add game_analytics/models/hybrid_subscription/intermediate \
  game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__player_behavior_28d.sql \
  game_analytics/tests/hybrid_subscription/assert_hybrid_analysis_population_eligible.sql \
  game_analytics/tests/hybrid_subscription/assert_hybrid_behavior_windows_complete.sql
git commit -m "fix: index hybrid analysis at eligible exposure"
```

### Task 4: Implement deterministic one-to-one nearest-control matching

**Files:**
- Create: `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__matched_pairs.sql`
- Modify: `game_analytics/models/hybrid_subscription/intermediate/schema.yml`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_matched_pairs_valid.sql`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_matched_population_reconciles.sql`

**Interfaces:**
- Consumes: eligible pre-period rows from `int_hybrid_subscription__player_28d_behavior`.
- Produces: `pair_id`, subscriber/control IDs, exact-match covariates, both pre-session counts, distance, and deterministic match sequence.

- [ ] **Step 1: Write pair validity tests**

Use a union of violations so a passing test returns zero rows:

```sql
with pairs as (
  select * from {{ ref('int_hybrid_subscription__matched_pairs') }}
), violations as (
  select pair_id from pairs group by pair_id having count(*) != 1
  union all
  select subscriber_player_id from pairs group by subscriber_player_id having count(*) != 1
  union all
  select control_player_id from pairs group by control_player_id having count(*) != 1
  union all
  select pair_id from pairs
  where subscriber_prior_payer_status != control_prior_payer_status
     or subscriber_platform != control_platform
     or subscriber_acquisition_channel != control_acquisition_channel
)
select * from violations
```

The population reconciliation test must compare eligible subscriber/control counts to matched and unmatched counts emitted by the matching model's control-total columns.

- [ ] **Step 2: Build deterministic candidate rows**

Pivot pre-period behavior to one player row, split on `is_subscriber`, and create one global subscriber sequence ordered by:

```sql
order by prior_payer_status, platform, acquisition_channel,
         pre_session_count, player_id
```

- [ ] **Step 3: Select controls recursively without replacement**

Use a DuckDB recursive CTE whose state carries the list of used control IDs. The matching core is:

```sql
with recursive
ordered_subscribers as (
    select
        *,
        row_number() over (
            order by prior_payer_status, platform, acquisition_channel,
                     pre_session_count, player_id
        ) as subscriber_sequence
    from eligible_players
    where is_subscriber
),
controls as (
    select * from eligible_players where not is_subscriber
),
matching as (
    select
        0::bigint as subscriber_sequence,
        null::varchar as subscriber_player_id,
        null::varchar as control_player_id,
        []::varchar[] as used_control_ids

    union all

    select
        subscriber.subscriber_sequence,
        subscriber.player_id,
        chosen.player_id,
        case
            when chosen.player_id is null then matching.used_control_ids
            else list_append(matching.used_control_ids, chosen.player_id)
        end
    from matching
    join ordered_subscribers subscriber
      on subscriber.subscriber_sequence = matching.subscriber_sequence + 1
    left join lateral (
        select control.player_id
        from controls control
        where control.prior_payer_status = subscriber.prior_payer_status
          and control.platform = subscriber.platform
          and control.acquisition_channel = subscriber.acquisition_channel
          and not list_contains(matching.used_control_ids, control.player_id)
        order by
          abs(control.pre_session_count - subscriber.pre_session_count),
          control.pre_session_count,
          control.player_id
        limit 1
    ) chosen on true
)
select *
from matching
where subscriber_sequence > 0
  and control_player_id is not null
```

Join subscriber and control attributes back after the recursive CTE. Derive `pair_id` as `subscriber_player_id || '__' || control_player_id` and persist absolute distance and sequence so the choice is auditable.

- [ ] **Step 4: Publish population control totals**

Cross join totals onto every pair:

```sql
eligible_subscriber_count,
eligible_control_count,
matched_pair_count,
eligible_subscriber_count - matched_pair_count as unmatched_subscriber_count,
eligible_control_count - matched_pair_count as unmatched_control_count
```

The reconciliation test calculates its own eligible and matched totals from source relations, so zero matched pairs remain testable without fabricating a pair row.

- [ ] **Step 5: Verify determinism and invariants**

```bash
cd game_analytics
dbt build --select int_hybrid_subscription__matched_pairs \
  assert_hybrid_matched_pairs_valid \
  assert_hybrid_matched_population_reconciles
dbt show --inline "select * from {{ ref('int_hybrid_subscription__matched_pairs') }} order by pair_id" --limit 20
```

Expected: all tests PASS; every control appears once; repeated builds return identical pair IDs.

- [ ] **Step 6: Commit matching**

```bash
git add game_analytics/models/hybrid_subscription/intermediate \
  game_analytics/tests/hybrid_subscription/assert_hybrid_matched_pairs_valid.sql \
  game_analytics/tests/hybrid_subscription/assert_hybrid_matched_population_reconciles.sql
git commit -m "feat: add deterministic hybrid subscriber matching"
```

### Task 5: Publish pair-level incrementality and matched diagnostic inputs

**Files:**
- Create: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__matched_incrementality.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__engagement_lift_inputs.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__cannibalization_inputs.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/kpi_schema.yml`
- Modify: `game_analytics/tests/hybrid_subscription/assert_hybrid_cannibalization_reconciles.sql`
- Modify: `game_analytics/tests/hybrid_subscription/assert_hybrid_diagnostic_segments_are_populated.sql`

**Interfaces:**
- Consumes: `int_hybrid_subscription__matched_pairs` and mature player-period behavior.
- Produces: one pair row with subscriber/control pre, post, change, and difference-in-differences for sessions, LiveOps, standalone, subscription, and total revenue.

- [ ] **Step 1: Make existing mart tests demand pair-grain inputs**

Update the tests to require a non-null `pair_id`, equal subscriber/control counts, and reconciliation to `mart_hybrid_subscription__matched_incrementality`. Run them and expect failure against the unmatched marts.

- [ ] **Step 2: Build pair-level deltas**

Join each pair to four behavior aliases: subscriber pre/post and control pre/post. For each metric `x`, publish:

```sql
subscriber_x_change = subscriber_post_x - subscriber_pre_x
control_x_change = control_post_x - control_pre_x
x_difference_in_differences = subscriber_x_change - control_x_change
```

Use explicit SQL aliases for `session_count`, `liveops_participation_count`, `standalone_store_net_revenue_usd`, `subscription_net_revenue_usd`, and `total_net_revenue_usd`; do not generate dynamic SQL.

- [ ] **Step 3: Rebuild engagement and cannibalization inputs from pairs**

Engagement inputs aggregate pair-level session and LiveOps deltas by exact-match covariates. Cannibalization inputs filter pairs where subscriber and control are both prior payers and aggregate standalone, subscription, and total revenue components. Both marts expose `matched_pair_count`, component sums, and means.

- [ ] **Step 4: Document keys and component fields**

In `kpi_schema.yml`, add the matched mart with unique/not-null `pair_id`; revise input-mart descriptions from eligible-player comparisons to matched-pair summaries. Add not-null tests for component numerators and matched counts.

- [ ] **Step 5: Run the pair-level slice**

```bash
cd game_analytics
dbt build --select \
  mart_hybrid_subscription__matched_incrementality \
  mart_hybrid_subscription__engagement_lift_inputs \
  mart_hybrid_subscription__cannibalization_inputs \
  assert_hybrid_cannibalization_reconciles \
  assert_hybrid_diagnostic_segments_are_populated
```

Expected: PASS and the aggregate pair count equals `int_hybrid_subscription__matched_pairs`.

- [ ] **Step 6: Commit the matched marts**

```bash
git add game_analytics/models/hybrid_subscription/marts \
  game_analytics/tests/hybrid_subscription/assert_hybrid_cannibalization_reconciles.sql \
  game_analytics/tests/hybrid_subscription/assert_hybrid_diagnostic_segments_are_populated.sql
git commit -m "feat: publish matched hybrid incrementality marts"
```

### Task 6: Implement cohort, daily, and monthly KPI contracts

**Files:**
- Create: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__subscription_cohorts.sql`
- Create: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__monthly_kpis.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__daily_kpis.sql`
- Modify: `game_analytics/models/hybrid_subscription/marts/kpi_schema.yml`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_kpis_reconcile.sql`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_zero_denominators_are_null.sql`
- Create: `game_analytics/tests/hybrid_subscription/assert_hybrid_cohort_maturity.sql`

**Interfaces:**
- Consumes: canonical sessions, subscriber daily state, exposures, entitlements, store transactions, LiveOps participation, player dimension, matched incrementality.
- Produces: all ten approved KPI contracts with recomputable numerators and denominators.

- [ ] **Step 1: Write failing formula and maturity tests**

The zero-denominator test is:

```sql
select *
from {{ ref('mart_hybrid_subscription__monthly_kpis') }}
where (mau = 0 and arpmau is not null)
   or (mau = 0 and liveops_participation_rate is not null)
   or (eligible_standalone_transaction_count = 0 and discount_utilization_rate is not null)
```

The cohort test rejects conversion cohorts younger than 28 days with non-null conversion and D30 cohorts younger than 30 days with non-null retention.

- [ ] **Step 2: Build eligible-exposure and D30 cohorts**

Publish one row per eligible-exposure cohort date and one row per subscription-start cohort date, including:

```sql
eligible_exposed_player_count,
converted_within_28d_player_count,
case when is_conversion_mature then converted_within_28d_player_count::double
  / nullif(eligible_exposed_player_count, 0) end as subscription_conversion_rate,
mature_subscription_starter_count,
retained_at_d30_player_count,
case when is_d30_mature then retained_at_d30_player_count::double
  / nullif(mature_subscription_starter_count, 0) end as d30_subscriber_retention_rate
```

Use the governed maximum observation timestamp as the as-of boundary.

- [ ] **Step 3: Correct and extend daily KPIs**

Read sessions from the canonical session fact, transaction categories from their boolean flags, and active subscribers from `fct_hybrid_subscription__subscriber_daily`. Preserve existing grant/exposure controls. Publish active-subscriber players distinctly at `metric_date × prior_payer_status` grain rather than summing entitlement records.

- [ ] **Step 4: Build monthly KPI components**

At calendar-month grain publish:

```sql
mau,
month_end_active_subscriber_count,
month_start_active_subscriber_count,
expired_or_revoked_entitlement_count,
subscriber_churn_rate,
standalone_store_net_revenue_usd,
subscription_net_revenue_usd,
total_net_revenue_usd,
arpmau,
discounted_standalone_transaction_count,
eligible_standalone_transaction_count,
discount_utilization_rate,
liveops_participant_count,
liveops_participation_rate
```

Count churn only on expiry/revocation terminal events. Join matched pair aggregates for engagement lift and incremental total net revenue as separately labeled observational fields; do not multiply a 28-day estimate into a monthly forecast.

- [ ] **Step 5: Reconcile every formula to facts**

In `assert_hybrid_kpis_reconcile.sql`, independently aggregate canonical facts and compare all component columns with `except all` in both directions. Also assert:

```sql
total_net_revenue_usd = standalone_store_net_revenue_usd + subscription_net_revenue_usd
```

and verify cancellation rows do not enter the churn numerator.

- [ ] **Step 6: Run KPI contracts and selector build**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/dbt/test_hybrid_subscription_marts_contract.py \
  tests/dbt/test_hybrid_subscription_intermediate_contract.py \
  tests/dbt/test_hybrid_subscription_kpi_marts_contract.py -v
cd game_analytics
dbt build --selector hybrid_subscription
```

Expected: all Python contracts PASS and dbt completes with `ERROR=0`.

- [ ] **Step 7: Commit the complete KPI layer**

```bash
git add game_analytics/models/hybrid_subscription/marts \
  game_analytics/tests/hybrid_subscription tests/dbt
git commit -m "feat: publish complete hybrid subscription KPI contracts"
```

### Task 7: Refactor Python calculations to matched-pair grain

**Files:**
- Modify: `src/analytics_lab/analysis/hybrid_subscription_diagnostic.py`
- Modify: `tests/analysis/test_hybrid_subscription_diagnostic.py`

**Interfaces:**
- Consumes: a DataFrame with one row per `pair_id` from `mart_hybrid_subscription__matched_incrementality` and governed aggregate control DataFrames.
- Produces: `engagement_summary(pairs: pd.DataFrame) -> dict[str, float | int | None]`, `revenue_summary(pairs: pd.DataFrame) -> dict[str, float | int]`, `bootstrap_intervals(pairs: pd.DataFrame, *, draws: int = 2000, seed: int = 42) -> dict[str, list[float]]`, and `reconcile_published_inputs(pairs: pd.DataFrame, engagement_inputs: pd.DataFrame, cannibalization_inputs: pd.DataFrame, *, tolerance: float = 1e-9) -> None`.

- [ ] **Step 1: Replace the fixture with explicit pair rows**

Create rows containing `pair_id`, exact-match covariates, session/LiveOps differences, and three revenue differences. Include two pairs with known outputs, one duplicate-pair case, and one covariate-mismatch case.

- [ ] **Step 2: Write failures for pair validation and output math**

Add tests that assert:

```python
assert result["matched_pair_count"] == 2
assert result["engagement_difference_in_differences"] == pytest.approx(1.25)
assert revenue["total_revenue_difference_in_differences"] == pytest.approx(0.0)
```

Add `pytest.raises(ValueError, match="unique pair_id")` and `pytest.raises(ValueError, match="matching covariates")` cases. Add a revenue-component test asserting `total == standalone + subscription` and that reward-track is not part of total.

- [ ] **Step 3: Run the module and verify the new tests fail**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/analysis/test_hybrid_subscription_diagnostic.py -v
```

Expected: FAIL because current functions require player-period rows.

- [ ] **Step 4: Implement `_validated_pairs` and pair summaries**

Define:

```python
def _validated_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, MATCHED_PAIR_COLUMNS, "matched incrementality")
    if frame["pair_id"].isna().any() or frame["pair_id"].duplicated().any():
        raise ValueError("matched incrementality must have unique pair_id")
    for column in ("prior_payer_status", "platform", "acquisition_channel"):
        if not frame[f"subscriber_{column}"].eq(frame[f"control_{column}"]).all():
            raise ValueError("matched pair matching covariates disagree")
    return frame.copy()
```

Compute summaries as means of published pair differences. Bootstrap by sampling entire pair rows with replacement and taking the mean of each sampled difference column. This preserves within-pair covariance and eliminates the current incorrect subscriber-status stratification.

- [ ] **Step 5: Update reconciliation**

Compare pair-level sums/counts against engagement, cannibalization, and matched-control marts. Reject missing pairs, duplicate aggregates, and numeric differences larger than `1e-9`.

- [ ] **Step 6: Run analysis tests and Ruff**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/analysis/test_hybrid_subscription_diagnostic.py -v
./.venv/bin/python -m ruff check src tests
```

Expected: all tests and lint checks PASS.

- [ ] **Step 7: Commit the pair-grain analysis library**

```bash
git add src/analytics_lab/analysis/hybrid_subscription_diagnostic.py \
  tests/analysis/test_hybrid_subscription_diagnostic.py
git commit -m "fix: calculate hybrid diagnostic at matched pair grain"
```

### Task 8: Update and execute the governed notebook

**Files:**
- Modify: `notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py`
- Create and commit: `reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json`
- Generate but do not commit: `notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.ipynb`
- Generate but do not commit: `reports/hybrid_subscription/figures/`

**Interfaces:**
- Consumes: matched incrementality, matched aggregate inputs, monthly KPIs, cohorts, and incident mart.
- Produces: reproducible JSON containing input relations, eligibility/matching rules, control totals, results, uncertainty, and limitations.

- [ ] **Step 1: Replace notebook inputs and validation flow**

Set `INPUT_RELATIONS` to the matched incrementality mart, engagement/cannibalization summaries, monthly KPI mart, subscription cohort mart, and incident mart. Query only `main_hybrid_subscription` governed marts. Run `reconcile_published_inputs` before calculations.

- [ ] **Step 2: Replace metadata and narrative**

Set the pairing rule to the exact strata and deterministic nearest-control ordering. Report eligible subscribers, eligible controls, matched pairs, and both unmatched counts. Separate observed facts, inferences, and limitations; explicitly state that matching does not establish exchangeability, parallel trends, causality, profitability, or lifetime value.

- [ ] **Step 3: Render pair-level figures**

Plot the distribution of pair session differences and the standalone/subscription/total pair revenue differences. Label every axis as a 28-day matched observational difference; do not label it uplift caused by subscription.

- [ ] **Step 4: Execute at the final code commit for this task**

First commit the notebook source:

```bash
git add notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py
git commit -m "feat: update hybrid matched diagnostic notebook"
```

Then execute:

```bash
./.venv/bin/python -m jupytext --to notebook --execute \
  notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py \
  --output notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.ipynb
./.venv/bin/python -m json.tool \
  reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json >/dev/null
```

- [ ] **Step 5: Validate provenance and commit only JSON**

Confirm `metadata.code_version` equals `git rev-parse HEAD`, seed equals `42`, draws equals `2000`, and all governed input relations are listed. Commit:

```bash
git add reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json
git commit -m "data: publish matched hybrid diagnostic results"
```

Leave the generated `.ipynb` and figures untracked.

### Task 9: Align metric governance, decision documents, and agent evaluation

**Files:**
- Modify: `docs/metrics/hybrid_subscription.md`
- Modify: `reports/hybrid_subscription/engagement_cannibalization_decision_memo.md`
- Modify: `docs/ai-audit/hybrid_subscription.md`
- Modify: `docs/ai-audit/hybrid_subscription_questions.yaml`
- Modify: `scripts/evaluation/hybrid_subscription_answers.json`
- Modify: `tests/docs/test_hybrid_subscription_metric_catalogue.py`
- Modify: `tests/docs/test_hybrid_subscription_decision_memo.py`
- Modify: `tests/evaluation/test_hybrid_subscription_questions.py`
- Modify: `README.md`
- Regenerate: `reports/hybrid_subscription/agent_evaluation.json`

**Interfaces:**
- Consumes: regenerated JSON and all ten dbt KPI contracts.
- Produces: internally consistent decision documentation and a trusted-agent suite that rejects unsupported interpretations.

- [ ] **Step 1: Expand documentation tests before prose**

Require the metric catalogue to contain exact entries for MAU, active subscribers, subscription conversion, subscriber churn, D30 subscriber retention, ARPMAU, incremental net revenue, discount utilization, engagement lift, and LiveOps participation. Require each entry to specify grain, numerator, denominator, exclusions, source model, maturity, and interpretation boundary.

Require the memo to cite the regenerated JSON, report matched/unmatched counts, distinguish standalone displacement from total value, and contain `does not establish causality`. Require it not to link the generated notebook or figures.

- [ ] **Step 2: Run documentation tests and verify failure**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/docs/test_hybrid_subscription_metric_catalogue.py \
  tests/docs/test_hybrid_subscription_decision_memo.py -v
```

Expected: FAIL on the missing KPI definitions and stale unmatched values.

- [ ] **Step 3: Rewrite catalogue, memo, and audit from regenerated evidence**

Copy numeric values from the committed results JSON; do not manually recompute them. Document reward-track exclusion, eligible-exposure indexing, deterministic matching, maturity rules, null denominator behavior, and the observational decision boundary. Remove every link that implies the untracked `.ipynb` or figures are published.

- [ ] **Step 4: Expand the trusted-agent cases**

Add cases for all ten KPI definitions, pair provenance, eligible-exposure indexing, unmatched-player handling, reward-track exclusion, zero denominators, cohort maturity, and refusal of causal/LTV claims. Give each case canonical answers grounded in named governed relations and updated JSON fields.

- [ ] **Step 5: Run tests and regenerate evaluation**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/docs/test_hybrid_subscription_metric_catalogue.py \
  tests/docs/test_hybrid_subscription_decision_memo.py \
  tests/evaluation/test_hybrid_subscription_questions.py -v
./.venv/bin/python -m analytics_lab.evaluate \
  --scenario hybrid_subscription \
  --questions docs/ai-audit/hybrid_subscription_questions.yaml \
  --answers scripts/evaluation/hybrid_subscription_answers.json \
  --output reports/hybrid_subscription/agent_evaluation.json
./.venv/bin/python -m json.tool \
  reports/hybrid_subscription/agent_evaluation.json >/dev/null
```

Expected: tests PASS and evaluation JSON reports `passed == total`.

- [ ] **Step 6: Commit governance artifacts**

```bash
git add README.md docs/metrics/hybrid_subscription.md \
  docs/ai-audit/hybrid_subscription.md \
  docs/ai-audit/hybrid_subscription_questions.yaml \
  reports/hybrid_subscription/engagement_cannibalization_decision_memo.md \
  reports/hybrid_subscription/agent_evaluation.json \
  scripts/evaluation/hybrid_subscription_answers.json \
  tests/docs tests/evaluation/test_hybrid_subscription_questions.py
git commit -m "docs: govern complete hybrid subscription decision evidence"
```

### Task 10: Run the final gate and prepare the pull request

**Files:**
- Verify: all tracked files changed by Tasks 1-9.
- Keep untracked: generated notebook and `reports/hybrid_subscription/figures/`.

**Interfaces:**
- Consumes: completed branch.
- Produces: reviewable branch with no unresolved Critical or Important findings.

- [ ] **Step 1: Run the full Python and lint gate**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest -W error
./.venv/bin/python -m ruff check src tests
```

Expected: all tests PASS and Ruff prints `All checks passed!`.

- [ ] **Step 2: Run the full dbt gate**

```bash
cd game_analytics
dbt parse --no-partial-parse
dbt build --selector hybrid_subscription
cd ..
```

Expected: parse succeeds and build ends with `ERROR=0`, `WARN=0`, and `SKIP=0`.

- [ ] **Step 3: Re-run the evaluator and artifact checks**

```bash
./.venv/bin/python -m analytics_lab.evaluate \
  --scenario hybrid_subscription \
  --questions docs/ai-audit/hybrid_subscription_questions.yaml \
  --answers scripts/evaluation/hybrid_subscription_answers.json \
  --output reports/hybrid_subscription/agent_evaluation.json
./.venv/bin/python -m json.tool \
  reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json >/dev/null
./.venv/bin/python -m json.tool \
  reports/hybrid_subscription/agent_evaluation.json >/dev/null
```

Expected: evaluator passes every case and both JSON files are valid.

- [ ] **Step 4: Check diffs and tracked status**

```bash
git diff --check
git diff --cached --check
git status --short
```

Expected: no tracked modifications remain. Only the generated `.ipynb` and figure directory may be untracked.

- [ ] **Step 5: Request an independent code review**

Invoke `superpowers:requesting-code-review` against the merge base with `origin/main`. Resolve every Critical and Important finding, repeat the relevant failing-first test cycle, and rerun Steps 1-4 after any correction.

- [ ] **Step 6: Push and open the pull request**

```bash
git push origin scenario/hybrid-subscription
```

Open a PR to `main` summarizing the eligible-exposure population, deterministic matching, full KPI layer, corrected revenue classification, regenerated evidence, and exact validation results.
