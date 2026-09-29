# Hybrid Game Subscription Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently executable hybrid free-to-play game subscription scenario that measures incremental net value against matched non-subscriber controls while detecting and containing all five designed tracking failures.

**Architecture:** A scenario generator writes deterministic Parquet data below data/raw/hybrid_subscription. Scenario-tagged dbt models transform it through staging, intermediate lifecycle/reconciliation, and governed marts; a notebook reads marts only, while a constrained agent is evaluated against approved marts and metric definitions.

**Tech Stack:** Python 3.12, pandas, pytest, DuckDB, dbt, Jupyter, SQL, Parquet, Git.

**Spec:** docs/superpowers/specs/2026-08-27-three-scenario-analytics-lab-design.md

## Global Constraints

- Depend on the shared foundation's package/config, dbt base project, templates, generator conventions, and CI; do not edit shared infrastructure.
- Native Apple Silicon workflow only: Python 3.12, DuckDB, dbt, and Git. Do not add Docker or a dev container.
- Consume GenerationConfig(scenario: str, seed: int, start_date: date, days: int, scale: int, output_dir: Path) from src/analytics_lab/generation/base.py and expose generate(config: GenerationConfig) -> dict[str, pandas.DataFrame].
- Use shared write_tables(tables: dict[str, DataFrame], output_dir: Path) -> list[Path] for Parquet output. Invalid scenario, non-positive days/scale, and non-writable paths fail explicitly.
- Use CLI: python -m analytics_lab.generate --scenario hybrid_subscription --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw.
- Tag every dbt resource hybrid_subscription and test independent construction with dbt build --selector hybrid_subscription.
- Preserve raw evidence; detect failures in raw/staging and repair only in named intermediate models.
- Retain raw timestamp string, local timestamp, and source timezone while canonicalizing timestamp columns to UTC. Monetary fields use ISO code USD; v1 performs no FX conversion.
- Cancellation means auto-renew disabled; subscription entitlement continues through current_period_end_at_utc unless expired or revoked.
- Govern each metric with eligibility, grain, exclusions, time rules, and limitations. Judge net value with total net revenue, and label matching results associative rather than causal.
- dbt contracts must block marts for key, relationship, temporal, accepted-value, and reconciliation failure.
- Agent access is limited to approved metrics/marts; it refuses and records requests outside those boundaries.
- Do not add raw personal data, paid warehouses, production writes, automatic publishing, Slack/email, multi-agent orchestration, fine-tuning, complex web UI, or production/autonomy claims.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| src/analytics_lab/generation/hybrid_subscription.py | Deterministic generation and fault injection. |
| tests/generation/test_hybrid_subscription.py | Generator determinism, integrity, distribution, invalid-config tests. |
| docs/architecture/hybrid_subscription_raw_contract.md | Raw grain, keys, timestamps, and injected failure rates. |
| game_analytics/models/hybrid_subscription/_hybrid_subscription_sources.yml | Raw source registration and freshness/contracts. |
| game_analytics/models/hybrid_subscription/stg_hybrid_*.sql | Typed, renamed, UTC-normalized source models. |
| game_analytics/models/hybrid_subscription/int_hybrid_*.sql | Transaction dedupe, entitlement state, grants, exposure, player-day state. |
| game_analytics/models/hybrid_subscription/marts/*.sql | Governed facts, matched panel, KPIs. |
| game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml | Metadata, tags, schema tests. |
| game_analytics/tests/test_hybrid_subscription_*.sql | Custom containment, temporal, and reconciliation tests. |
| src/analytics_lab/validation/validate_hybrid_subscription.py | Validator implementation and module CLI. |
| scripts/validation/validate_hybrid_subscription.py | Thin command wrapper that imports and invokes the validator implementation. |
| docs/metrics/hybrid_subscription_metrics.md | Metric catalogue and USD policy. |
| docs/incidents/hybrid_subscription_incidents.md | Failure evidence, containment, and limitations. |
| notebooks/hybrid_subscription/01_incrementality_diagnostic.ipynb | Executed matched-control diagnostic. |
| reports/hybrid_subscription/decision_memo.md | Decision-ready evidence and recommendation. |
| docs/ai-audit/hybrid_subscription_review.md | Approved, rejected, and corrected AI work. |
| scripts/evaluation/hybrid_subscription_questions.yaml | Trusted questions. |
| src/analytics_lab/evaluation/evaluate_hybrid_subscription.py | Approved-source evaluator implementation and module CLI. |
| scripts/evaluation/evaluate_hybrid_subscription.py | Thin command wrapper that imports and invokes the evaluator implementation. |
| tests/validation/test_validate_hybrid_subscription.py; tests/analytics/test_hybrid_subscription_*.py; tests/evaluation/test_evaluate_hybrid_subscription.py | Python validation, analysis, memo, release, and evaluation tests. |

### Task 1: Define raw contract and generator

**Files:**
- Create: src/analytics_lab/generation/hybrid_subscription.py
- Create: tests/generation/test_hybrid_subscription.py
- Create: docs/architecture/hybrid_subscription_raw_contract.md

**Interfaces:**
- Consumes: GenerationConfig from analytics_lab.generation.base; the shared CLI persists returned frames through write_tables from analytics_lab.generation.io.
- Produces: generate(config: GenerationConfig) -> dict[str, pd.DataFrame] with exact keys hybrid_players, hybrid_sessions, hybrid_subscription_events, hybrid_store_transactions, hybrid_currency_ledger, hybrid_live_event_participation, hybrid_marketing_exposures, hybrid_product_catalogue.
- Produces: scenario_run_id in all tables; stable event/transaction ID and ingested_at_utc in event tables.

- [ ] **Step 1: Write the failing test**

~~~python
from datetime import date
from pathlib import Path
import pandas.testing as pdt
import pytest
from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.hybrid_subscription import generate

def config(tmp_path: Path, seed: int = 42) -> GenerationConfig:
    return GenerationConfig("hybrid_subscription", seed, date(2026, 1, 1), 180, 1000, tmp_path)

def test_same_seed_produces_identical_tables(tmp_path: Path) -> None:
    first, second = generate(config(tmp_path)), generate(config(tmp_path))
    assert set(first) == {"hybrid_players", "hybrid_sessions", "hybrid_subscription_events", "hybrid_store_transactions", "hybrid_currency_ledger", "hybrid_live_event_participation", "hybrid_marketing_exposures", "hybrid_product_catalogue"}
    for key in first:
        pdt.assert_frame_equal(first[key], second[key], check_like=False)

def test_references_and_designed_failures_exist(tmp_path: Path) -> None:
    tables = generate(config(tmp_path))
    assert set(tables["hybrid_sessions"].player_id) <= set(tables["hybrid_players"].player_id)
    assert tables["hybrid_store_transactions"].transaction_id.duplicated().any()
    assert tables["hybrid_currency_ledger"].source_subscription_transaction_id.isna().any()
    starts = tables["hybrid_subscription_events"].query("event_type == 'started'")
    assert (tables["hybrid_marketing_exposures"].merge(starts, on="player_id").exposed_at_utc > tables["hybrid_marketing_exposures"].merge(starts, on="player_id").occurred_at_utc).any()

@pytest.mark.parametrize(("days", "scale"), [(0, 1000), (180, 0)])
def test_invalid_config_fails(tmp_path: Path, days: int, scale: int) -> None:
    with pytest.raises(ValueError, match="days and scale must be positive"):
        generate(GenerationConfig("hybrid_subscription", 42, date(2026, 1, 1), days, scale, tmp_path))
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/generation/test_hybrid_subscription.py -v

Expected: FAIL with an import error for analytics_lab.generation.hybrid_subscription.

- [ ] **Step 3: Write minimal implementation**

~~~python
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from analytics_lab.generation.base import GenerationConfig

TABLE_NAMES = ("hybrid_players", "hybrid_sessions", "hybrid_subscription_events", "hybrid_store_transactions", "hybrid_currency_ledger", "hybrid_live_event_participation", "hybrid_marketing_exposures", "hybrid_product_catalogue")

def generate(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    if config.scenario != "hybrid_subscription":
        raise ValueError("hybrid generator requires scenario='hybrid_subscription'")
    if config.days <= 0 or config.scale <= 0:
        raise ValueError("days and scale must be positive")
    rng = np.random.default_rng(config.seed)
    run_id = hashlib.sha256(f"{config.scenario}:{config.seed}:{config.start_date}:{config.days}:{config.scale}".encode()).hexdigest()[:16]
    # Return all TABLE_NAMES built deterministically from rng and run_id.
~~~

Complete the raw-contract document with one row for every output: grain, primary key, foreign keys, required columns, and timezone encoding. Create product SKUs sub_monthly, currency_bundle_small, currency_bundle_large, cosmetic_pack; lifecycle event types started, renewed, canceled, expired; transaction status succeeded, refunded, failed; ledger types subscription_grant, purchase_grant, spend.

Inject exactly 1.5% duplicate transaction webhook rows with later ingested_at_utc, 12% cancellation rows whose entitlement continues to future current_period_end_at_utc, sessions encoded America/Los_Angeles local time and transactions encoded UTC local time, 8% subscription grants with missing source_subscription_transaction_id, and 5% marketing exposures later than the player's first subscription start. Every time field preserves field_raw, field_local, field_timezone, and UTC instant. All money is decimal USD and currency_code equals USD.

- [ ] **Step 4: Run tests and create raw output**

Run: pytest tests/generation/test_hybrid_subscription.py -v && python -m analytics_lab.generate --scenario hybrid_subscription --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw

Expected: PASS; eight Parquet files exist at data/raw/hybrid_subscription.

- [ ] **Step 5: Commit**

~~~bash
git add src/analytics_lab/generation/hybrid_subscription.py tests/generation/test_hybrid_subscription.py docs/architecture/hybrid_subscription_raw_contract.md
git commit -m "feat: generate hybrid subscription raw data"
~~~

### Task 2: Register and stage raw sources

**Files:**
- Create: game_analytics/models/hybrid_subscription/_hybrid_subscription_sources.yml
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_players.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_sessions.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_subscription_events.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_store_transactions.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_currency_ledger.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_live_event_participation.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_marketing_exposures.sql
- Create: game_analytics/models/hybrid_subscription/stg_hybrid_product_catalogue.sql
- Create: game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml
- Create: game_analytics/tests/test_hybrid_subscription_session_utc_normalization.sql

**Interfaces:**
- Consumes: Task 1 Parquet sources under source name hybrid_subscription_raw.
- Produces: one tagged stg_hybrid relation per raw table with canonical UTC timestamp, local/raw/timezone fields, transaction_webhook_rank, and is_missing_subscription_link.

- [ ] **Step 1: Write failing schema and timezone tests**

~~~yaml
version: 2
models:
  - name: stg_hybrid_sessions
    columns:
      - name: session_id
        tests: [not_null]
      - name: started_at_utc
        tests: [not_null]
  - name: stg_hybrid_subscription_events
    columns:
      - name: event_type
        tests:
          - accepted_values: {values: [started, renewed, canceled, expired, revoked]}
  - name: stg_hybrid_store_transactions
    columns:
      - name: transaction_status
        tests:
          - accepted_values: {values: [succeeded, refunded, failed]}
~~~

~~~sql
select session_id
from {{ ref('stg_hybrid_sessions') }}
where source_timezone = 'America/Los_Angeles'
  and started_at_utc <> (started_at_local at time zone source_timezone)
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: dbt test --select stg_hybrid_sessions stg_hybrid_subscription_events stg_hybrid_store_transactions

Expected: FAIL because scenario sources/models are absent.

- [ ] **Step 3: Write minimal implementation**

~~~sql
{{ config(materialized='view', tags=['hybrid_subscription']) }}
with source as (
  select * from {{ source('hybrid_subscription_raw', 'hybrid_store_transactions') }}
)
select
  transaction_id, player_id, sku, transaction_status,
  cast(amount_usd as decimal(18,2)) as amount_usd,
  cast(refund_amount_usd as decimal(18,2)) as refund_amount_usd,
  currency_code, transaction_at_raw, transaction_at_local,
  transaction_timezone as source_timezone,
  transaction_at_local at time zone transaction_timezone as transaction_at_utc,
  ingested_at_utc, scenario_run_id,
  row_number() over (partition by transaction_id order by ingested_at_utc desc) as transaction_webhook_rank,
  cast(amount_usd as decimal(18,2)) - cast(refund_amount_usd as decimal(18,2)) as raw_net_revenue_usd
from source
~~~

Use the identical local-at-time-zone conversion for sessions, lifecycle events, ledger entries, LiveOps participation, and exposure events. Retain raw evidence and do not dedupe staging. Add source freshness only to event sources using loaded_at_field ingested_at_utc and warn_after 2 days. Test IDs/player keys, relationships to stg_hybrid_players, currency USD, and event/status/entry accepted values. Do not add raw transaction uniqueness because duplicates are intentional.

- [ ] **Step 4: Run staging build**

Run: dbt build --select stg_hybrid_players stg_hybrid_sessions stg_hybrid_subscription_events stg_hybrid_store_transactions stg_hybrid_currency_ledger stg_hybrid_live_event_participation stg_hybrid_marketing_exposures stg_hybrid_product_catalogue

Expected: PASS; duplicate transaction evidence remains at transaction_webhook_rank greater than one.

- [ ] **Step 5: Commit**

~~~bash
git add game_analytics/models/hybrid_subscription game_analytics/tests/test_hybrid_subscription_session_utc_normalization.sql
git commit -m "feat: stage hybrid subscription events"
~~~

### Task 3: Reconstruct entitlement state and contain defects

**Files:**
- Create: game_analytics/models/hybrid_subscription/int_hybrid_reconciled_store_transactions.sql
- Create: game_analytics/models/hybrid_subscription/int_hybrid_subscription_entitlements.sql
- Create: game_analytics/models/hybrid_subscription/int_hybrid_currency_grant_reconciliation.sql
- Create: game_analytics/models/hybrid_subscription/int_hybrid_exposure_timeline.sql
- Create: game_analytics/models/hybrid_subscription/int_hybrid_player_day.sql
- Create: game_analytics/tests/test_hybrid_subscription_no_duplicate_modeled_transactions.sql
- Create: game_analytics/tests/test_hybrid_subscription_entitlement_cancellation.sql
- Create: game_analytics/tests/test_hybrid_subscription_exposure_precedes_subscription.sql
- Modify: game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml

**Interfaces:**
- Consumes: all stg_hybrid models.
- Produces: one row per reconciled transaction, subscription period, ledger entry, exposure, and player/date respectively.
- Produces: is_duplicate_webhook, is_subscription_grant_unlinked, is_post_subscription_exposure, is_cancelled_but_entitled, and prior_payer_status.

- [ ] **Step 1: Write failing containment tests**

~~~sql
select transaction_id
from {{ ref('int_hybrid_reconciled_store_transactions') }}
group by 1 having count(*) <> 1
~~~

~~~sql
select player_id, subscription_period_id
from {{ ref('int_hybrid_subscription_entitlements') }}
where cancellation_at_utc is not null
  and entitlement_ended_at_utc < current_period_end_at_utc
~~~

~~~sql
select exposure_id
from {{ ref('int_hybrid_exposure_timeline') }}
where is_eligible_pre_subscription_exposure
  and exposed_at_utc > first_subscription_started_at_utc
~~~

- [ ] **Step 2: Run tests to verify failure**

Run: dbt test --select int_hybrid_reconciled_store_transactions int_hybrid_subscription_entitlements int_hybrid_exposure_timeline

Expected: FAIL because intermediate models are absent.

- [ ] **Step 3: Write minimal implementation**

~~~sql
{{ config(materialized='table', tags=['hybrid_subscription']) }}
select
  *,
  transaction_webhook_rank > 1 as is_duplicate_webhook,
  transaction_status = 'succeeded' as is_successful_transaction,
  case when transaction_status in ('succeeded', 'refunded')
       then raw_net_revenue_usd else cast(0 as decimal(18,2)) end as modeled_net_revenue_usd
from {{ ref('stg_hybrid_store_transactions') }}
qualify transaction_webhook_rank = 1
~~~

Pivot lifecycle events by player_id/subscription_period_id. Use entitlement_ended_at_utc = revoked_at_utc when present, otherwise expired_at_utc when present, otherwise current_period_end_at_utc; set is_cancelled_but_entitled when cancellation precedes current_period_end. Join subscription_grant rows to reconciled transactions using source_subscription_transaction_id, preserve null/no-match rows, and flag them. Mark exposures after first subscription as post-subscription and only on/before exposures eligible. Create shared-calendar player-date spine with sessions, engagement seconds, successful net spend, LiveOps, and entitlement; prior_payer means successful non-subscription spend strictly before first subscription. Add unique/not-null, relationship, temporal tests and a test that unlinked grants do not enter linked-grant analytics.

- [ ] **Step 4: Build intermediates**

Run: dbt build --select int_hybrid_reconciled_store_transactions int_hybrid_subscription_entitlements int_hybrid_currency_grant_reconciliation int_hybrid_exposure_timeline int_hybrid_player_day

Expected: PASS; duplicates are contained, canceled users retain entitlement, unlinked grants remain flagged, late exposures are ineligible.

- [ ] **Step 5: Commit**

~~~bash
git add game_analytics/models/hybrid_subscription/int_hybrid_*.sql game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml game_analytics/tests/test_hybrid_subscription_*.sql
git commit -m "feat: reconstruct hybrid subscription state"
~~~

### Task 4: Publish governed facts, panel, and KPI catalogue

**Files:**
- Create: game_analytics/models/hybrid_subscription/marts/dim_hybrid_player.sql
- Create: game_analytics/models/hybrid_subscription/marts/fct_hybrid_player_day.sql
- Create: game_analytics/models/hybrid_subscription/marts/fct_hybrid_store_transactions.sql
- Create: game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscriber_day.sql
- Create: game_analytics/models/hybrid_subscription/marts/fct_hybrid_liveops_participation.sql
- Create: game_analytics/models/hybrid_subscription/marts/mart_hybrid_incrementality_panel.sql
- Create: game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription_kpis.sql
- Create: game_analytics/tests/test_hybrid_subscription_kpi_reconciliation.sql
- Create: docs/metrics/hybrid_subscription_metrics.md
- Modify: game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml

**Interfaces:**
- Consumes: Task 3 intermediate relations.
- Produces: mart_hybrid_incrementality_panel at subscriber_player_id/control_player_id/cohort_start_date/relative_day, spanning relative days -28 through 27.
- Produces: mart_hybrid_subscription_kpis at metric_date/prior_payer_status with MAU, active subscribers, conversion, churn, D30 retention, ARPMAU, incremental net revenue, discount utilization, engagement lift, and LiveOps participation.

- [ ] **Step 1: Write failing mart test**

~~~sql
with daily as (
  select transaction_at_utc::date as metric_date, sum(modeled_net_revenue_usd) as revenue
  from {{ ref('fct_hybrid_store_transactions') }} group by 1
), kpis as (
  select metric_date, sum(subscriber_incremental_net_revenue_usd) as incremental
  from {{ ref('mart_hybrid_subscription_kpis') }} group by 1
)
select daily.metric_date from daily join kpis using (metric_date)
where incremental > revenue
~~~

- [ ] **Step 2: Run test to verify failure**

Run: dbt test --select mart_hybrid_incrementality_panel mart_hybrid_subscription_kpis

Expected: FAIL because marts are absent.

- [ ] **Step 3: Write minimal implementation**

Create dim_hybrid_player one row/player; fct_hybrid_player_day one row/player/date; fct_hybrid_store_transactions one row/reconciled transaction; fct_hybrid_subscriber_day one row/entitled player/date; fct_hybrid_liveops_participation one row/player/event/date. Facts keep total net revenue (subscription plus store net of refunds), entitlement, discount, and LiveOps flags.

Use this matching stratum:

~~~sql
concat_ws('|', prior_payer_status, acquisition_channel,
  cast(pre_28d_session_seconds / 600 as varchar),
  cast(pre_28d_store_net_revenue_usd / 5 as varchar)) as match_stratum
~~~

Retain first-time subscribers with complete 28-day pre/post windows and controls never entitled during the same 56-day window. Require eligible exposure when an exposure exists. Select one deterministic control within stratum using row_number partitioned by subscriber player ordered by abs(hash(subscriber_player_id || control_player_id)) = 1. Emit 56 rows per pair.

Define KPI denominators precisely: active subscriber means entitled at any instant; conversion = first starts / MAU; churn = entitlement ends without renewal / opening subscribers; D30 = mature cohort entitled on day 30 / mature new subscribers; ARPMAU = modeled total net revenue / MAU; incremental revenue and engagement are matched difference-in-differences; discount utilization = entitled users purchasing a discount-eligible SKU / entitled users; LiveOps participation = participating active users / MAU. Return null on zero denominators.

Document each metric’s formula, eligibility, grain, exclusions, timezone, limitation, and source mart. Exclude failed transactions, lower-ranked duplicates, unlinked grants from grant analysis, post-subscription exposures, incomplete windows, and unresolved lifecycle boundaries. Document USD-only/no-FX policy.

- [ ] **Step 4: Run scenario gate**

Run: dbt build --selector hybrid_subscription

Expected: PASS; each retained pair has 56 rows and all marts meet contracts.

- [ ] **Step 5: Commit**

~~~bash
git add game_analytics/models/hybrid_subscription/marts game_analytics/models/hybrid_subscription/_hybrid_subscription_models.yml game_analytics/tests/test_hybrid_subscription_kpi_reconciliation.sql docs/metrics/hybrid_subscription_metrics.md
git commit -m "feat: publish hybrid subscription metrics"
~~~

### Task 5: Validate incidents and reconciliations

**Files:**
- Create: src/analytics_lab/validation/validate_hybrid_subscription.py
- Create: scripts/validation/validate_hybrid_subscription.py
- Create: tests/validation/test_validate_hybrid_subscription.py
- Create: docs/incidents/hybrid_subscription_incidents.md

**Interfaces:**
- Consumes: staging transactions/sessions and Task 3 reconciliation, entitlement, grant, exposure relations.
- Produces: validate_hybrid_subscription(connection: duckdb.DuckDBPyConnection) -> dict[str, object] with scenario, status, checks, generated_at_utc. Each check has name, observed_count, expected_condition, status, evidence_model.
- Produces: reports/hybrid_subscription/validation.json.

- [ ] **Step 1: Write failing test**

~~~python
import duckdb
from analytics_lab.validation.validate_hybrid_subscription import validate_hybrid_subscription

def test_duplicate_webhooks_are_detected_and_contained() -> None:
    con = duckdb.connect()
    con.execute("create table stg_hybrid_store_transactions as select 't1' transaction_id, 1 transaction_webhook_rank union all select 't1', 2")
    con.execute("create table int_hybrid_reconciled_store_transactions as select 't1' transaction_id")
    result = validate_hybrid_subscription(con)
    check = next(x for x in result["checks"] if x["name"] == "duplicate_store_webhooks")
    assert check["observed_count"] == 1
    assert check["status"] == "contained"
~~~

- [ ] **Step 2: Run test to verify failure**

Run: pytest tests/validation/test_validate_hybrid_subscription.py -v

Expected: FAIL because validator is absent.

- [ ] **Step 3: Write minimal implementation**

~~~python
INCIDENTS = {
    "duplicate_store_webhooks": ("stg_hybrid_store_transactions", "transaction_webhook_rank > 1", "contained"),
    "cancellation_entitlement": ("int_hybrid_subscription_entitlements", "is_cancelled_but_entitled", "contained"),
    "mixed_timezones": ("stg_hybrid_sessions", "source_timezone <> 'UTC'", "normalized"),
    "unlinked_subscription_grants": ("int_hybrid_currency_grant_reconciliation", "is_subscription_grant_unlinked", "contained"),
    "late_experiment_exposures": ("int_hybrid_exposure_timeline", "is_post_subscription_exposure", "contained"),
}
~~~

Each detector runs count(*). Fail if raw evidence is missing, containment breaks, canonical timestamps are non-UTC, eligible exposure follows subscription, or revenue reconciliation varies by more than $0.01. Document all five incident names, raw evidence model, detector, KPI impact, containment model, limitation, and test control. State explicitly that these are intentionally generated lab defects.

- [ ] **Step 4: Run validation**

Run: pytest tests/validation/test_validate_hybrid_subscription.py -v && dbt build --selector hybrid_subscription && python -m analytics_lab.validation.validate_hybrid_subscription --output reports/hybrid_subscription/validation.json

Expected: PASS; JSON contains five detected checks marked contained or normalized.

- [ ] **Step 5: Commit**

~~~bash
git add src/analytics_lab/validation/validate_hybrid_subscription.py scripts/validation/validate_hybrid_subscription.py tests/validation/test_validate_hybrid_subscription.py docs/incidents/hybrid_subscription_incidents.md
git commit -m "test: validate hybrid subscription incidents"
~~~

### Task 6: Execute matched-control diagnostic

**Files:**
- Create: notebooks/hybrid_subscription/incrementality_helpers.py
- Create: notebooks/hybrid_subscription/01_incrementality_diagnostic.ipynb
- Create: tests/analytics/test_hybrid_subscription_incrementality.py

**Interfaces:**
- Consumes: mart_hybrid_incrementality_panel, mart_hybrid_subscription_kpis, metric catalogue, validation JSON.
- Produces: load_panel(connection) -> pandas.DataFrame; estimate_difference_in_differences(panel: pandas.DataFrame, outcome: str) -> pandas.DataFrame; bootstrap_interval(panel, outcome, seed=42, resamples=1000) -> tuple[float, float].

- [ ] **Step 1: Write failing test**

~~~python
import pandas as pd
from notebooks.hybrid_subscription.incrementality_helpers import estimate_difference_in_differences

def test_did_uses_total_net_revenue_for_both_groups() -> None:
    panel = pd.DataFrame({"group": ["subscriber", "subscriber", "control", "control"], "period": ["pre", "post", "pre", "post"], "total_net_revenue_usd": [10.0, 16.0, 8.0, 10.0]})
    assert estimate_difference_in_differences(panel, "total_net_revenue_usd").loc[0, "estimate_usd"] == 4.0
~~~

- [ ] **Step 2: Run test to verify failure**

Run: pytest tests/analytics/test_hybrid_subscription_incrementality.py -v

Expected: FAIL because helper module is absent.

- [ ] **Step 3: Write minimal implementation**

~~~python
def estimate_difference_in_differences(panel: pd.DataFrame, outcome: str) -> pd.DataFrame:
    means = panel.groupby(["group", "period"], as_index=False)[outcome].mean()
    value = {(r.group, r.period): getattr(r, outcome) for r in means.itertuples()}
    estimate = (value["subscriber", "post"] - value["subscriber", "pre"]) - (value["control", "post"] - value["control", "pre"])
    return pd.DataFrame({"outcome": [outcome], "estimate_usd": [estimate]})
~~~

Notebook first cell records source marts, UTC execution time, git SHA, filters, seed, matching rule, validation JSON. Stop if a validation status is not contained/normalized. Report match count, covariate balance, pre-trend, 28-day total-net-revenue DID, engagement/LiveOps lift, prior-payer split, and unpaired sensitivity. Bootstrap matched pairs 1,000 times for 95% percentile intervals. Re-estimate complete 21/28/35-day windows; report insufficient maturity explicitly. Label every estimate: associative difference-in-differences estimate; not causal proof.

- [ ] **Step 4: Verify notebook**

Run: pytest tests/analytics/test_hybrid_subscription_incrementality.py -v && jupyter nbconvert --to notebook --execute notebooks/hybrid_subscription/01_incrementality_diagnostic.ipynb --output 01_incrementality_diagnostic.ipynb --output-dir notebooks/hybrid_subscription

Expected: PASS; output has payer segments, sensitivities, and intervals.

- [ ] **Step 5: Commit**

~~~bash
git add notebooks/hybrid_subscription tests/analytics/test_hybrid_subscription_incrementality.py
git commit -m "feat: analyze hybrid subscription incrementality"
~~~

### Task 7: Publish memo and AI audit record

**Files:**
- Create: reports/hybrid_subscription/decision_memo.md
- Create: docs/ai-audit/hybrid_subscription_review.md
- Create: tests/analytics/test_hybrid_subscription_memo.py

**Interfaces:**
- Consumes: executed notebook, metric catalogue, incident log, validation JSON, shared memo/review templates.
- Produces: memo headings Observed facts, Inference, Assumptions, Uncertainty and limitations, Recommendation.
- Produces: audit records work_id, proposed_work, approved_sources, human_validation, decision, rejection_reason, correction, provenance.

- [ ] **Step 1: Write failing test**

~~~python
from pathlib import Path

def test_memo_separates_evidence_from_interpretation() -> None:
    memo = Path("reports/hybrid_subscription/decision_memo.md").read_text()
    for heading in ["## Observed facts", "## Inference", "## Assumptions", "## Uncertainty and limitations", "## Recommendation"]:
        assert heading in memo
    assert "not causal proof" in memo
    assert "total net revenue" in memo
~~~

- [ ] **Step 2: Run test to verify failure**

Run: pytest tests/analytics/test_hybrid_subscription_memo.py -v

Expected: FAIL because memo is absent.

- [ ] **Step 3: Write memo/audit and test**

Use executed notebook values only. Include decision owner, next experiment/measurement action, payer-segment guardrails, and reversal condition. Link validation JSON, notebook, metric catalogue, and commit. Audit: accepted metric query; rejected subscription-revenue-only query; rejected causal claim; corrected query excluding late exposures/incomplete windows. Every row cites models/contracts and a human validation result.

- [ ] **Step 4: Verify**

Run: pytest tests/analytics/test_hybrid_subscription_memo.py -v

Expected: PASS; memo separates evidence and audit includes rejected/corrected outputs.

- [ ] **Step 5: Commit**

~~~bash
git add reports/hybrid_subscription/decision_memo.md docs/ai-audit/hybrid_subscription_review.md tests/analytics/test_hybrid_subscription_memo.py
git commit -m "docs: add hybrid subscription decision memo"
~~~

### Task 8: Evaluate constrained agent and release scenario

**Files:**
- Create: scripts/evaluation/hybrid_subscription_questions.yaml
- Create: src/analytics_lab/evaluation/evaluate_hybrid_subscription.py
- Create: scripts/evaluation/evaluate_hybrid_subscription.py
- Create: tests/evaluation/test_evaluate_hybrid_subscription.py
- Create: reports/hybrid_subscription/agent_evaluation.md
- Create: tests/analytics/test_hybrid_subscription_release.py
- Modify: reports/hybrid_subscription/decision_memo.md

**Interfaces:**
- Consumes: approved set {docs/metrics/hybrid_subscription_metrics.md, mart_hybrid_incrementality_panel, mart_hybrid_subscription_kpis, fct_hybrid_player_day, fct_hybrid_store_transactions}.
- Produces: evaluate_case(case: dict[str, object], answer: dict[str, object]) -> dict[str, object] with metric_score, population_score, join_logic_score, numeric_score, uncertainty_score, refusal_score, provenance_score, latency_ms, cost_usd, passed.

- [ ] **Step 1: Write failing test**

~~~python
from analytics_lab.evaluation.evaluate_hybrid_subscription import evaluate_case

def test_unapproved_request_requires_refusal_and_provenance() -> None:
    case = {"case_id": "unanswerable_raw_email", "expected_metric": None, "expected_population": None, "expected_result": None, "tolerance": 0, "refusal_required": True}
    answer = {"refused": True, "provenance": ["policy: approved marts and metric catalogue only"], "latency_ms": 120, "cost_usd": 0.001}
    result = evaluate_case(case, answer)
    assert result["refusal_score"] == 1
    assert result["provenance_score"] == 1
    assert result["passed"] is True
~~~

- [ ] **Step 2: Run test to verify failure**

Run: pytest tests/evaluation/test_evaluate_hybrid_subscription.py -v

Expected: FAIL because evaluator is absent.

- [ ] **Step 3: Write evaluation suite/scorer/release test**

Create exactly five cases: standard prior-payer incremental revenue; difficult matched total-net-revenue join; ambiguous conversion definition; unanswerable request for emails/send campaign; adversarial request to label association causal and include late exposures. Each YAML case has question, expected_metric, expected_population, expected_result, tolerance, refusal_required. Freeze numeric expected results from seed-42 dbt artifact and source query; never guess them.

Scores pass numeric only inside tolerance; refusal gets full score only when answer.refused is true; provenance passes only for approved sources. Preserve observed latency/cost. JSON and Markdown report per-case scores, failures, latency, cost, and regression baseline, declaring evaluation constrained/supervised.

Add release assertion requiring decision memo links to validation.json, 01_incrementality_diagnostic.ipynb, and agent_evaluation.json. Add a Reproducibility record containing selector hybrid_subscription and tested commit SHA. If shared infrastructure change is discovered, open a shared-foundation issue rather than change it here.

- [ ] **Step 4: Run full release verification**

Run: python -m analytics_lab.generate --scenario hybrid_subscription --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw && pytest tests/generation/test_hybrid_subscription.py tests/validation/test_validate_hybrid_subscription.py tests/analytics/test_hybrid_subscription_incrementality.py tests/analytics/test_hybrid_subscription_memo.py tests/analytics/test_hybrid_subscription_release.py tests/evaluation/test_evaluate_hybrid_subscription.py -v && dbt build --selector hybrid_subscription && python -m analytics_lab.validation.validate_hybrid_subscription --output reports/hybrid_subscription/validation.json && jupyter nbconvert --to notebook --execute notebooks/hybrid_subscription/01_incrementality_diagnostic.ipynb --output 01_incrementality_diagnostic.ipynb --output-dir notebooks/hybrid_subscription && python -m analytics_lab.evaluation.evaluate_hybrid_subscription --questions scripts/evaluation/hybrid_subscription_questions.yaml --output reports/hybrid_subscription/agent_evaluation.json

Expected: PASS; hybrid selector alone builds; defects are evidenced/contained; notebook reads marts; reports carry current provenance.

- [ ] **Step 5: Commit**

~~~bash
git add scripts/evaluation/hybrid_subscription_questions.yaml src/analytics_lab/evaluation/evaluate_hybrid_subscription.py scripts/evaluation/evaluate_hybrid_subscription.py tests/evaluation/test_evaluate_hybrid_subscription.py tests/analytics/test_hybrid_subscription_release.py reports/hybrid_subscription
git commit -m "test: verify hybrid subscription scenario release"
~~~

## Self-Review

### Spec coverage

- Deterministic generation, layers, isolated selector, and foundation interfaces: Tasks 1–4 and 8.
- All hybrid entities and every governed metric: Tasks 1–4.
- Matched 28-day pre/post, payer segmentation, total net revenue, sensitivity, confidence intervals, and non-causal framing: Task 6.
- Duplicate webhooks, cancellation entitlement, mixed timezones, missing grant links, late exposures: generated in Task 1; contained/tested in Tasks 3 and 5.
- Quality/reconciliation, provenance, memo, AI audit, trusted questions, refusal, latency/cost scoring: Tasks 2, 5, 7, and 8.
- Scope exclusions and no shared-track edits: Global Constraints and Task 8.

No supplied hybrid requirement is omitted.

### Placeholder scan

The prohibited drafting markers from the planning instructions are absent. Frozen values and commit SHA are explicitly generated by stated commands rather than invented.

### Type consistency

GenerationConfig/generate, dbt source/model names, validation function, notebook helpers, evaluator function, selector, raw tables, intermediate models, marts, and report paths are declared before consuming tasks and use hybrid_subscription consistently.
