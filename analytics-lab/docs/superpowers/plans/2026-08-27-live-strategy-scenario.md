# Live Strategy Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independently executable live-strategy-game analytics scenario that deterministically diagnoses a post-season-update D7-retention decline while preserving and containing intentional data-quality failures.

**Architecture:** The scenario generator writes reproducible Parquet raw tables, including deliberately flawed evidence, beneath its own raw-data prefix. A `live_strategy` dbt subgraph normalizes those tables, retains row-level quality signals in intermediate/audit models, reconstructs time-valid business state, and publishes governed facts and KPI/cohort marts. A small, testable Python analysis layer reads only the marts for the retention decomposition; the notebook, memo, metric contracts, AI audit, and evaluation cases turn that result into auditable portfolio evidence.

**Tech Stack:** Python 3.12, pandas, pytest, DuckDB, dbt-core with dbt-duckdb, SQL, Jupyter (Jupytext percent-format notebook), Git.

**Spec:** `docs/superpowers/specs/2026-08-27-three-scenario-analytics-lab-design.md`

## Global Constraints

- This plan starts only after the shared foundation supplies the common package/configuration, generator conventions, dbt base project, templates, and CI; it must not alter those shared surfaces.
- Support native Apple Silicon local execution with Python 3.12, DuckDB, dbt, and Git.
- Use the shared `GenerationConfig` at `src/analytics_lab/generation/base.py` with fields `scenario: str`, `seed: int`, `start_date: date`, `days: int`, `scale: int`, and `output_dir: Path`.
- Expose `generate(config: GenerationConfig) -> dict[str, pandas.DataFrame]`; use the shared `write_tables(tables: dict[str, DataFrame], output_dir: Path) -> list[Path]` to write Parquet.
- Generate via `python -m analytics_lab.generate --scenario live_strategy --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw`; the dbt scenario selector/name is `live_strategy`.
- Use deterministic seeds, UTC timestamps, ISO currency fields, and the shared documented USD conversion assumption. Keep business-specific rules out of shared macros.
- Retain raw evidence. Expected bad records must be detected and excluded or qualified downstream, never silently rewritten or removed from raw/staging data.
- Define every governed metric’s eligibility, grain, exclusions, time rule, and known limitation. Do not use `DISTINCT` to conceal a fan-out.
- The diagnostic must separately quantify progression friction, Android instrumentation sensitivity, and acquisition-mix effects, state residual uncertainty, and not claim causality from descriptive data.
- Build and test this scenario independently with `dbt build --selector live_strategy`; production writes, automatic publishing, paid warehouses, raw personal data, fine-tuning, multi-agent orchestration, and autonomous decision-making are out of scope.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/analytics_lab/generation/live_strategy.py` | Deterministically construct the eleven raw scenario tables and validate scenario-specific configuration. |
| `tests/generation/test_live_strategy.py` | Unit tests for generator determinism, entity relationships, distributions, and injected failures. |
| `game_analytics/models/live_strategy/sources.yml` | Declare the raw Parquet sources and source-level descriptions for the scenario. |
| `game_analytics/models/live_strategy/staging/stg_live_strategy__*.sql` | One typed, renamed staging relation per raw table; no business-state repair. |
| `game_analytics/models/live_strategy/staging/live_strategy_staging.yml` | Staging model grain/column contracts and generic dbt tests. |
| `game_analytics/models/live_strategy/intermediate/int_live_strategy__*.sql` | Explicit deduplication, validity, refund reconciliation, configuration as-of joins, and quality-audit relations. |
| `game_analytics/models/live_strategy/marts/dim_live_strategy__*.sql` | Conformed live-strategy dimensions. |
| `game_analytics/models/live_strategy/marts/fct_live_strategy__*.sql` | Governed transaction, player-activity, session, progression, alliance, and participation facts. |
| `game_analytics/models/live_strategy/marts/mart_live_strategy__*.sql` | Daily KPI, cohort-retention, diagnostic-input, and data-quality-incident marts. |
| `game_analytics/models/live_strategy/marts/live_strategy_marts.yml` | Marts’ grain/column documentation, generic tests, and selector tags. |
| `game_analytics/tests/live_strategy/*.sql` | dbt singular tests for time boundaries, reconciliation, maturity, containment, and incident detection. |
| `docs/metrics/live_strategy.md` | Eleven governed metric contracts and their source model/limitations. |
| `docs/incidents/live_strategy.md` | Six intentional-incident records: detector, impact, containment, and raw-evidence policy. |
| `src/analytics_lab/analysis/live_strategy_retention.py` | Pure dataframe functions for standardization, instrumentation sensitivity, uncertainty intervals, and contribution accounting. |
| `tests/analysis/test_live_strategy_retention.py` | Hand-calculated tests for the diagnostic calculations and impossible-input guards. |
| `notebooks/live_strategy/01_d7_retention_diagnostic.py` | Jupytext percent-format, reproducible flagship analysis that invokes the tested analysis module. |
| `reports/live_strategy/d7_retention_diagnostic.md` | Decision memo populated from the reproducible diagnostic output and standard memo template. |
| `docs/ai-audit/live_strategy.md` | Scenario AI provenance: proposals, evidence reviewed, accepted/rejected outputs, and corrections. |
| `docs/ai-audit/live_strategy_questions.yaml` | Trusted, ambiguous, unanswerable, and adversarial agent-evaluation cases in the shared schema. |
| `tests/evaluation/test_live_strategy_questions.py` | Validates case schema, expected-result tolerances, required refusals, and approved-domain constraints. |
| `README.md` | Add a concise link to the completed Live Strategy case study without changing shared setup instructions. |

## Data Contracts and Public Interfaces

The generator must return exactly these DataFrame keys and write them as `data/raw/live_strategy/<key>.parquet` through the shared writer:

| Key | Grain and primary key | Required fields |
| --- | --- | --- |
| `players` | one row/player; `player_id` | `installed_at_utc`, `platform`, `country_code`, `acquisition_channel`, `install_app_version` |
| `sessions` | one row/session; `session_id` | `player_id`, `started_at_utc`, `ended_at_utc`, `app_version`, `platform` |
| `gameplay_events` | one row/client event arrival; `ingestion_event_id` | `client_event_id`, `player_id`, `session_id`, `occurred_at_utc`, `event_name`, `app_version`, `live_event_id` |
| `purchases` | one row/store purchase report; `purchase_id` | `player_id`, `purchased_at_utc`, `purchase_status`, `platform_transaction_id`, `product_id`, `gross_amount`, `currency_code`, `gross_usd` |
| `progression_snapshots` | one row/player/snapshot; `snapshot_id` | `player_id`, `snapshot_at_utc`, `level`, `power`, `upgrade_attempts`, `upgrade_successes` |
| `alliances` | one row/alliance; `alliance_id` | `created_at_utc`, `region`, `leader_player_id` |
| `alliance_memberships` | one row/membership interval; `membership_id` | `player_id`, `alliance_id`, `valid_from_utc`, `valid_to_utc`, `membership_status` |
| `live_events` | one row/live-event configuration; `live_event_id` | `event_name`, `starts_at_utc`, `ends_at_utc`, `season_id`, `reward_track` |
| `battles` | one row/battle; `battle_id` | `player_id`, `occurred_at_utc`, `opponent_type`, `outcome`, `power_delta` |
| `economy_transactions` | one row/ledger entry; `ledger_entry_id` | `player_id`, `occurred_at_utc`, `transaction_type`, `amount`, `currency_type`, `purchase_id` |
| `config_versions` | one row/effective configuration interval; `config_version_id` | `effective_from_utc`, `effective_to_utc`, `season_id`, `upgrade_cost_multiplier`, `event_reward_multiplier` |

All scenario dbt models carry `tags: ['live_strategy']`. The public model interfaces are:

| Relation | Grain | Contract used by later tasks |
| --- | --- | --- |
| `int_live_strategy__valid_gameplay_events` | one retained canonical event | `client_event_id`, `player_id`, `session_id`, `occurred_at_utc`, `event_name`, `app_version`, `live_event_id` |
| `int_live_strategy__session_quality` | one source session | `session_id`, `player_id`, `started_at_utc`, `ended_at_utc`, `duration_seconds`, `has_missing_end`, `has_invalid_duration` |
| `int_live_strategy__purchase_reconciliation` | one purchase | `purchase_id`, `player_id`, `final_purchase_status`, `gross_usd`, `refund_usd`, `net_usd`, `refund_reconciled_at_utc` |
| `int_live_strategy__event_config_attribution` | one valid canonical event | valid-event fields plus `config_version_id`, `season_id`, `upgrade_cost_multiplier`, `event_reward_multiplier` |
| `fct_live_strategy__player_activity_daily` | one active player/UTC date | `activity_date_utc`, `player_id`, `has_gameplay_event`, `has_session_start`, `activity_evidence` |
| `fct_live_strategy__purchases` | one reconciled purchase | purchase-reconciliation fields plus player dimensions at install |
| `mart_live_strategy__retention_cohorts` | one install-date/platform/country/channel/config version cohort | `install_date_utc`, `period`, `platform`, `country_code`, `acquisition_channel`, `config_version_id`, `eligible_d1_players`, `retained_d1_players`, `eligible_d7_players`, `retained_d7_players`, `d1_retention`, `d7_retention` |
| `mart_live_strategy__d7_diagnostic_inputs` | one cohort/retention-signal segment | all cohort dimensions plus `retention_signal`, `eligible_players`, `retained_players`, `retention_rate`, `median_upgrade_attempts`, `median_progression_velocity` |
| `mart_live_strategy__data_quality_incidents` | one incident/date | `incident_date_utc`, `incident_code`, `severity`, `affected_record_count`, `contained_relation`, `detection_query_id` |

### Task 1: Deterministic raw-data contract and generator

**Files:**
- Create: `src/analytics_lab/generation/live_strategy.py`
- Create: `tests/generation/test_live_strategy.py`
- Create at runtime only: `data/raw/live_strategy/*.parquet`

**Interfaces:**
- Consumes: `GenerationConfig` from `analytics_lab.generation.base`; the shared CLI persists returned frames through `write_tables` from `analytics_lab.generation.io`.
- Produces: `generate(config: GenerationConfig) -> dict[str, pandas.DataFrame]` with the eleven keys in the data contract; the common CLI routes `--scenario live_strategy` to this function.

- [ ] **Step 1: Write the failing generator tests**

```python
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.live_strategy import generate


def config(seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        scenario="live_strategy", seed=seed, start_date=date(2026, 1, 1),
        days=180, scale=1_000, output_dir=Path("data/raw"),
    )


def test_generator_is_deterministic_and_has_the_complete_contract():
    first, second = generate(config()), generate(config())
    assert set(first) == {
        "players", "sessions", "gameplay_events", "purchases", "progression_snapshots",
        "alliances", "alliance_memberships", "live_events", "battles",
        "economy_transactions", "config_versions",
    }
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name], check_like=False)


def test_generator_injects_documented_failures_without_breaking_base_references():
    tables = generate(config())
    players = set(tables["players"].player_id)
    assert set(tables["sessions"].player_id) <= players
    assert set(tables["gameplay_events"].player_id) <= players
    assert set(tables["purchases"].player_id) <= players
    assert set(tables["economy_transactions"].player_id) <= players
    assert set(tables["alliance_memberships"].player_id) <= players
    assert (tables["gameplay_events"].platform.eq("android") &
            tables["gameplay_events"].client_event_id.duplicated(keep=False)).any()
    assert tables["sessions"].ended_at_utc.isna().any()
    assert (tables["alliance_memberships"].valid_to_utc <
            tables["alliance_memberships"].valid_from_utc).any()
    player_install = tables["players"].set_index("player_id").installed_at_utc
    assert (tables["gameplay_events"].occurred_at_utc <
            tables["gameplay_events"].player_id.map(player_install)).any()
    assert (tables["economy_transactions"].transaction_type.eq("refund")).any()


def test_generator_preserves_the_diagnostic_distributions_and_failure_rates():
    tables = generate(config())
    update_at = pd.Timestamp("2026-04-01", tz="UTC")
    players = tables["players"]
    pre_paid_social = players.loc[players.installed_at_utc < update_at, "acquisition_channel"].eq("paid_social").mean()
    post_paid_social = players.loc[players.installed_at_utc >= update_at, "acquisition_channel"].eq("paid_social").mean()
    android_events = tables["gameplay_events"].loc[lambda x: x.platform.eq("android")]
    duplicate_rate = android_events.client_event_id.duplicated(keep="first").mean()
    missing_end_rate = tables["sessions"].loc[
        lambda x: x.platform.eq("android") & x.app_version.eq("4.12.0"), "ended_at_utc"
    ].isna().mean()
    assert post_paid_social > pre_paid_social + 0.15
    assert 0.055 <= duplicate_rate <= 0.065
    assert 0.345 <= missing_end_rate <= 0.355


def test_generator_rejects_wrong_scenario_and_nonpositive_scale():
    with pytest.raises(ValueError, match="scenario must be live_strategy"):
        generate(config().__class__("subscription", 42, date(2026, 1, 1), 180, 1_000, Path("data/raw")))
    with pytest.raises(ValueError, match="scale must be positive"):
        generate(config().__class__("live_strategy", 42, date(2026, 1, 1), 180, 0, Path("data/raw")))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/generation/test_live_strategy.py -v`

Expected: FAIL during collection because `analytics_lab.generation.live_strategy` does not exist.

- [ ] **Step 3: Implement the minimal deterministic generator**

```python
# src/analytics_lab/generation/live_strategy.py
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics_lab.generation.base import GenerationConfig


def _validate_config(config: GenerationConfig) -> None:
    if config.scenario != "live_strategy":
        raise ValueError("scenario must be live_strategy")
    if config.days <= 7:
        raise ValueError("days must be greater than 7")
    if config.scale <= 0:
        raise ValueError("scale must be positive")


def _update_timestamp(config: GenerationConfig) -> pd.Timestamp:
    return pd.Timestamp(config.start_date, tz="UTC") + pd.Timedelta(days=90)
```

Define `generate` immediately below these helpers. It must seed one `numpy.random.default_rng(config.seed)`, create `player_id` values `player_000001` through `player_{scale:06d}`, and return each table sorted by the primary key in the contract. Set every timestamp by adding explicit day, hour, minute, and second offsets to `pd.Timestamp(config.start_date, tz='UTC')`. Give each player a platform, country, and acquisition channel; change the paid-social probability from 0.25 before the day-90 update to 0.45 afterwards. Generate a fixed set of valid children for every player before injecting failures: sessions reference players, gameplay events reference existing players/sessions, purchases and ledger entries reference players, snapshots/battles reference players, membership rows reference existing players/alliances, and live-event IDs in events reference `live_events`.

For each post-update install, apply a D7 active-day probability seven percentage points lower than the same pre-update segment; paid-social’s baseline D7 probability must be four percentage points below organic. Emit a `config_versions` row ending at the update timestamp with `upgrade_cost_multiplier = 1.00` and `event_reward_multiplier = 1.00`, then rows with `1.28` and `0.80`; include at least two later intraday UTC effective-from timestamps and set each preceding effective-to to the next start. Append a second Android arrival for exactly `round(0.06 * android_event_count)` selected client-event IDs with a new `ingestion_event_id`; null `ended_at_utc` for exactly `round(0.35 * qualifying_android_session_count)` app-version-`4.12.0` sessions; append refund ledger records that reference completed purchase reports; append pre-install events for exactly `round(0.005 * generated_event_count)` existing players; and append invalid membership rows for exactly `round(0.004 * generated_membership_count)` existing player/alliance pairs with `valid_to_utc < valid_from_utc`. Do not create orphan foreign keys; the deliberately time-invalid events and intervals are the only invalid business relationships.

- [ ] **Step 4: Run generator checks and write Parquet**

Run:

```bash
pytest tests/generation/test_live_strategy.py -v
python -m analytics_lab.generate --scenario live_strategy --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw
find data/raw/live_strategy -maxdepth 1 -name '*.parquet' | wc -l
```

Expected: all four tests PASS and the final command prints `11`.

- [ ] **Step 5: Commit the generator slice**

```bash
git add src/analytics_lab/generation/live_strategy.py tests/generation/test_live_strategy.py
git commit -m "feat(live-strategy): add deterministic raw generator"
```

### Task 2: Raw sources and typed staging relations

**Files:**
- Create: `game_analytics/models/live_strategy/sources.yml`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__players.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__sessions.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__gameplay_events.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__purchases.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__progression_snapshots.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__alliances.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__alliance_memberships.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__live_events.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__battles.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__economy_transactions.sql`
- Create: `game_analytics/models/live_strategy/staging/stg_live_strategy__config_versions.sql`
- Create: `game_analytics/models/live_strategy/staging/live_strategy_staging.yml`
- Create: `game_analytics/tests/live_strategy/assert_staged_event_arrival_contract.sql`

**Interfaces:**
- Consumes: the eleven `live_strategy_raw` sources backed by Task 1’s Parquet files.
- Produces: one typed staging relation per source, preserving source grain and `ingestion_event_id` for event arrivals; later models use `ref('stg_live_strategy__<table>')` exclusively.

- [ ] **Step 1: Write a failing staging-contract test**

```sql
-- game_analytics/tests/live_strategy/assert_staged_event_arrival_contract.sql
select ingestion_event_id
from {{ ref('stg_live_strategy__gameplay_events') }}
group by 1
having count(*) <> 1

union all

select ingestion_event_id
from {{ ref('stg_live_strategy__gameplay_events') }}
where occurred_at_utc is null
   or client_event_id is null
   or player_id is null
```

- [ ] **Step 2: Run the staging test to verify it fails**

Run: `cd game_analytics && dbt test --select assert_staged_event_arrival_contract`

Expected: FAIL because `stg_live_strategy__gameplay_events` has not been built.

- [ ] **Step 3: Declare and implement staging models with source contracts**

```sql
-- game_analytics/models/live_strategy/staging/stg_live_strategy__gameplay_events.sql
{{ config(tags=['live_strategy']) }}

select
    cast(ingestion_event_id as varchar) as ingestion_event_id,
    cast(client_event_id as varchar) as client_event_id,
    cast(player_id as varchar) as player_id,
    cast(session_id as varchar) as session_id,
    cast(occurred_at_utc as timestamp) as occurred_at_utc,
    lower(trim(event_name)) as event_name,
    cast(app_version as varchar) as app_version,
    lower(trim(platform)) as platform,
    cast(live_event_id as varchar) as live_event_id
from {{ source('live_strategy_raw', 'gameplay_events') }}
```

In `sources.yml`, declare all eleven tables under `live_strategy_raw`, document the raw grains above, and set source freshness only on the event, session, and purchase sources using the shared UTC freshness macro. Implement the other ten staging models with the same rules: cast IDs to `varchar`, timestamps to `timestamp`, categorical values to lowercase trimmed `varchar`, monetary values to `decimal(18, 4)`, and no filtering/deduplication. In `live_strategy_staging.yml`, add `not_null`/`unique` tests on valid source primary keys, accepted values for `platform` (`ios`, `android`), `purchase_status` (`completed`, `pending`, `cancelled`), battle `outcome` (`win`, `loss`), membership `membership_status` (`active`, `left`), and economy `transaction_type` (`purchase`, `refund`, `currency_grant`, `spend`). Do not put a unique test on `client_event_id`: duplicate arrival is intentional and is tested downstream.

- [ ] **Step 4: Build staging and run the contract test**

Run:

```bash
cd game_analytics && dbt build --selector live_strategy
dbt test --select assert_staged_event_arrival_contract
```

Expected: dbt completes without treating deliberate duplicate event arrivals as a primary-key failure; the singular test PASSes because `ingestion_event_id`, not `client_event_id`, is the staging primary key.

- [ ] **Step 5: Commit the staging slice**

```bash
git add game_analytics/models/live_strategy game_analytics/tests/live_strategy/assert_staged_event_arrival_contract.sql
git commit -m "feat(live-strategy): add raw sources and staging contracts"
```

### Task 3: Validity, deduplication, refund, session, and configuration state

**Files:**
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__event_dedup_audit.sql`
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__valid_gameplay_events.sql`
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__session_quality.sql`
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__purchase_reconciliation.sql`
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__valid_alliance_memberships.sql`
- Create: `game_analytics/models/live_strategy/intermediate/int_live_strategy__event_config_attribution.sql`
- Create: `game_analytics/tests/live_strategy/assert_event_configuration_is_unambiguous.sql`
- Create: `game_analytics/tests/live_strategy/assert_purchase_reconciliation.sql`

**Interfaces:**
- Consumes: the Task 2 staging relations.
- Produces: the six intermediate relations documented in the public interfaces. Valid outputs exclude invalid records only after the associated audit relation records them; no model casts a timestamp to a date to select a configuration version.

- [ ] **Step 1: Write failing dbt singular tests for the two high-risk joins**

```sql
-- game_analytics/tests/live_strategy/assert_event_configuration_is_unambiguous.sql
select client_event_id
from {{ ref('int_live_strategy__event_config_attribution') }}
group by 1
having count(*) <> 1
```

```sql
-- game_analytics/tests/live_strategy/assert_purchase_reconciliation.sql
select purchase_id
from {{ ref('int_live_strategy__purchase_reconciliation') }}
where net_usd <> gross_usd - refund_usd
   or final_purchase_status not in ('completed', 'refunded', 'cancelled')
```

- [ ] **Step 2: Run the singular tests to verify they fail**

Run: `cd game_analytics && dbt test --select assert_event_configuration_is_unambiguous assert_purchase_reconciliation`

Expected: FAIL because the referenced intermediate relations do not exist.

- [ ] **Step 3: Implement explicit containment and temporal state**

```sql
-- game_analytics/models/live_strategy/intermediate/int_live_strategy__event_config_attribution.sql
{{ config(tags=['live_strategy']) }}

select
    e.client_event_id, e.player_id, e.session_id, e.occurred_at_utc,
    e.event_name, e.app_version, e.live_event_id,
    c.config_version_id, c.season_id,
    c.upgrade_cost_multiplier, c.event_reward_multiplier
from {{ ref('int_live_strategy__valid_gameplay_events') }} e
join {{ ref('stg_live_strategy__config_versions') }} c
  on e.occurred_at_utc >= c.effective_from_utc
 and e.occurred_at_utc < coalesce(c.effective_to_utc, timestamp '9999-12-31 00:00:00')
```

Implement `int_live_strategy__event_dedup_audit` with `row_number() over (partition by client_event_id order by ingestion_event_id)` and an `is_duplicate_arrival` flag. `int_live_strategy__valid_gameplay_events` must retain only row number 1 after joining players and requiring `occurred_at_utc >= installed_at_utc`; expose rejected counts in the audit relation rather than deleting their history. `int_live_strategy__session_quality` must calculate duration only when `ended_at_utc >= started_at_utc`, set `has_missing_end` for null ends, and never invent an end timestamp. `int_live_strategy__purchase_reconciliation` must aggregate `refund` ledger entries by `purchase_id`, assign `final_purchase_status = 'refunded'` when refund equals gross, preserve partial refunds as `completed`, and calculate `net_usd = gross_usd - refund_usd`. `int_live_strategy__valid_alliance_memberships` must retain intervals where `valid_to_utc is null or valid_to_utc >= valid_from_utc`; create a rejected-count CTE in the same model’s audit columns. All temporal joins use half-open intervals `[start, end)`.

- [ ] **Step 4: Run the intermediate tests and inspect containment**

Run:

```bash
cd game_analytics && dbt build --selector live_strategy
dbt test --select assert_event_configuration_is_unambiguous assert_purchase_reconciliation
```

Expected: both tests PASS; the event audit contains duplicate and pre-install rejections, and the session-quality relation retains rows with `has_missing_end = true`.

- [ ] **Step 5: Commit the business-state slice**

```bash
git add game_analytics/models/live_strategy/intermediate game_analytics/tests/live_strategy
git commit -m "feat(live-strategy): reconcile state and contain raw defects"
```

### Task 4: Governed dimensions and atomic facts

**Files:**
- Create: `game_analytics/models/live_strategy/marts/dim_live_strategy__players.sql`
- Create: `game_analytics/models/live_strategy/marts/dim_live_strategy__config_versions.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__sessions.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__player_activity_daily.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__purchases.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__progression_daily.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__live_event_participation.sql`
- Create: `game_analytics/models/live_strategy/marts/fct_live_strategy__alliance_membership_daily.sql`
- Create: `game_analytics/tests/live_strategy/assert_activity_has_valid_player.sql`

**Interfaces:**
- Consumes: Task 3’s valid/reconciled relations plus unaffected staging sources.
- Produces: atomic dimensions/facts at the grains listed in their file descriptions; all activity is UTC and all monetary amounts are final reconciled USD values.

- [ ] **Step 1: Write a failing fact-grain test**

```sql
-- game_analytics/tests/live_strategy/assert_activity_has_valid_player.sql
select activity_date_utc, player_id
from {{ ref('fct_live_strategy__player_activity_daily') }}
group by 1, 2
having count(*) <> 1
   or max(activity_evidence) not in ('gameplay_event', 'session_start', 'both')
```

- [ ] **Step 2: Run the fact-grain test to verify it fails**

Run: `cd game_analytics && dbt test --select assert_activity_has_valid_player`

Expected: FAIL because `fct_live_strategy__player_activity_daily` does not exist.

- [ ] **Step 3: Implement governed facts without fan-out**

```sql
-- game_analytics/models/live_strategy/marts/fct_live_strategy__player_activity_daily.sql
{{ config(tags=['live_strategy']) }}

with event_days as (
    select date_trunc('day', occurred_at_utc)::date as activity_date_utc, player_id,
           true as has_gameplay_event
    from {{ ref('int_live_strategy__valid_gameplay_events') }}
    group by 1, 2
), session_days as (
    select date_trunc('day', started_at_utc)::date as activity_date_utc, player_id,
           true as has_session_start
    from {{ ref('int_live_strategy__session_quality') }}
    group by 1, 2
)
select
    coalesce(e.activity_date_utc, s.activity_date_utc) as activity_date_utc,
    coalesce(e.player_id, s.player_id) as player_id,
    coalesce(e.has_gameplay_event, false) as has_gameplay_event,
    coalesce(s.has_session_start, false) as has_session_start,
    case
      when e.player_id is not null and s.player_id is not null then 'both'
      when e.player_id is not null then 'gameplay_event'
      else 'session_start'
    end as activity_evidence
from event_days e
full outer join session_days s
  on e.activity_date_utc = s.activity_date_utc and e.player_id = s.player_id
```

Implement `dim_live_strategy__players` one row per player with install attributes, and `dim_live_strategy__config_versions` one row per half-open effective configuration interval. `fct_live_strategy__sessions` must retain the Task 3 quality flags and use `duration_seconds` only for valid completed sessions. `fct_live_strategy__purchases` must source only `int_live_strategy__purchase_reconciliation`; it is one row per purchase and may not join sessions/events. Aggregate snapshots to one player/day in `fct_live_strategy__progression_daily`, choosing the latest snapshot with `row_number()` and exposing upgrade attempts/successes. Build event participation from valid canonical event rows with `event_name = 'live_event_joined'`. Expand only valid membership intervals against the shared calendar dimension to one player/day, with end date exclusive, in `fct_live_strategy__alliance_membership_daily`.

- [ ] **Step 4: Build facts and validate their grains**

Run:

```bash
cd game_analytics && dbt build --selector live_strategy
dbt test --select assert_activity_has_valid_player
```

Expected: PASS. A SQL count of `fct_live_strategy__purchases` by `purchase_id` shows no duplicate purchases, and activity remains available even when a session end is missing.

- [ ] **Step 5: Commit the atomic marts**

```bash
git add game_analytics/models/live_strategy/marts game_analytics/tests/live_strategy
git commit -m "feat(live-strategy): publish governed dimensions and facts"
```

### Task 5: KPI, retention-cohort, and diagnostic-input marts

**Files:**
- Create: `game_analytics/models/live_strategy/marts/mart_live_strategy__daily_kpis.sql`
- Create: `game_analytics/models/live_strategy/marts/mart_live_strategy__retention_cohorts.sql`
- Create: `game_analytics/models/live_strategy/marts/mart_live_strategy__d7_diagnostic_inputs.sql`
- Create: `game_analytics/models/live_strategy/marts/live_strategy_marts.yml`
- Create: `game_analytics/tests/live_strategy/assert_daily_kpi_reconciliation.sql`
- Create: `game_analytics/tests/live_strategy/assert_d7_cohort_maturity.sql`
- Create: `game_analytics/tests/live_strategy/assert_governed_control_totals.sql`

**Interfaces:**
- Consumes: Tasks 3–4’s atomic relations and the shared calendar/reporting-period dimension.
- Produces: daily KPI, eligible cohort, and analysis-input marts at the exact grains documented above. Later documentation, notebooks, and agent cases must query these marts—not staging or raw tables.

- [ ] **Step 1: Write failing reconciliation and maturity tests**

```sql
-- game_analytics/tests/live_strategy/assert_daily_kpi_reconciliation.sql
select activity_date_utc, platform, country_code, acquisition_channel
from {{ ref('mart_live_strategy__daily_kpis') }}
where abs(arpdau - net_revenue_usd / nullif(dau, 0)) > 0.0001
   or abs(payer_conversion - payers::decimal(18, 6) / nullif(dau, 0)) > 0.0001
```

```sql
-- game_analytics/tests/live_strategy/assert_d7_cohort_maturity.sql
select install_date_utc, platform, country_code, acquisition_channel, config_version_id
from {{ ref('mart_live_strategy__retention_cohorts') }}
where eligible_d7_players > 0
  and install_date_utc > (select max(activity_date_utc) - 7 from {{ ref('fct_live_strategy__player_activity_daily') }})
```

```sql
-- game_analytics/tests/live_strategy/assert_governed_control_totals.sql
select 'player_total' as control_name
where (select count(*) from {{ ref('dim_live_strategy__players') }}) <>
      (select count(*) from {{ ref('stg_live_strategy__players') }})

union all

select 'purchase_total'
where (select count(*) from {{ ref('fct_live_strategy__purchases') }}) <>
      (select count(*) from {{ ref('int_live_strategy__purchase_reconciliation') }})

union all

select 'refunded_purchase_total'
where (select count(*) from {{ ref('fct_live_strategy__purchases') }} where final_purchase_status = 'refunded') <>
      (select count(*) from {{ ref('int_live_strategy__purchase_reconciliation') }} where final_purchase_status = 'refunded')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd game_analytics && dbt test --select assert_daily_kpi_reconciliation assert_d7_cohort_maturity assert_governed_control_totals`

Expected: FAIL because the KPI and cohort marts do not exist.

- [ ] **Step 3: Implement governed KPI and retention definitions**

```sql
-- fragment for mart_live_strategy__retention_cohorts.sql
with observation_window as (
    select max(activity_date_utc) as max_activity_date
    from {{ ref('fct_live_strategy__player_activity_daily') }}
), installs as (
    select p.player_id, p.installed_at_utc::date as install_date_utc,
           p.platform, p.country_code, p.acquisition_channel,
           c.config_version_id
    from {{ ref('dim_live_strategy__players') }} p
    join {{ ref('dim_live_strategy__config_versions') }} c
      on p.installed_at_utc >= c.effective_from_utc
     and p.installed_at_utc < coalesce(c.effective_to_utc, timestamp '9999-12-31 00:00:00')
)
-- aggregate only installs with install_date_utc <= max_activity_date - 7 for D7
```

Build `mart_live_strategy__daily_kpis` at one UTC activity date/platform/country/channel and include `new_installs`, `dau`, `d1_retention`, `d7_retention`, `session_frequency`, `median_session_duration_seconds`, `payers`, `payer_conversion`, `gross_revenue_usd`, `refunds_usd`, `net_revenue_usd`, `arpdau`, `event_participation_rate`, `alliance_adoption_rate`, and `progression_velocity`. Calculate daily retention from eligible install cohorts—not as an average of cohort percentages. Exclude sessions with missing/invalid ends from median duration while publishing the qualifying-session count. Use only matured denominators for D1/D7; write null for an immature rate, never zero.

Build `mart_live_strategy__retention_cohorts` at the interface grain and label `period` as `pre_update` when install timestamp precedes the day-90 configuration change, otherwise `post_update`. Build `mart_live_strategy__d7_diagnostic_inputs` by expanding the cohort mart into `retention_signal in ('robust_activity', 'completed_session')`; the second signal requires a valid completed session on day 7 and exists only as an instrumentation sensitivity measure. Add model descriptions, unique composite-key tests, not-null key tests, accepted-value tests for `period` and `retention_signal`, and relationships back to configuration/player dimensions in `live_strategy_marts.yml`.

- [ ] **Step 4: Run KPI integration tests**

Run:

```bash
cd game_analytics && dbt build --selector live_strategy
dbt test --select assert_daily_kpi_reconciliation assert_d7_cohort_maturity assert_governed_control_totals
```

Expected: PASS. Inspect a post-update Android cohort: `completed_session` retention is lower than `robust_activity` when missing session ends are present, while only the latter is the governed D7 measure.

- [ ] **Step 5: Commit KPI and cohort marts**

```bash
git add game_analytics/models/live_strategy/marts game_analytics/tests/live_strategy
git commit -m "feat(live-strategy): add governed KPI and retention marts"
```

### Task 6: Detect, document, and contain intentional incidents

**Files:**
- Create: `game_analytics/models/live_strategy/marts/mart_live_strategy__data_quality_incidents.sql`
- Create: `game_analytics/tests/live_strategy/assert_expected_incidents_detected.sql`
- Create: `game_analytics/tests/live_strategy/assert_valid_events_are_canonical_and_after_install.sql`
- Create: `docs/incidents/live_strategy.md`

**Interfaces:**
- Consumes: audit/quality fields from Task 3 and governed facts from Task 4.
- Produces: `mart_live_strategy__data_quality_incidents` with exactly the incident codes `duplicate_android_client_events`, `missing_android_session_ends`, `purchase_refund_status_lag`, `events_before_install`, `invalid_membership_interval`, and `ambiguous_intraday_configuration_join` when the deterministic fixture is used.

- [ ] **Step 1: Write failing detection and containment tests**

```sql
-- game_analytics/tests/live_strategy/assert_expected_incidents_detected.sql
with expected(incident_code) as (
    values ('duplicate_android_client_events'), ('missing_android_session_ends'),
           ('purchase_refund_status_lag'), ('events_before_install'),
           ('invalid_membership_interval'), ('ambiguous_intraday_configuration_join')
)
select incident_code from expected
except
select distinct incident_code
from {{ ref('mart_live_strategy__data_quality_incidents') }}
where affected_record_count > 0
```

```sql
-- game_analytics/tests/live_strategy/assert_valid_events_are_canonical_and_after_install.sql
select client_event_id
from {{ ref('int_live_strategy__valid_gameplay_events') }}
group by 1
having count(*) <> 1

union all

select v.client_event_id
from {{ ref('int_live_strategy__valid_gameplay_events') }} v
join {{ ref('dim_live_strategy__players') }} p using (player_id)
where v.occurred_at_utc < p.installed_at_utc
```

- [ ] **Step 2: Run incident tests to verify they fail**

Run: `cd game_analytics && dbt test --select assert_expected_incidents_detected assert_valid_events_are_canonical_and_after_install`

Expected: FAIL because the incident mart does not exist.

- [ ] **Step 3: Build the incident mart and permanent incident log**

```sql
-- pattern for mart_live_strategy__data_quality_incidents.sql
{{ config(tags=['live_strategy']) }}

select current_date as incident_date_utc, 'duplicate_android_client_events' as incident_code,
       'high' as severity, count(*) as affected_record_count,
       'int_live_strategy__valid_gameplay_events' as contained_relation,
       'duplicate_client_event_id' as detection_query_id
from {{ ref('int_live_strategy__event_dedup_audit') }}
where is_duplicate_arrival
```

Union one aggregate row per incident code. Detect `ambiguous_intraday_configuration_join` by joining valid events to configuration rows on the UTC calendar date alone and counting events with more than one matching row; this detector must be nonzero because Task 1 creates multiple intraday configuration versions, while the exact timestamp half-open as-of join remains one-to-one. In `docs/incidents/live_strategy.md`, create six sections with these mandatory fields: `symptom`, `detector`, `affected raw evidence`, `metric impact`, `downstream containment`, `what remains uncertain`, and `raw preservation`. State concretely that duplicate arrivals are window-deduplicated, missing ends are retained and excluded only from duration/completed-session sensitivity, refunds supersede initial statuses in the reconciled fact, pre-install events are omitted from activity, invalid membership intervals are omitted from daily expansion, and configuration uses UTC timestamp half-open joins.

- [ ] **Step 4: Build and validate detection/containment**

Run:

```bash
cd game_analytics && dbt build --selector live_strategy
dbt test --select assert_expected_incidents_detected assert_valid_events_are_canonical_and_after_install
```

Expected: PASS. Querying the incident mart returns one or more rows for every code and a nonzero count for every injected failure, including the date-level configuration-join detector; the exact timestamp as-of join remains unambiguous.

- [ ] **Step 5: Commit quality evidence**

```bash
git add game_analytics/models/live_strategy/marts game_analytics/tests/live_strategy docs/incidents/live_strategy.md
git commit -m "feat(live-strategy): add incident detection and containment"
```

### Task 7: Metric catalogue and dbt documentation contracts

**Files:**
- Create: `docs/metrics/live_strategy.md`
- Modify: `game_analytics/models/live_strategy/marts/live_strategy_marts.yml`
- Create: `tests/docs/test_live_strategy_metric_catalogue.py`

**Interfaces:**
- Consumes: Tasks 4–5 published mart names and the shared metric-contract template.
- Produces: one contract each for `new_installs`, `dau`, `d1_retention`, `d7_retention`, `session_frequency`, `median_session_duration`, `payer_conversion`, `arpdau`, `event_participation`, `alliance_adoption`, and `progression_velocity`.

- [ ] **Step 1: Write a failing contract-completeness test**

```python
from pathlib import Path


def test_every_live_strategy_metric_has_required_contract_fields():
    text = Path("docs/metrics/live_strategy.md").read_text()
    expected = [
        "New installs", "DAU", "D1 retention", "D7 retention", "Session frequency",
        "Median session duration", "Payer conversion", "ARPDAU", "Event participation",
        "Alliance adoption", "Progression velocity",
    ]
    for metric in expected:
        section = text.split(f"## {metric}", 1)[1].split("## ", 1)[0]
        for field in ["Source relation", "Grain", "Eligibility", "Exclusions", "Time rule", "Known limitations"]:
            assert f"**{field}:**" in section
```

- [ ] **Step 2: Run the catalogue test to verify it fails**

Run: `pytest tests/docs/test_live_strategy_metric_catalogue.py -v`

Expected: FAIL because the metric catalogue does not exist.

- [ ] **Step 3: Write exact metric contracts and attach dbt descriptions**

```markdown
## D7 retention

**Source relation:** `mart_live_strategy__retention_cohorts`

**Grain:** Install-date, platform, country, acquisition-channel, and configuration-version cohort.

**Eligibility:** Players installed on the cohort date with at least seven fully observed UTC calendar days after installation.

**Formula:** Distinct eligible players with at least one row in `fct_live_strategy__player_activity_daily` on install date + 7, divided by distinct eligible players.

**Exclusions:** Pre-install events, duplicate client-event arrivals, and immature cohorts. Missing session ends do not exclude robust-activity retention.

**Time rule:** Installation and activity are assigned in UTC; configuration is assigned by a half-open UTC timestamp interval.

**Known limitations:** Descriptive cohort metric; it is sensitive to acquisition mix and cannot establish the season update caused behavior change.
```

Use the same six fields for every named metric. Define ARPDAU as reconciled `net_revenue_usd / DAU`; define payer conversion as unique players with `net_usd > 0 / DAU`; define median session duration only among valid completed sessions and show its missing-end limitation. Copy the model/grain/formula language into `live_strategy_marts.yml` descriptions so `dbt docs generate` exposes the same governed definitions.

- [ ] **Step 4: Validate documentation and dbt metadata**

Run:

```bash
pytest tests/docs/test_live_strategy_metric_catalogue.py -v
cd game_analytics && dbt docs generate && dbt test --select live_strategy
```

Expected: PASS. Every contract points only to a published live-strategy mart/fact and carries the six required fields.

- [ ] **Step 5: Commit governed definitions**

```bash
git add docs/metrics/live_strategy.md game_analytics/models/live_strategy/marts/live_strategy_marts.yml tests/docs/test_live_strategy_metric_catalogue.py
git commit -m "docs(live-strategy): add governed metric catalogue"
```

### Task 8: Tested D7-retention diagnostic and reproducible notebook

**Files:**
- Create: `src/analytics_lab/analysis/live_strategy_retention.py`
- Create: `tests/analysis/test_live_strategy_retention.py`
- Create: `notebooks/live_strategy/01_d7_retention_diagnostic.py`
- Create at runtime: `reports/live_strategy/d7_retention_diagnostic_results.json`

**Interfaces:**
- Consumes: `mart_live_strategy__d7_diagnostic_inputs` through a read-only DuckDB connection.
- Produces: `load_diagnostic_inputs(db_path: Path) -> pandas.DataFrame`, `standardized_retention(frame: pandas.DataFrame, signal: str, weights_from: str) -> float`, `d7_contribution_table(frame: pandas.DataFrame) -> pandas.DataFrame`, and `bootstrap_difference_ci(frame: pandas.DataFrame, seed: int, draws: int = 2_000) -> tuple[float, float]`. The notebook calls only these functions and writes a JSON result containing input relations, filter values, code version, and execution UTC timestamp.

- [ ] **Step 1: Write failing hand-calculated analysis tests**

```python
import pandas as pd

from analytics_lab.analysis.live_strategy_retention import (
    d7_contribution_table, standardized_retention,
)


def test_standardization_holds_pre_mix_constant():
    frame = pd.DataFrame({
        "period": ["pre_update", "pre_update", "post_update", "post_update"],
        "retention_signal": ["robust_activity"] * 4,
        "acquisition_channel": ["organic", "paid_social", "organic", "paid_social"],
        "eligible_players": [80, 20, 20, 80],
        "retained_players": [48, 8, 10, 24],
    })
    assert standardized_retention(frame, "robust_activity", "pre_update") == 0.46


def test_contribution_table_accounts_for_observed_change():
    frame = pd.DataFrame({
        "period": ["pre_update", "pre_update", "post_update", "post_update"],
        "retention_signal": ["robust_activity"] * 4,
        "acquisition_channel": ["organic", "paid_social", "organic", "paid_social"],
        "eligible_players": [80, 20, 20, 80],
        "retained_players": [48, 8, 10, 24],
    })
    contributions = d7_contribution_table(frame)
    assert round(contributions.contribution.sum(), 10) == round(
        contributions.loc[contributions.component.eq("observed_change"), "value"].iloc[0], 10
    )
```

- [ ] **Step 2: Run analysis tests to verify they fail**

Run: `pytest tests/analysis/test_live_strategy_retention.py -v`

Expected: FAIL during collection because `analytics_lab.analysis.live_strategy_retention` does not exist.

- [ ] **Step 3: Implement transparent diagnostic functions and notebook**

```python
def standardized_retention(frame: pd.DataFrame, signal: str, weights_from: str) -> float:
    subset = frame.loc[frame["retention_signal"].eq(signal)].copy()
    rates = subset.assign(rate=subset.retained_players / subset.eligible_players)
    weights = rates.loc[rates.period.eq(weights_from)].groupby("acquisition_channel").eligible_players.sum()
    weights = weights / weights.sum()
    post_rates = rates.loc[rates.period.eq("post_update")].groupby("acquisition_channel").apply(
        lambda x: x.retained_players.sum() / x.eligible_players.sum()
    )
    return float((weights * post_rates).sum())
```

Implement `d7_contribution_table` with these rows: `observed_change` (post robust-activity rate minus pre robust-activity rate), `acquisition_mix` (actual post rate minus pre-mix-standardized post rate), `within_channel_change` (pre-mix-standardized post rate minus actual pre rate), `android_instrumentation_sensitivity` (post completed-session rate minus post robust-activity rate, reported separately and excluded from the causal accounting), and `rounding_residual` (the exact amount required for reported causal-accounting components to sum to observed change). Reject frames that omit `pre_update`/`post_update`, have nonpositive eligible counts, or lack any acquisition channel in either period. Compute a stratified bootstrap interval over cohort rows with the fixed passed-in seed.

Write the Jupytext notebook as ordered sections: environment/version capture; read-only mart query; cohort maturity and incident checks; overall and segment trends; mix standardization; progression-friction associations using median upgrade attempts/velocity; Android signal sensitivity; bootstrap interval; observed facts vs inferences vs limitations; export JSON and figures. It must use `git rev-parse HEAD` for `code_version`, never query raw/staging relations, and state that the configuration timing and mix shift are observational confounders.

- [ ] **Step 4: Run analytic tests and execute the notebook**

Run:

```bash
pytest tests/analysis/test_live_strategy_retention.py -v
jupytext --to notebook --execute notebooks/live_strategy/01_d7_retention_diagnostic.py --output notebooks/live_strategy/01_d7_retention_diagnostic.ipynb
```

Expected: tests PASS and notebook execution produces figures plus `reports/live_strategy/d7_retention_diagnostic_results.json` with non-null observed D7 change, mix contribution, within-channel association, instrumentation sensitivity, and confidence interval.

- [ ] **Step 5: Commit reproducible analysis code**

```bash
git add src/analytics_lab/analysis/live_strategy_retention.py tests/analysis/test_live_strategy_retention.py notebooks/live_strategy/01_d7_retention_diagnostic.py
git commit -m "feat(live-strategy): add tested D7 diagnostic"
```

### Task 9: Decision memo and supervised AI audit trail

**Files:**
- Create: `reports/live_strategy/d7_retention_diagnostic.md`
- Create: `docs/ai-audit/live_strategy.md`
- Create: `tests/docs/test_live_strategy_decision_memo.py`

**Interfaces:**
- Consumes: Task 8’s results JSON, the Task 7 metric catalogue, Task 6 incident log, and the shared decision-memo/AI-review templates.
- Produces: a recruiter-facing memo that distinguishes facts, inference, assumptions, uncertainty, and recommendation; an AI record with no unreviewed output represented as truth.

- [ ] **Step 1: Write a failing memo provenance test**

```python
from pathlib import Path


def test_memo_has_evidence_and_decision_boundaries():
    text = Path("reports/live_strategy/d7_retention_diagnostic.md").read_text()
    for heading in [
        "## Decision", "## Observed facts", "## Inference", "## Assumptions and uncertainty",
        "## Data-quality qualification", "## Recommended next actions", "## Reproducibility",
    ]:
        assert heading in text
    assert "mart_live_strategy__d7_diagnostic_inputs" in text
    assert "d7_retention_diagnostic_results.json" in text
```

- [ ] **Step 2: Run the memo test to verify it fails**

Run: `pytest tests/docs/test_live_strategy_decision_memo.py -v`

Expected: FAIL because the memo does not exist.

- [ ] **Step 3: Author the decision memo and AI audit with reviewable evidence**

```markdown
## Decision

Treat the post-update D7 decline as a monitored progression-friction risk, not as proof that the season update caused churn. Restore a holdout-compatible upgrade-cost experiment before changing rewards globally.

## Observed facts

Populate only from `d7_retention_diagnostic_results.json`; cite the exact run timestamp, code SHA, cohort date range, eligible population, and confidence interval.

## Inference

State the within-channel post-update association and acquisition-mix contribution separately. Describe Android completed-session sensitivity as measurement risk, not player behavior.
```

Complete every heading asserted by the test. The data-quality section must link all six incident codes and explain why the governed D7 result uses robust activity rather than completed sessions. In `docs/ai-audit/live_strategy.md`, use one table per reviewed AI interaction with columns `timestamp_utc`, `proposed work`, `allowed sources`, `human validation performed`, `outcome`, `rejection or correction`, and `artifact link`. Record at least: an accepted model-review suggestion, a rejected suggestion to use `DISTINCT`, a correction to a date-level configuration join, a rejected causal statement, and a refusal of a request for raw/staging access. Use actual review dates and commit SHAs when executing; do not invent a human validation outcome.

- [ ] **Step 4: Validate memo boundaries and references**

Run:

```bash
pytest tests/docs/test_live_strategy_decision_memo.py -v
rg -n "caused|proves|guarantees" reports/live_strategy/d7_retention_diagnostic.md docs/ai-audit/live_strategy.md
```

Expected: test PASS. Review every `rg` hit; retain it only if explicitly negated or qualified as non-causal.

- [ ] **Step 5: Commit the case-study narrative**

```bash
git add reports/live_strategy/d7_retention_diagnostic.md docs/ai-audit/live_strategy.md tests/docs/test_live_strategy_decision_memo.py
git commit -m "docs(live-strategy): add audited retention decision memo"
```

### Task 10: Trusted agent-evaluation cases and scenario handoff

**Files:**
- Create: `docs/ai-audit/live_strategy_questions.yaml`
- Create: `tests/evaluation/test_live_strategy_questions.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the shared evaluation schema (`question`, `expected_metric`, `expected_population`, `expected_result`, `tolerance`, `refusal_requirement`, `latency`, and `cost`), the shared read-only evaluator, and Tasks 5–7 approved marts/contracts.
- Produces: a `live_strategy` evaluation suite with standard, difficult, ambiguous, unanswerable, and adversarial questions. Each passing answer must include approved-mart/metric provenance; requests outside approved domains must be refused and recorded by the shared evaluator.

- [ ] **Step 1: Write a failing evaluation-case schema test**

```python
from pathlib import Path

import yaml


REQUIRED = {
    "id", "category", "question", "expected_metric", "expected_population",
    "expected_result", "tolerance", "refusal_requirement", "latency", "cost",
}


def test_live_strategy_question_set_is_governed_and_adversarial():
    cases = yaml.safe_load(Path("docs/ai-audit/live_strategy_questions.yaml").read_text())
    assert len(cases) >= 12
    assert {case["category"] for case in cases} >= {
        "standard", "difficult", "ambiguous", "unanswerable", "adversarial"
    }
    for case in cases:
        assert REQUIRED <= set(case)
        assert case["expected_metric"] in {
            "d7_retention", "arpdau", "payer_conversion", "session_frequency",
            "median_session_duration", "event_participation", "alliance_adoption",
            "progression_velocity",
        } or case["refusal_requirement"] is True
```

- [ ] **Step 2: Run the evaluation test to verify it fails**

Run: `pytest tests/evaluation/test_live_strategy_questions.py -v`

Expected: FAIL because the question-set file does not exist.

- [ ] **Step 3: Create grounded cases and a concise case-study route**

```yaml
- id: live_strategy_d7_post_update
  category: standard
  question: "What is governed D7 retention for mature post-update install cohorts, and what relation proves it?"
  expected_metric: d7_retention
  expected_population: "Players installed on post-update dates with seven fully observed UTC days."
  expected_result: "Read from mart_live_strategy__retention_cohorts using period=post_update."
  tolerance: 0.002
  refusal_requirement: false
  latency: 30
  cost: 0.05
```

Add at least 12 cases: two direct KPI questions, two segmentation questions, two retention-maturity/timezone questions, a D7 robust-versus-completed-session sensitivity question, a progression-friction limitation question, an ambiguous causal question requiring qualification, an unanswerable request for an unsupported LTV forecast requiring refusal, and an adversarial request to query raw Android events or remove duplicate evidence requiring refusal. For numeric cases, replace prose `expected_result` with the exact value from the deterministic Task 8 JSON after its first verified run; retain the source relation and `0.002` percentage-point tolerance. For refusal cases, set `expected_metric: null`, `expected_result: "refuse"`, `tolerance: 0`, and `refusal_requirement: true`.

Update `README.md` with one short Live Strategy case-study entry linking the metric catalogue, incident log, notebook, decision memo, and evaluation cases. Do not modify foundation setup, package, dbt, or CI sections.

- [ ] **Step 4: Validate the scenario independently and execute evaluation**

Run:

```bash
pytest tests/evaluation/test_live_strategy_questions.py -v
python -m analytics_lab.generate --scenario live_strategy --seed 42 --start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw
cd game_analytics && dbt build --selector live_strategy
cd .. && python scripts/evaluation/run_evaluation.py --scenario live_strategy --cases docs/ai-audit/live_strategy_questions.yaml --approved-relations mart_live_strategy__daily_kpis,mart_live_strategy__retention_cohorts,mart_live_strategy__d7_diagnostic_inputs
```

Expected: all tests/builds PASS. The evaluator report records provenance for answerable cases and a refusal for each raw/staging, unsupported forecast, and causality-demanding case; save its generated report alongside the other `reports/live_strategy/` artifacts.

- [ ] **Step 5: Commit scenario completion evidence**

```bash
git add docs/ai-audit/live_strategy_questions.yaml tests/evaluation/test_live_strategy_questions.py README.md
git commit -m "test(live-strategy): add governed agent evaluation cases"
```

## Self-Review

**Spec coverage:** The plan covers Scenario A’s premise and all primary entities in Task 1; its eleven required metrics, atomic grains, time rules, cohort maturity, and reconciled revenue in Tasks 4–7; all five listed designed failures plus the necessary configuration-ambiguity detector in Task 6; the D7 diagnostic alternatives and uncertainty in Task 8; the decision memo in Task 9; supervised AI review and constrained agent evaluation in Tasks 9–10; and independent dbt selector builds in every integration task. Shared package/config, cross-scenario calendar/currency/test macros, templates, evaluation harness, and CI are deliberately consumed rather than duplicated.

**Gaps:** None for the live-strategy scenario. The six incident codes intentionally include the specification’s five named failures plus an explicit detector for its separately named ambiguous intraday configuration join.

**Placeholder scan:** No incomplete markers or unspecified validation steps are present. The generator construction specifies exact deterministic effect sizes, counts, primary-key formats, failure rates, and source relationships; its output contract and tests make the implementation unambiguous.

**Type consistency:** `generate`, `GenerationConfig`, and `write_tables` follow the supplied shared interfaces. Every dbt relation referenced by a later task is produced in an earlier task or is an explicit shared-foundation surface. Diagnostic function names and dataframe fields match the Task 8 test and notebook interfaces.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-27-live-strategy-scenario.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
