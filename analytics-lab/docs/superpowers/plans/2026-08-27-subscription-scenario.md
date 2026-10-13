# Consumer Subscription Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently executable consumer-subscription analytics scenario that deterministically generates evidence, publishes governed subscription metrics, contains designed data failures, and supports an auditable trial-conversion investigation.

**Architecture:** The scenario generator writes seven raw Parquet entities plus a deterministic quality-control table beneath `data/raw/subscription/`; raw records are immutable evidence, including deliberately bad records. Subscription-specific dbt staging standardizes and deduplicates records, intermediate models reconstruct trial and paid entitlement state, and marts expose a daily user-state fact, financial facts, diagnostic cohorts, and daily KPIs. The notebook, memo, AI audit, and trusted question set consume only approved marts and metric contracts.

**Tech Stack:** Python 3.12, pandas, pytest, DuckDB, dbt-duckdb, SQL, Jupyter, YAML, Markdown, Git.

**Spec:** `docs/superpowers/specs/2026-08-27-three-scenario-analytics-lab-design.md`

## Global Constraints

- Run locally on Apple Silicon with Python 3.12, DuckDB, dbt, and Git.
- Use the shared `GenerationConfig` from `src/analytics_lab/generation/base.py`: `scenario: str`, `seed: int`, `start_date: date`, `days: int`, `scale: int`, and `output_dir: Path`.
- Expose exactly `generate(config: GenerationConfig) -> dict[str, pandas.DataFrame]` from `src/analytics_lab/generation/subscription.py`.
- Generate via `python -m analytics_lab.generate --scenario subscription --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw`; use the shared `write_tables(tables: dict[str, DataFrame], output_dir: Path) -> list[Path]` Parquet writer.
- Keep the dbt selector and scenario name exactly `subscription`; do not modify shared package, configuration, macros, templates, or CI in this track.
- Keep raw records immutable: detect and contain duplicate webhooks, late cancellations, missing campaign identifiers, inconsistent activation names, and local-time trial ends downstream rather than rewriting raw evidence.
- Use UTC for modeled timestamps, retain the original timestamp and source timezone whenever conversion occurs, and include explicit local-time boundary tests.
- Publish a metric contract for signup-to-trial rate, trial-to-paid conversion, activation, trial activation, D30 paid retention, early paid churn, MRR, NRR, and CAC with eligibility, grain, exclusions, time rules, and known limitations.
- Make all models independently buildable with `dbt build --selector subscription`; use approved marts and metric contracts only in notebooks, reports, and agent evaluation.
- Do not include raw personal data, production writes, automatic publishing, messaging integrations, paid warehouses, or multi-agent analytics orchestration.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/analytics_lab/generation/subscription.py` | Deterministic generator for raw subscription entities and designed failures. |
| `tests/generation/test_subscription.py` | Generator determinism, referential-integrity, distribution, and invalid-config tests. |
| `game_analytics/seeds/subscription_event_name_map.csv` | Explicit mapping from raw activation aliases to canonical events. |
| `game_analytics/models/subscription/sources.yml` | Raw Parquet source registration and source-column documentation. |
| `game_analytics/models/subscription/stg_subscription__*.sql` | Typed, normalized, deduplicated staging models that retain raw evidence fields. |
| `game_analytics/models/subscription/int_subscription__*.sql` | Lifecycle reconstruction, cohort attribution, data-quality audit, and metric eligibility logic. |
| `game_analytics/models/subscription/dim_subscription__*.sql` | Conformed user and campaign dimensions. |
| `game_analytics/models/subscription/fct_subscription__*.sql` | Daily user state, payments, and marketing-spend facts. |
| `game_analytics/models/subscription/mart_subscription__*.sql` | Governed KPI and diagnostic cohort outputs. |
| `game_analytics/models/subscription/schema.yml` | Scenario model contracts, dbt tests, descriptions, and selector tags. |
| `game_analytics/tests/subscription_*.sql` | SQL tests for lifecycle, maturity, timezone, reconciliation, and designed-failure containment. |
| `docs/metrics/subscription/*.md` | One metric contract per governed metric. |
| `docs/incidents/subscription/2026-08-27-subscription-data-quality.md` | Detection, impact, containment, and evidence for the five intentional failures. |
| `notebooks/subscription/trial_to_paid_diagnostic.ipynb` | Reproducible flagship diagnostic using approved marts. |
| `reports/subscription/trial_to_paid_decision_memo.md` | Decision-ready memo that distinguishes observations, inference, assumptions, uncertainty, and recommendations. |
| `docs/ai-audit/subscription/trial_to_paid_diagnostic.md` | AI work proposal, human validation, rejected output, correction, and provenance. |
| `scripts/evaluation/subscription_questions.yaml` | Trusted, difficult, ambiguous, unanswerable, and adversarial subscription questions. |
| `tests/evaluation/test_subscription_questions.py` | Schema and expected-result validation for the scenario question set. |

## Data Contract and Interfaces

The generator must return these exact table keys. Each key is written by the shared writer to `data/raw/subscription/<key>.parquet`:

| Table key | Required business key and required columns |
|---|---|
| `subscription_users` | `user_id`, `signup_at`, `country_code`, `platform`, `campaign_id`, `acquisition_channel` |
| `subscription_onboarding_events` | `onboarding_event_id`, `user_id`, `event_name`, `occurred_at`, `ingested_at` |
| `subscription_product_events` | `product_event_id`, `user_id`, `event_name`, `occurred_at`, `ingested_at` |
| `subscription_lifecycle_events` | `webhook_id`, `subscription_id`, `user_id`, `event_type`, `occurred_at`, `effective_at`, `ingested_at`, `plan_id`, `billing_period`, `trial_end_at_reported_utc`, `trial_timezone` |
| `subscription_payments` | `payment_id`, `subscription_id`, `user_id`, `payment_at`, `amount_local`, `currency_code`, `amount_usd`, `payment_status`, `refund_at` |
| `subscription_marketing_spend` | `spend_id`, `spend_date`, `campaign_id`, `channel`, `country_code`, `spend_usd` |
| `subscription_support_tickets` | `ticket_id`, `user_id`, `created_at`, `ticket_category`, `ticket_status` |
| `subscription_generation_controls` | `control_name`, `expected_value`, `description` |

All subscription dbt model names carry the `subscription` tag. The public scenario interfaces created by this plan are:

```text
stg_subscription__subscription_events
  -> one row per webhook_id after deterministic duplicate selection;
     includes source_webhook_duplicate_count, raw_trial_end_at_reported_utc,
     trial_timezone, and trial_end_at_utc.

int_subscription__subscription_periods
  -> one row per subscription_id and contiguous entitlement interval;
     columns: subscription_id, user_id, period_start_at, period_end_at,
     scheduled_trial_end_at, paid_start_at, cancellation_effective_at,
     auto_renew_enabled, lifecycle_status, plan_id, monthly_recurring_revenue_usd.

fct_subscription__daily_user_state
  -> one row per user_id and calendar_date;
     columns: user_id, calendar_date, is_signed_up, is_trial_eligible,
     is_trial_active, is_paid_active, is_activated, campaign_id,
     monthly_recurring_revenue_usd.

mart_subscription__kpis_daily
  -> one row per metric_date; includes each governed numerator, denominator,
     rate/value, unknown_campaign_share, and data_quality_status.

mart_subscription__trial_conversion_diagnostic
  -> one row per mature trial cohort_date, acquisition_channel, campaign_id,
     plan_id, and activation_segment, with eligible_trials, paid_conversions,
     trial_to_paid_rate, payment_failure_trials, and maturity_cutoff_date.
```

### Task 1: Define and test the deterministic raw subscription generator

**Files:**
- Create: `src/analytics_lab/generation/subscription.py`
- Create: `tests/generation/test_subscription.py`

**Interfaces:**
- Consumes: `GenerationConfig` from `analytics_lab.generation.base`; the shared CLI persists returned frames through `write_tables` from `analytics_lab.generation.io`.
- Produces: `generate(config: GenerationConfig) -> dict[str, pandas.DataFrame]` with the eight table keys in the data contract; invalid `scenario`, non-positive `days`, or non-positive `scale` raises `ValueError`.

- [ ] **Step 1: Write the failing generator tests**

```python
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.subscription import generate


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig("subscription", seed, date(2026, 1, 1), 180, 1000, Path("data/raw"))


def test_generate_is_deterministic_for_the_same_config() -> None:
    first = generate(config())
    second = generate(config())
    assert set(first) == {
        "subscription_users", "subscription_onboarding_events", "subscription_product_events",
        "subscription_lifecycle_events", "subscription_payments", "subscription_marketing_spend",
        "subscription_support_tickets", "subscription_generation_controls",
    }
    for table_name in first:
        pd.testing.assert_frame_equal(first[table_name], second[table_name])


def test_generated_foreign_keys_and_designed_failure_evidence_are_present() -> None:
    tables = generate(config())
    users = set(tables["subscription_users"].user_id)
    controls = tables["subscription_generation_controls"].set_index("control_name").expected_value
    assert set(tables["subscription_lifecycle_events"].user_id) <= users
    assert set(tables["subscription_payments"].user_id) <= users
    assert (tables["subscription_lifecycle_events"].duplicated("webhook_id").sum() > 0)
    assert tables["subscription_users"].campaign_id.isna().any()
    assert set(tables["subscription_product_events"].event_name) >= {
        "activation_completed", "activated", "onboarding_complete"
    }
    assert 0.15 <= float(controls["trial_start_rate"]) <= 0.21
    assert float(controls["duplicate_webhook_rows"]) > 0
    assert float(controls["late_cancellation_rows"]) > 0
    assert float(controls["payment_failure_trial_rate"]) >= 0.03


def test_invalid_generator_config_fails_loudly() -> None:
    with pytest.raises(ValueError, match="days must be positive"):
        generate(GenerationConfig("subscription", 42, date(2026, 1, 1), 0, 1000, Path("data/raw")))
```

- [ ] **Step 2: Run the generator tests to verify they fail**

Run: `pytest tests/generation/test_subscription.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'analytics_lab.generation.subscription'`.

- [ ] **Step 3: Implement deterministic entities, controls, and injected failures**

```python
def generate(config: GenerationConfig) -> dict[str, pd.DataFrame]:
    if config.scenario != "subscription":
        raise ValueError("scenario must be subscription")
    if config.days <= 0:
        raise ValueError("days must be positive")
    if config.scale <= 0:
        raise ValueError("scale must be positive")
    rng = np.random.default_rng(config.seed)
    # Build users first; every later user_id and subscription_id is derived from these rows.
    # Emit duplicate lifecycle webhook rows, late effective cancellations, null campaign_id,
    # all three activation aliases, and local-time trial-end values labelled as UTC.
    # Build subscription_generation_controls from the emitted frames, not hard-coded counts.
    return tables
```

Implement each required table with stable column order, sorted by its business key and timestamp before returning it. Create 18% trials, 32% mature paid conversion among pre-decline cohorts, 27% among post-decline cohorts, and at least 3% payment-failure trials; record those realized rates and duplicate counts in `subscription_generation_controls`. Model cancellations with a later `ingested_at` than `effective_at`, while retaining both timestamps. Generate only synthetic IDs and non-identifying categorical attributes.

- [ ] **Step 4: Run the generator tests and write a representative raw dataset**

Run: `pytest tests/generation/test_subscription.py -v && python -m analytics_lab.generate --scenario subscription --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw`

Expected: all three tests PASS and eight files exist under `data/raw/subscription/`.

- [ ] **Step 5: Commit the independently testable generator**

```bash
git add src/analytics_lab/generation/subscription.py tests/generation/test_subscription.py
git commit -m "feat(subscription): add deterministic raw data generator"
```

### Task 2: Register raw sources and canonicalize staged evidence

**Files:**
- Create: `game_analytics/seeds/subscription_event_name_map.csv`
- Create: `game_analytics/models/subscription/sources.yml`
- Create: `game_analytics/models/subscription/stg_subscription__users.sql`
- Create: `game_analytics/models/subscription/stg_subscription__onboarding_events.sql`
- Create: `game_analytics/models/subscription/stg_subscription__product_events.sql`
- Create: `game_analytics/models/subscription/stg_subscription__subscription_events.sql`
- Create: `game_analytics/models/subscription/stg_subscription__payments.sql`
- Create: `game_analytics/models/subscription/stg_subscription__marketing_spend.sql`
- Create: `game_analytics/models/subscription/stg_subscription__support_tickets.sql`
- Create: `game_analytics/models/subscription/schema.yml`

**Interfaces:**
- Consumes: generated Parquet tables, shared `dim_dates` calendar model, and dbt's `source()` and `ref()` interfaces.
- Produces: seven typed `stg_subscription__*` relations; `stg_subscription__subscription_events` selects the greatest `ingested_at` row per `webhook_id`, and retains a duplicate count; `stg_subscription__product_events` exposes `canonical_event_name` and `is_activation_event`.

- [ ] **Step 1: Write failing dbt source and staging contract tests**

Add the following model-test declarations to `schema.yml` before writing the models:

```yaml
version: 2
models:
  - name: stg_subscription__users
    config: {tags: [subscription]}
    columns:
      - name: user_id
        tests: [not_null, unique]
      - name: signup_at
        tests: [not_null]
  - name: stg_subscription__subscription_events
    config: {tags: [subscription]}
    columns:
      - name: webhook_id
        tests: [not_null, unique]
      - name: event_type
        tests:
          - accepted_values: {values: [trial_started, trial_ended, paid_started, renewed, cancelled, expired]}
      - name: user_id
        tests:
          - relationships: {to: ref('stg_subscription__users'), field: user_id}
  - name: stg_subscription__product_events
    config: {tags: [subscription]}
    columns:
      - name: canonical_event_name
        tests: [not_null]
```

- [ ] **Step 2: Run the contracts to verify they fail before sources and models exist**

Run: `dbt build --selector subscription`

Expected: FAIL because the referenced staging relations do not exist.

- [ ] **Step 3: Implement source registration, activation mapping, and lossless staging**

Use this exact activation mapping seed, including all intentional aliases:

```csv
raw_event_name,canonical_event_name,is_activation_event
activation_completed,activation_completed,true
activated,activation_completed,true
onboarding_complete,activation_completed,true
screen_view,screen_view,false
feature_used,feature_used,false
```

Implement `stg_subscription__subscription_events.sql` with deterministic deduplication and conversion of the falsely-labelled local timestamp:

```sql
with ranked as (
  select *,
    count(*) over (partition by webhook_id) as source_webhook_duplicate_count,
    row_number() over (partition by webhook_id order by ingested_at desc, occurred_at desc) as duplicate_rank
  from {{ source('subscription_raw', 'subscription_lifecycle_events') }}
)
select
  webhook_id, subscription_id, user_id, event_type,
  cast(occurred_at as timestamp) as occurred_at,
  cast(effective_at as timestamp) as effective_at,
  cast(ingested_at as timestamp) as ingested_at,
  trial_end_at_reported_utc as raw_trial_end_at_reported_utc,
  trial_timezone,
  timezone('UTC', timezone(trial_timezone, cast(trial_end_at_reported_utc as timestamp))) as trial_end_at_utc,
  source_webhook_duplicate_count, plan_id, billing_period
from ranked
where duplicate_rank = 1
```

Implement equivalent explicit `cast`/rename models for the other six sources. For product events, left join the seed by `event_name` and set `is_activation_event` from the seed; use `coalesce(canonical_event_name, 'unmapped')` to preserve unexpected evidence without silently treating it as activation. Document every raw field and its intended failure in `sources.yml`; do not add uniqueness tests to the raw lifecycle source because duplicates are intentionally expected there.

- [ ] **Step 4: Run the staging contracts**

Run: `dbt seed --select subscription_event_name_map && dbt build --selector subscription`

Expected: PASS; the staged lifecycle relation has unique `webhook_id` while retaining a positive `source_webhook_duplicate_count` for known duplicate evidence.

- [ ] **Step 5: Commit the raw-to-staging boundary**

```bash
git add game_analytics/seeds/subscription_event_name_map.csv game_analytics/models/subscription
git commit -m "feat(subscription): stage raw lifecycle and product evidence"
```

### Task 3: Reconstruct lifecycle state, cohorts, attribution, and quality audit

**Files:**
- Create: `game_analytics/models/subscription/int_subscription__activation_events.sql`
- Create: `game_analytics/models/subscription/int_subscription__subscription_periods.sql`
- Create: `game_analytics/models/subscription/int_subscription__trial_cohorts.sql`
- Create: `game_analytics/models/subscription/int_subscription__paid_cohorts.sql`
- Create: `game_analytics/models/subscription/int_subscription__campaign_attribution.sql`
- Create: `game_analytics/models/subscription/int_subscription__quality_audit.sql`
- Create: `game_analytics/tests/subscription_no_overlapping_entitlements.sql`
- Create: `game_analytics/tests/subscription_trial_end_is_normalized_to_utc.sql`
- Modify: `game_analytics/models/subscription/schema.yml`

**Interfaces:**
- Consumes: the seven `stg_subscription__*` models and `dim_dates`.
- Produces: `int_subscription__activation_events(user_id, activation_at)`, `int_subscription__subscription_periods` as specified in Data Contract and Interfaces, trial and paid cohort relations with `cohort_date`, campaign attribution with `campaign_id`, `attribution_status`, and a one-row `int_subscription__quality_audit` with five non-negative incident counters.

- [ ] **Step 1: Write failing custom business-rule tests**

```sql
-- game_analytics/tests/subscription_no_overlapping_entitlements.sql
with ordered as (
  select subscription_id, period_start_at, period_end_at,
    lag(period_end_at) over (partition by subscription_id order by period_start_at) as prior_end_at
  from {{ ref('int_subscription__subscription_periods') }}
)
select * from ordered where prior_end_at > period_start_at
```

```sql
-- game_analytics/tests/subscription_trial_end_is_normalized_to_utc.sql
select *
from {{ ref('stg_subscription__subscription_events') }}
where event_type = 'trial_started'
  and trial_timezone <> 'UTC'
  and trial_end_at_utc = cast(raw_trial_end_at_reported_utc as timestamp)
```

- [ ] **Step 2: Run the intermediate tests to verify they fail**

Run: `dbt test --selector subscription --select subscription_no_overlapping_entitlements subscription_trial_end_is_normalized_to_utc`

Expected: FAIL because `int_subscription__subscription_periods` has not been created.

- [ ] **Step 3: Implement canonical state and failure containment**

```sql
-- int_subscription__activation_events.sql
select user_id, min(occurred_at) as activation_at
from {{ ref('stg_subscription__product_events') }}
where is_activation_event
group by 1
```

Implement subscription periods by ordering canonical lifecycle events per `subscription_id`, using `effective_at` for state transitions and only `ingested_at` to measure lateness. A `cancelled` event sets `auto_renew_enabled = false` but preserves entitlement through the next `expired` event or scheduled paid-period end. Split each subscription into non-overlapping trial and paid intervals; calculate monthly recurring revenue as the paid plan price for `monthly` and annual price divided by 12 for `annual`. Do not infer an immediate loss of entitlement from cancellation.

Build trial cohorts from `trial_started`, set `maturity_cutoff_date = trial_start_at::date + 21 days`, and set `is_mature` only when that date is on or before the maximum modeled calendar date. Build paid cohorts from the first paid entitlement. Attribute a user to their signup campaign when non-null; otherwise use `campaign_id = 'unknown'` and `attribution_status = 'missing_campaign'` so CAC can exclude it explicitly. Build a quality-audit row with `duplicate_webhook_rows`, `late_cancellation_rows`, `missing_campaign_users`, `unmapped_activation_events`, and `local_time_trial_end_rows`, each calculated directly from staged evidence.

- [ ] **Step 4: Run the intermediate build and tests**

Run: `dbt build --selector subscription`

Expected: PASS; quality audit reports positive values for all five deliberately injected failure categories.

- [ ] **Step 5: Commit lifecycle reconstruction**

```bash
git add game_analytics/models/subscription/int_subscription__*.sql game_analytics/models/subscription/schema.yml game_analytics/tests/subscription_no_overlapping_entitlements.sql game_analytics/tests/subscription_trial_end_is_normalized_to_utc.sql
git commit -m "feat(subscription): reconstruct lifecycle cohorts and quality audit"
```

### Task 4: Publish dimensions, governed facts, and KPI marts

**Files:**
- Create: `game_analytics/models/subscription/dim_subscription__users.sql`
- Create: `game_analytics/models/subscription/dim_subscription__campaigns.sql`
- Create: `game_analytics/models/subscription/fct_subscription__daily_user_state.sql`
- Create: `game_analytics/models/subscription/fct_subscription__payments.sql`
- Create: `game_analytics/models/subscription/fct_subscription__marketing_spend_daily.sql`
- Create: `game_analytics/models/subscription/mart_subscription__kpis_daily.sql`
- Create: `game_analytics/models/subscription/mart_subscription__trial_conversion_diagnostic.sql`
- Create: `game_analytics/tests/subscription_daily_user_state_has_one_row_per_user_date.sql`
- Create: `game_analytics/tests/subscription_mrr_reconciles_to_active_paid_state.sql`
- Modify: `game_analytics/models/subscription/schema.yml`

**Interfaces:**
- Consumes: intermediate cohort, lifecycle, attribution, activation, quality-audit relations and `dim_dates`.
- Produces: the public `fct_subscription__daily_user_state`, `mart_subscription__kpis_daily`, and `mart_subscription__trial_conversion_diagnostic` interfaces defined above; one `fct_subscription__payments` row per `payment_id` and one `fct_subscription__marketing_spend_daily` row per spend date/campaign/country.

- [ ] **Step 1: Write failing mart grain and reconciliation tests**

```sql
-- game_analytics/tests/subscription_daily_user_state_has_one_row_per_user_date.sql
select user_id, calendar_date
from {{ ref('fct_subscription__daily_user_state') }}
group by 1, 2
having count(*) > 1
```

```sql
-- game_analytics/tests/subscription_mrr_reconciles_to_active_paid_state.sql
with expected as (
  select calendar_date, sum(monthly_recurring_revenue_usd) as expected_mrr
  from {{ ref('fct_subscription__daily_user_state') }}
  where is_paid_active
  group by 1
)
select k.metric_date, k.mrr_usd, e.expected_mrr
from {{ ref('mart_subscription__kpis_daily') }} k
join expected e on k.metric_date = e.calendar_date
where abs(k.mrr_usd - e.expected_mrr) > 0.01
```

- [ ] **Step 2: Run the mart tests to verify they fail**

Run: `dbt test --selector subscription --select subscription_daily_user_state_has_one_row_per_user_date subscription_mrr_reconciles_to_active_paid_state`

Expected: FAIL because the fact and KPI mart do not exist.

- [ ] **Step 3: Implement fact grains and governed formulas**

Generate daily state by joining each user to `dim_dates` from `signup_at::date` through the maximum calendar date. Mark trial and paid state by whether `calendar_date` is inside an entitlement interval. Set activation only when `activation_at` is on or before the date and no later than seven days after signup. Build payment facts using successful, non-refunded payments for recognized gross revenue and preserve failed/refunded records with explicit status flags.

Implement the following exact daily KPI rules in `mart_subscription__kpis_daily.sql`:

| Metric | Numerator | Denominator / eligibility |
|---|---|---|
| Signup-to-trial rate | signups whose first trial begins within 7 days | signups on `metric_date` |
| Activation rate | signups with activation within 7 days | signups on `metric_date` |
| Trial activation | mature trials with activation on/before scheduled trial end | mature trial starts on `metric_date` |
| Trial-to-paid conversion | mature trials with first paid entitlement within 3 days after scheduled trial end | mature trial starts on `metric_date` |
| D30 paid retention | first paid cohorts paid-active on day 30 | paid starts exactly 30 days earlier |
| Early paid churn | first paid cohorts whose effective cancellation is within 30 days | paid starts on `metric_date` |
| MRR | sum monthly recurring revenue for paid-active state | not applicable |
| NRR | current MRR from the paid cohort at the start of the reporting month, net of churn, divided by that cohort's starting MRR | cohorts with positive starting MRR |
| CAC | tracked campaign spend | newly paid users attributed to a non-unknown campaign |

Set conversion-related values to `null` rather than zero where the cohort is not mature. Include `unknown_campaign_share` and a `data_quality_status` of `review_required` whenever the daily quality audit has any positive incident count; the scenario remains publishable because the canonical stage contains the bad raw evidence.

The diagnostic mart must use only mature trials and group by `cohort_date`, `acquisition_channel`, `campaign_id`, `plan_id`, and `activation_segment` (`activated_before_trial_end` or `not_activated_before_trial_end`). It must quantify payment-failure trials separately rather than reclassifying them as onboarding failure.

- [ ] **Step 4: Run scenario build and fact/mart contracts**

Run: `dbt build --selector subscription`

Expected: PASS; the daily-state fact is unique on `(user_id, calendar_date)` and MRR reconciles to paid-active state to within USD 0.01.

- [ ] **Step 5: Commit governed data products**

```bash
git add game_analytics/models/subscription/dim_subscription__*.sql game_analytics/models/subscription/fct_subscription__*.sql game_analytics/models/subscription/mart_subscription__*.sql game_analytics/models/subscription/schema.yml game_analytics/tests/subscription_daily_user_state_has_one_row_per_user_date.sql game_analytics/tests/subscription_mrr_reconciles_to_active_paid_state.sql
git commit -m "feat(subscription): publish governed facts and KPI marts"
```

### Task 5: Make metric definitions and designed-failure handling reviewable

**Files:**
- Create: `docs/metrics/subscription/signup_to_trial_rate.md`
- Create: `docs/metrics/subscription/trial_to_paid_conversion.md`
- Create: `docs/metrics/subscription/activation.md`
- Create: `docs/metrics/subscription/trial_activation.md`
- Create: `docs/metrics/subscription/d30_paid_retention.md`
- Create: `docs/metrics/subscription/early_paid_churn.md`
- Create: `docs/metrics/subscription/mrr.md`
- Create: `docs/metrics/subscription/nrr.md`
- Create: `docs/metrics/subscription/cac.md`
- Create: `docs/incidents/subscription/2026-08-27-subscription-data-quality.md`
- Create: `tests/validation/test_subscription_metric_contracts.py`

**Interfaces:**
- Consumes: `mart_subscription__kpis_daily`, `mart_subscription__trial_conversion_diagnostic`, and `int_subscription__quality_audit`.
- Produces: nine human-readable metric contracts containing `Owner`, `Source model`, `Grain`, `Eligibility`, `Formula`, `Exclusions`, `Time rule`, `Known limitations`, and `Validation query`; one incident record with `Detection`, `Impact`, `Containment`, and `Raw evidence retained` sections.

- [ ] **Step 1: Write the failing documentation-contract test**

```python
from pathlib import Path


REQUIRED = {"Owner", "Source model", "Grain", "Eligibility", "Formula", "Exclusions", "Time rule", "Known limitations", "Validation query"}


def test_subscription_metric_contracts_are_complete() -> None:
    contracts = list(Path("docs/metrics/subscription").glob("*.md"))
    assert len(contracts) == 9
    for contract in contracts:
        text = contract.read_text()
        assert all(f"## {heading}" in text for heading in REQUIRED), contract
```

- [ ] **Step 2: Run the documentation-contract test to verify it fails**

Run: `pytest tests/validation/test_subscription_metric_contracts.py -v`

Expected: FAIL because no subscription metric contracts exist.

- [ ] **Step 3: Write complete contracts and the incident record**

Use this concrete structure in every metric contract and replace the bracketed metric-specific values with the exact rules from Task 4:

```markdown
# Trial-to-Paid Conversion

## Owner
Consumer Subscription Analytics

## Source model
`mart_subscription__kpis_daily` and `mart_subscription__trial_conversion_diagnostic`

## Grain
Mature trial cohort date; diagnostic dimensions are campaign, channel, plan, and activation segment.

## Eligibility
Trial starts with `maturity_cutoff_date <= max(calendar_date)`.

## Formula
Eligible trials with first paid entitlement no later than three days after scheduled trial end divided by eligible trials.

## Exclusions
Immature cohorts; duplicate lifecycle webhooks after canonical selection; trials without a valid trial-start event.

## Time rule
Trial end uses `trial_end_at_utc`, reconstructed from the recorded local value and `trial_timezone`.

## Known limitations
The scenario uses synthetic attribution and observes association, not causal effect, across acquisition channels.

## Validation query
`select metric_date, trial_to_paid_conversion from mart_subscription__kpis_daily order by metric_date;`
```

Write the incident document with a separate subsection for each designed failure. State the raw table and detector, the affected downstream metric or interpretation, the exact containment (`latest ingested webhook per webhook_id`; `effective_at` for lifecycle; `unknown` attribution bucket; event mapping seed; timezone reconstruction), and why raw records are not changed. Include a query for each detector against the named staging or intermediate model.

- [ ] **Step 4: Run documentation validation and a quality-audit query**

Run: `pytest tests/validation/test_subscription_metric_contracts.py -v && dbt show --select int_subscription__quality_audit --limit 1`

Expected: PASS; the audit output has positive counters for all five designed failures and documents containment without hiding the evidence.

- [ ] **Step 5: Commit governance artifacts**

```bash
git add docs/metrics/subscription docs/incidents/subscription tests/validation/test_subscription_metric_contracts.py
git commit -m "docs(subscription): define metrics and incident containment"
```

### Task 6: Build the reproducible flagship diagnostic and decision memo

**Files:**
- Create: `notebooks/subscription/trial_to_paid_diagnostic.ipynb`
- Create: `reports/subscription/trial_to_paid_decision_memo.md`
- Create: `docs/ai-audit/subscription/trial_to_paid_diagnostic.md`
- Create: `tests/validation/test_subscription_diagnostic_artifacts.py`

**Interfaces:**
- Consumes: `mart_subscription__trial_conversion_diagnostic`, `mart_subscription__kpis_daily`, `fct_subscription__payments`, the nine metric contracts, and `int_subscription__quality_audit` through the DuckDB dbt target.
- Produces: notebook cells with `source_models`, `execution_date`, `filters`, and `code_version`; a memo with the required decision sections; an AI audit trail that records a rejected claim and its human correction.

- [ ] **Step 1: Write the failing diagnostic-artifact test**

```python
from pathlib import Path


def test_subscription_diagnostic_artifacts_are_auditable() -> None:
    notebook = Path("notebooks/subscription/trial_to_paid_diagnostic.ipynb").read_text()
    memo = Path("reports/subscription/trial_to_paid_decision_memo.md").read_text()
    audit = Path("docs/ai-audit/subscription/trial_to_paid_diagnostic.md").read_text()
    for token in ["source_models", "execution_date", "filters", "code_version", "maturity_cutoff_date"]:
        assert token in notebook
    for heading in ["## Observed facts", "## Inference", "## Assumptions and uncertainty", "## Recommendation"]:
        assert heading in memo
    for heading in ["## Proposed work", "## Human validation", "## Rejected output", "## Correction", "## Provenance"]:
        assert heading in audit
```

- [ ] **Step 2: Run the artifact test to verify it fails**

Run: `pytest tests/validation/test_subscription_diagnostic_artifacts.py -v`

Expected: FAIL because the notebook, memo, and audit trail do not exist.

- [ ] **Step 3: Implement the notebook, memo, and AI review record**

Make the first notebook code cell declare the reproducibility record and query only marts/facts:

```python
from datetime import datetime, timezone
import subprocess

source_models = [
    "mart_subscription__trial_conversion_diagnostic",
    "mart_subscription__kpis_daily",
    "fct_subscription__payments",
    "int_subscription__quality_audit",
]
execution_date = datetime.now(timezone.utc).isoformat()
filters = {"mature_trials_only": True, "conversion_window_days": 3}
code_version = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
```

The notebook must calculate the mature trial-to-paid decline in percentage points, decomposition views by acquisition channel/campaign, onboarding activation segment, payment-failure status, plan, and cohort maturity. Include a weighted standardized-rate comparison that holds the pre-decline channel mix fixed, and a sensitivity table using 2-day, 3-day, and 7-day conversion windows. Visualize rates with binomial 95% confidence intervals, label association as non-causal, and show the quality-audit counts beside conclusions.

The memo must name the dataset date range and code version, state observed facts separately from inference, quantify each factor's share or explicitly say it cannot be identified, state that payment failures are not onboarding failures, and recommend one measurement repair plus one reversible product/checkout experiment. Its uncertainty section must cover synthetic data, cohort maturity, unobserved acquisition quality, local-time repair, and non-causal decomposition.

The AI audit must show a proposed decomposition query, a human validation that checks the metric contract and join grain, one rejected statement that claimed the onboarding change caused conversion loss, the corrected association-only language, and provenance listing the source models, run date, reviewer, and commit SHA.

- [ ] **Step 4: Execute the notebook and validate its artifacts**

Run: `jupyter nbconvert --to notebook --execute notebooks/subscription/trial_to_paid_diagnostic.ipynb --output trial_to_paid_diagnostic.executed.ipynb --ExecutePreprocessor.timeout=120 && pytest tests/validation/test_subscription_diagnostic_artifacts.py -v`

Expected: notebook execution succeeds using the local DuckDB target and the artifact test PASSes.

- [ ] **Step 5: Commit the analysis package**

```bash
git add notebooks/subscription/trial_to_paid_diagnostic.ipynb reports/subscription/trial_to_paid_decision_memo.md docs/ai-audit/subscription/trial_to_paid_diagnostic.md tests/validation/test_subscription_diagnostic_artifacts.py
git commit -m "feat(subscription): add trial conversion diagnostic and memo"
```

### Task 7: Add trusted agent-evaluation questions and run the scenario gate

**Files:**
- Create: `scripts/evaluation/subscription_questions.yaml`
- Create: `tests/evaluation/test_subscription_questions.py`
- Modify: `game_analytics/models/subscription/schema.yml`

**Interfaces:**
- Consumes: the shared evaluator schema with `question`, `expected_metric`, `expected_population`, `expected_result`, `tolerance`, `refusal_requirement`, `latency`, and `cost`; approved metric contracts and marts.
- Produces: a valid `subscription_questions.yaml` with five question classes (`standard`, `difficult`, `ambiguous`, `unanswerable`, `adversarial`) and expected numeric or refusal outcomes, plus final dbt source-to-mart contracts.

- [ ] **Step 1: Write the failing question-set validator**

```python
from pathlib import Path

import yaml


REQUIRED = {"question", "expected_metric", "expected_population", "expected_result", "tolerance", "refusal_requirement", "latency", "cost"}


def test_subscription_question_set_covers_required_question_classes() -> None:
    questions = yaml.safe_load(Path("scripts/evaluation/subscription_questions.yaml").read_text())["questions"]
    assert {q["class"] for q in questions} == {"standard", "difficult", "ambiguous", "unanswerable", "adversarial"}
    assert all(REQUIRED <= set(q) for q in questions)
    assert all(q["expected_metric"] in {"signup_to_trial_rate", "trial_to_paid_conversion", "mrr", "cac", "refusal"} for q in questions)
```

- [ ] **Step 2: Run the evaluator validator to verify it fails**

Run: `pytest tests/evaluation/test_subscription_questions.py -v`

Expected: FAIL because the subscription question set does not exist.

- [ ] **Step 3: Create grounded trusted questions and complete final contracts**

Create five YAML entries. Include: a standard MRR question with a numeric result generated from `mart_subscription__kpis_daily`; a difficult mature trial-conversion question requiring the three-day window and maturity exclusion; an ambiguous CAC question that must state the campaign-attribution limitation; an unanswerable request for an individual user's raw data with `expected_metric: refusal` and `refusal_requirement: true`; and an adversarial prompt asking the agent to treat a cancellation as immediate entitlement loss with a refusal/correction expectation. Set numeric expected results by querying the seeded 180-day data at seed 42 and choose explicit tolerances no wider than 0.01 for money and 0.001 for rates. Set latency and cost ceilings using the shared evaluator's units.

Add `not_null`, `unique`, and relationship tests in `schema.yml` for every business key introduced in Tasks 3–4. Add accepted-values tests for `attribution_status` (`tracked`, `missing_campaign`), `activation_segment` (`activated_before_trial_end`, `not_activated_before_trial_end`), and `data_quality_status` (`review_required`, `clear`).

- [ ] **Step 4: Run validation, dbt integration, and the constrained evaluator**

Run: `pytest tests/generation/test_subscription.py tests/validation/test_subscription_metric_contracts.py tests/validation/test_subscription_diagnostic_artifacts.py tests/evaluation/test_subscription_questions.py -v && dbt build --selector subscription && python -m analytics_lab.evaluate --scenario subscription --questions scripts/evaluation/subscription_questions.yaml`

Expected: all Python and dbt tests PASS; the evaluator records metric, population, join logic, numeric-result tolerance, uncertainty/refusal, provenance, latency, and cost scores without accessing raw data.

- [ ] **Step 5: Commit the evaluation gate**

```bash
git add scripts/evaluation/subscription_questions.yaml tests/evaluation/test_subscription_questions.py game_analytics/models/subscription/schema.yml
git commit -m "test(subscription): add trusted analytical evaluation"
```

## Self-Review

**Spec coverage:** Task 1 satisfies deterministic synthetic generation, configured scale, all subscription entities, and the five designed failures. Tasks 2–4 implement raw, staging, intermediate, mart layers; UTC/local-time handling; lifecycle reconstruction; source and business-rule contracts; independently selectable dbt builds; all nine governed metrics; and revenue/user reconciliation. Task 5 documents metric eligibility, grain, exclusions, time rules, limitations, and incidents without changing raw evidence. Task 6 supplies the mature-conversion diagnostic, sensitivity/uncertainty analysis, decision memo, and supervised AI audit trail. Task 7 covers standard through adversarial agent questions and evaluator scoring. Scope exclusions and shared-foundation ownership are stated in Global Constraints. No requirements are uncovered.

**Placeholder scan:** The plan contains no `TBD`, `TODO`, `implement later`, unspecified error-handling instructions, or unfilled template values. Runtime provenance is populated by executable Python in Task 6.

**Type consistency:** The generator interface, eight raw table keys, staging names, lifecycle-period columns, daily-state grain, KPI names, diagnostic dimensions, selector name, and evaluator fields are used consistently in all later tasks.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-27-subscription-scenario.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task and review between tasks for fast iteration.
2. **Inline Execution** — Execute tasks in one session using `superpowers:executing-plans`, in batches with review checkpoints.

Which approach?
