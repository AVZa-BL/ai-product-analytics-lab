# Experiment Referee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shared experiment referee that adjudicates a pre-registered, locked protocol against a governed hybrid-subscription readout and returns `SHIP`, `STOP`, `INCONCLUSIVE`, or `REFUSE` with its evidence, a verdict artifact, and a decision memo in the governed template.

**Architecture:** An assignment-grain units fact and an arm-by-stratum readout mart are published under the hybrid selector from the existing eligible-exposure population and mature 28-day behaviour. Shared Python loads a protocol, verifies its registration lock, evaluates preconditions in a fixed order and refuses on the first failure, estimates an intent-to-treat effect with a stratified bootstrap, applies the registered decision rule to the interval, and writes a verdict whose label must reproduce in CI on Linux before it is publishable. Designed effects in the generator make every label demonstrable without perturbing the default generation.

**Tech Stack:** dbt Core 1.12.3, dbt-duckdb 1.11.0, DuckDB SQL, Python 3.12, pandas, NumPy, PyYAML, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-13-experiment-referee-design.md`

## Global Constraints

- The primary outcome of the first registered protocol is `total_net_revenue_usd`. The generator's designed lift must move standalone-store spend as well as sessions.
- Thresholds (`practical_threshold`, `minimum_detectable_effect`, `minimum_units_per_arm`) are set by the owner at registration. The referee has no defaults for them, the plan supplies none, and test-only protocols under `tests/referee/fixtures/` carry values chosen to exercise each label.
- Both estimators, `difference_in_differences` and `post_period_difference`, are implemented; the protocol names one and the lock fixes it.
- Preconditions are evaluated in the spec's order and the referee stops at the first failure. Exit status is zero for every adjudicated label including `REFUSE`; non-zero exit is reserved for malformed protocols, missing relations, and units/readout reconciliation failures.
- Analysis is by assigned arm, never by eventual subscription.
- The chi-square p-value for a 2×2 table (one degree of freedom) is `math.erfc(sqrt(x / 2))`. `scipy` is a dev-only dependency and must not become a runtime import of `analytics_lab`.
- The hybrid generation at default knobs must be frame-for-frame identical to the current generation. The effect branch draws from `np.random.default_rng(config.seed + 1_000_003)`, never from the main stream.
- Every verdict carries `input_fingerprint`, `execution_platform`, `package_versions` including `pyarrow`, `code_version`, `executed_at_utc`, `protocol_sha256`, and `registered_at_commit`.
- Commit protocols, verdicts, memos, and fixture protocols. Commit nothing generated under `data/` or `game_analytics/target/`.

## File structure

| Responsibility | Files |
| --- | --- |
| Shared provenance | Create `src/analytics_lab/provenance.py`; modify `src/analytics_lab/analysis/live_strategy_retention.py` to import and re-export `fingerprint_inputs` |
| Referee package | Create `src/analytics_lab/referee/__init__.py`, `protocol.py`, `readout.py`, `preconditions.py`, `estimate.py`, `verdict.py`, `memo.py`, `__main__.py` |
| Units and readout models | Create `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__experiment_units.sql`, `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__experiment_units.sql`, `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__experiment_readout.sql`; modify `intermediate/schema.yml`, `marts/schema.yml`, `marts/kpi_schema.yml` |
| Executable dbt invariants | Create `game_analytics/tests/hybrid_subscription/assert_hybrid_experiment_units_valid.sql`, `assert_hybrid_experiment_readout_reconciles.sql`, `assert_hybrid_late_exposures_excluded_from_units.sql` |
| Generator knobs | Modify `src/analytics_lab/generation/base.py`, `src/analytics_lab/generation/hybrid_subscription.py`, `src/analytics_lab/generate.py`, `tests/generation/test_hybrid_subscription.py`, `tests/generation/test_cli.py` |
| Python tests | Create `tests/referee/test_protocol.py`, `test_preconditions.py`, `test_estimate.py`, `test_verdict.py`, `test_memo.py`, `test_cli.py`, `tests/referee/fixtures/*.yaml`; create `tests/dbt/test_hybrid_subscription_experiment_sql.py`; modify the three hybrid dbt contract tests |
| Registration and evidence | Create `docs/experiments/hybrid_subscription_launch_offer.yaml`, `reports/experiments/hybrid_subscription_launch_offer_verdict.json`, `reports/experiments/hybrid_subscription_launch_offer_decision_memo.md` |
| Governance and gates | Modify `docs/metrics/hybrid_subscription.md`, `docs/ai-audit/hybrid_subscription_questions.yaml`, `scripts/evaluation/hybrid_subscription_answers.json`, `tests/evaluation/test_hybrid_subscription_questions.py`, `tests/docs/test_templates_are_enforced.py`, `docs/getting_started.md`, `README.md`, `scripts/validation/run_scenario_checks.sh`, `tests/validation/test_ci_quality_gates.py`; create `tests/docs/test_experiment_decision_memo.py`, `tests/docs/test_experiment_registration.py` |

---

### Task 1: Lock the surface with failing contract tests

**Files:**
- Modify: `tests/dbt/test_hybrid_subscription_intermediate_contract.py`
- Modify: `tests/dbt/test_hybrid_subscription_marts_contract.py`
- Modify: `tests/dbt/test_hybrid_subscription_kpi_marts_contract.py`
- Create: `tests/referee/__init__.py` (empty), `tests/referee/test_protocol.py`

**Interfaces:**
- Consumes: the current contract sets and model directories.
- Produces: the exact model, test, and module names every later task must satisfy.

- [ ] **Step 1: Extend the dbt contract sets**

Intermediate contract (`EXPECTED_MODELS` is compared with strict equality against the directory, so this is the only place the new intermediate model may be introduced):

```python
"int_hybrid_subscription__experiment_units",
```

Marts contract, `EXPECTED_MODELS`:

```python
"fct_hybrid_subscription__experiment_units",
```

Marts contract, `EXPECTED_TESTS`:

```python
"assert_hybrid_experiment_units_valid.sql",
"assert_hybrid_late_exposures_excluded_from_units.sql",
```

KPI marts contract, `EXPECTED_MODELS`:

```python
"mart_hybrid_subscription__experiment_readout",
```

KPI marts contract, `EXPECTED_TESTS`:

```python
"assert_hybrid_experiment_readout_reconciles.sql",
```

- [ ] **Step 2: Write the first referee test so the package must exist**

```python
from pathlib import Path

import pytest

from analytics_lab.referee.protocol import ProtocolError, load_protocol

FIXTURES = Path("tests/referee/fixtures")


def test_valid_protocol_loads_with_two_arms_summing_to_one() -> None:
    protocol = load_protocol(FIXTURES / "valid.yaml")
    assert protocol.arms == {"control": 0.5, "offer": 0.5}
    assert protocol.primary == "total_net_revenue_usd"


@pytest.mark.parametrize(
    "fixture, message",
    [
        ("three_arms.yaml", "exactly two arms"),
        ("allocation_not_one.yaml", "allocations must sum to 1"),
        ("unknown_outcome.yaml", "not a column of"),
        ("rule_outside_vocabulary.yaml", "decision rule"),
        ("missing_registration.yaml", "registration"),
    ],
)
def test_malformed_protocols_are_rejected_before_any_data_is_read(fixture, message) -> None:
    with pytest.raises(ProtocolError, match=message):
        load_protocol(FIXTURES / fixture)
```

- [ ] **Step 3: Run and verify both fail for missing resources**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest \
  tests/dbt/test_hybrid_subscription_intermediate_contract.py \
  tests/dbt/test_hybrid_subscription_marts_contract.py \
  tests/dbt/test_hybrid_subscription_kpi_marts_contract.py \
  tests/referee/test_protocol.py -v
```

Expected: the three contract modules FAIL on the missing models and singular tests; `test_protocol.py` FAILS at import with `ModuleNotFoundError: analytics_lab.referee`.

- [ ] **Step 4: Commit only the failing tests**

```bash
git add tests/dbt/test_hybrid_subscription_intermediate_contract.py \
  tests/dbt/test_hybrid_subscription_marts_contract.py \
  tests/dbt/test_hybrid_subscription_kpi_marts_contract.py \
  tests/referee/__init__.py tests/referee/test_protocol.py
git commit -m "test: require the experiment referee surface"
```

### Task 2: Protocol loader and registration lock

**Files:**
- Create: `src/analytics_lab/referee/__init__.py`, `src/analytics_lab/referee/protocol.py`
- Create: `tests/referee/fixtures/valid.yaml` and the five malformed fixtures named in Task 1
- Create: `tests/docs/test_experiment_registration.py`

**Interfaces:**
- Consumes: a protocol YAML path; the hybrid marts `schema.yml` for the arm column's accepted values and the population relation's columns.
- Produces: a frozen `Protocol` and `protocol_sha256(path) -> str`.

- [ ] **Step 1: Define the protocol contract**

```python
DECISION_RULE_CANONICAL = {
    "ship": "ci_lower > 0 and point_estimate >= practical_threshold and no stop_on_breach guardrail is breached",
    "stop": "ci_upper < 0 or any stop_on_breach guardrail is breached",
    "otherwise": "inconclusive",
}
ESTIMATORS = ("difference_in_differences", "post_period_difference")
DIRECTIONS = ("no_decrease", "no_increase")


@dataclass(frozen=True)
class Guardrail:
    metric: str
    direction: str
    tolerance: float
    stop_on_breach: bool


@dataclass(frozen=True)
class Protocol:
    experiment: str
    scenario: str
    unit: str
    assignment_relation: str
    arm_column: str
    campaign_id: str
    arms: dict[str, float]
    population_relation: str
    population_require: tuple[str, ...]
    primary: str
    estimator: str
    guardrails: tuple[Guardrail, ...]
    secondary: tuple[str, ...]
    strata: tuple[str, ...]
    observation_horizon_hours: int
    minimum_units_per_arm: int
    practical_threshold: float
    minimum_detectable_effect: float
    bootstrap_seed: int
    bootstrap_draws: int
    interval: float
    sample_ratio_alpha: float
    registered_at_commit: str
    protocol_sha256: str
    path: Path
```

The decision rule is parsed, not evaluated: `load_protocol` requires the `decision_rule` block to equal `DECISION_RULE_CANONICAL` exactly and raises `ProtocolError("decision rule outside the fixed vocabulary")` otherwise. Outcome, guardrail, secondary, and strata columns are checked against the population relation's `columns` in `game_analytics/models/hybrid_subscription/marts/schema.yml`; arm names are checked against the arm column's `accepted_values` in `staging/schema.yml`.

- [ ] **Step 2: Implement the lock**

```python
def protocol_sha256(document: dict[str, object]) -> str:
    body = {key: value for key, value in document.items() if key != "registration"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
```

`load_protocol` computes the hash over the parsed document and raises `ProtocolError("protocol amended after registration")` when it differs from `registration.protocol_sha256`. The 40-character `registered_at_commit` is validated for form only here; reachability is a docs test:

```python
def test_registered_commit_is_an_ancestor_of_head() -> None:
    for path in sorted(Path("docs/experiments").glob("*.yaml")):
        protocol = load_protocol(path)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", protocol.registered_at_commit, "HEAD"],
            check=False,
        )
        assert result.returncode == 0, f"{path}: registered commit is not reachable from HEAD"
```

The test passes vacuously while `docs/experiments/` is empty and starts guarding in Task 9.

- [ ] **Step 3: Write the fixtures and run**

`valid.yaml` is the spec's example with the hash filled in by a one-off `python -c` that calls `protocol_sha256`, and a `registered_at_commit` of forty zeros (form-valid; the reachability test reads only `docs/experiments/`). Each malformed fixture breaks exactly one rule.

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee/test_protocol.py tests/docs/test_experiment_registration.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/analytics_lab/referee tests/referee tests/docs/test_experiment_registration.py
git commit -m "feat(referee): load and lock pre-registered protocols"
```

### Task 3: Units fact and readout mart

**Files:**
- Create: `game_analytics/models/hybrid_subscription/intermediate/int_hybrid_subscription__experiment_units.sql`
- Create: `game_analytics/models/hybrid_subscription/marts/fct_hybrid_subscription__experiment_units.sql`
- Create: `game_analytics/models/hybrid_subscription/marts/mart_hybrid_subscription__experiment_readout.sql`
- Create: the three singular tests named in Task 1
- Modify: `intermediate/schema.yml`, `marts/schema.yml`, `marts/kpi_schema.yml`
- Create: `tests/dbt/test_hybrid_subscription_experiment_sql.py`

**Interfaces:**
- Consumes: `fct_hybrid_subscription__marketing_exposures` (`eligible_experiment_arm`, `campaign_id`, `player_id`), `int_hybrid_subscription__analysis_population` (`index_at_utc`, `is_population_eligible`, `exclusion_reason`, `ingestion_mature_through_at_utc`), `fct_hybrid_subscription__player_behavior_28d` (`analysis_period`, `is_window_mature`, the five outcomes, the three strata).
- Produces: one row per unit; one row per `experiment_arm × prior_payer_status × platform`.

- [ ] **Step 1: Write the SQL-level tests first**

Reuse the `build(db, name)` harness from `tests/dbt/test_hybrid_subscription_population_sql.py`, which compiles a model against DuckDB fixture tables by substituting `ref()`. Fixtures are small hand-written frames: four exposures (one per arm, one late with a null eligible arm, one for an ineligible player), matching population and behaviour rows.

```python
def test_units_exclude_late_and_ineligible_exposures_and_immature_windows(): ...
def test_units_are_unique_per_player_with_non_null_arm(): ...
def test_readout_counts_reconcile_to_units_and_exclusions_by_arm(): ...
def test_readout_publishes_null_means_on_zero_units(): ...
```

Expected: FAIL (models absent).

- [ ] **Step 2: Implement the intermediate model**

```sql
with assigned as (
    select
        exposure.player_id,
        exposure.eligible_experiment_arm as experiment_arm,
        exposure.campaign_id
    from {{ ref('fct_hybrid_subscription__marketing_exposures') }} exposure
    where exposure.eligible_experiment_arm is not null
),
population as (
    select player_id, index_at_utc, is_population_eligible, ingestion_mature_through_at_utc
    from {{ ref('int_hybrid_subscription__analysis_population') }}
),
behaviour as (
    select * from {{ ref('fct_hybrid_subscription__player_behavior_28d') }}
),
pre as (select * from behaviour where analysis_period = 'pre'),
post as (select * from behaviour where analysis_period = 'post')
select
    assigned.player_id,
    assigned.experiment_arm,
    assigned.campaign_id,
    population.index_at_utc,
    population.ingestion_mature_through_at_utc,
    pre.prior_payer_status,
    pre.platform,
    pre.acquisition_channel,
    pre.session_count as pre_session_count,
    post.session_count as post_session_count,
    post.session_count - pre.session_count as session_count_change,
    -- same three columns for liveops_participation_count,
    -- standalone_store_net_revenue_usd, subscription_net_revenue_usd,
    -- total_net_revenue_usd
from assigned
join population using (player_id)
join pre using (player_id)
join post using (player_id)
where population.is_population_eligible
  and pre.is_window_mature
  and post.is_window_mature
```

The fact model is a passthrough adding `player_id as unit_id`, in the pattern of `fct_hybrid_subscription__player_behavior_28d`.

- [ ] **Step 3: Implement the readout mart**

One row per `experiment_arm × prior_payer_status × platform`:

- `assigned_count` from `assigned` joined to players for strata (assignment precedes any exclusion);
- `ineligible_population_count` where `is_population_eligible` is false;
- `immature_window_count` where either window is immature among the population-eligible;
- `unit_count`, and per outcome `pre_sum`, `post_sum`, `change_sum` over units;
- `ingestion_mature_through_at_utc` (the population's value, constant across rows);
- `case when unit_count > 0 then change_sum / unit_count end as change_mean` per outcome, so a zero denominator is null.

- [ ] **Step 4: Singular tests and schema**

`assert_hybrid_experiment_units_valid.sql` fails on a duplicate `player_id`, a null arm, or an arm outside `('control', 'offer')`. `assert_hybrid_late_exposures_excluded_from_units.sql` fails if any unit's `index_at_utc` is not strictly before that player's first subscription start. `assert_hybrid_experiment_readout_reconciles.sql` fails if any count or sum in the readout differs from the same aggregate computed directly over the units fact and the assignment/exclusion sets.

Document every column in the three schema files with `not_null`, `unique` on `player_id`/`unit_id`, and `accepted_values` on `experiment_arm`.

- [ ] **Step 5: Build and run**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/dbt -v
( cd game_analytics && dbt build --selector hybrid_subscription --indirect-selection cautious --profiles-dir . )
```

Expected: tests PASS; build completes with the previous `PASS=348` plus the new models and tests, `ERROR=0`.

- [ ] **Step 6: Commit**

```bash
git add game_analytics/models/hybrid_subscription game_analytics/tests/hybrid_subscription tests/dbt
git commit -m "feat(dbt): publish experiment units and arm-by-stratum readout"
```

### Task 4: Shared provenance and the readout loader

**Files:**
- Create: `src/analytics_lab/provenance.py`
- Modify: `src/analytics_lab/analysis/live_strategy_retention.py`
- Create: `src/analytics_lab/referee/readout.py`
- Create: `tests/referee/test_readout.py`

**Interfaces:**
- Consumes: a DuckDB path and a `Protocol`.
- Produces: `Readout(units: DataFrame, readout: DataFrame, incidents: DataFrame, fingerprint: dict)`.

- [ ] **Step 1: Move provenance helpers to one place**

`provenance.py` exports `fingerprint_inputs(frame)` (moved verbatim with its tests), `execution_platform() -> dict`, `package_versions() -> dict` including `pyarrow`, and `code_version(repo_root) -> str` via `git rev-parse HEAD`. `live_strategy_retention` imports `fingerprint_inputs` from it so `tests/analysis/test_live_strategy_retention.py` is unchanged.

- [ ] **Step 2: Load the three relations read-only from `game_analytics/`**

Use the `_working_directory` pattern from `live_strategy_retention`. Queries select exactly the columns the protocol names plus `player_id`, `experiment_arm`, `index_at_utc`, and the strata; the loader raises `ReadoutError` if a named column is absent or if the units/readout counts do not reconcile. The fingerprint is computed over the units frame.

- [ ] **Step 3: Test against a temporary DuckDB built from fixture frames, then commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee/test_readout.py tests/analysis/test_live_strategy_retention.py -v
git add src/analytics_lab/provenance.py src/analytics_lab/analysis/live_strategy_retention.py src/analytics_lab/referee/readout.py tests/referee/test_readout.py
git commit -m "feat(referee): load governed readouts with shared provenance"
```

### Task 5: Preconditions, one refusal each

**Files:**
- Create: `src/analytics_lab/referee/preconditions.py`, `tests/referee/test_preconditions.py`

**Interfaces:**
- Consumes: `Protocol`, `Readout`.
- Produces: `Preconditions` (the JSON block in the spec) and the first `Refusal(reason, evidence)` if any.

- [ ] **Step 1: Write one failing test per precondition, in the spec's order**

```python
def test_amended_protocol_is_refused_with_hash_mismatch(): ...
def test_unit_indexed_after_subscription_start_is_refused(): ...
def test_sample_ratio_mismatch_is_refused_at_registered_alpha(): ...
def test_balanced_allocation_passes_with_hand_calculated_chi_square(): ...
def test_asymmetric_attrition_by_arm_is_refused(): ...
def test_immature_readout_is_refused_and_never_estimated(): ...
def test_uncontained_incident_is_refused(): ...
def test_minimum_units_shortfall_is_not_a_refusal(): ...
```

The hand calculation: 600 control and 400 offer at 0.5/0.5 gives `x = (600-500)^2/500 + (400-500)^2/500 = 40`, and `erfc(sqrt(20))` is below `1e-9`; 510/490 gives `x = 0.4` and a p-value near 0.53.

- [ ] **Step 2: Implement**

```python
def chi_square_p_value_df1(statistic: float) -> float:
    return math.erfc(math.sqrt(statistic / 2.0))


def sample_ratio(observed: dict[str, int], expected_share: dict[str, float], alpha: float) -> dict:
    total = sum(observed.values())
    statistic = sum(
        (observed[arm] - total * share) ** 2 / (total * share)
        for arm, share in expected_share.items()
    )
    p_value = chi_square_p_value_df1(statistic)
    return {"expected": expected_share, "observed": observed, "chi_square": statistic,
            "p_value": p_value, "passed": p_value >= alpha}
```

Differential attrition runs the same 2×2 test twice, once per exclusion category (`ineligible_population_count`, `immature_window_count`) against `assigned_count`, and refuses if either fails. Maturity requires `immature_window_count == 0` in both arms and `max(index_at_utc) + observation_horizon_hours <= ingestion_mature_through_at_utc`. Incidents require every `decision_status` in `('contained', 'clear')` and a non-empty relation. Assignment-before-exposure is asserted from the units fact's `index_at_utc` against `first_subscription_at_utc` from the exposures relation. The minimum-units check records `met: false` without refusing.

- [ ] **Step 3: Run and commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee/test_preconditions.py -v
git add src/analytics_lab/referee/preconditions.py tests/referee/test_preconditions.py
git commit -m "feat(referee): refuse on protocol, ratio, attrition, maturity and containment failures"
```

### Task 6: Estimators and stratified bootstrap

**Files:**
- Create: `src/analytics_lab/referee/estimate.py`, `tests/referee/test_estimate.py`

**Interfaces:**
- Consumes: the units frame, `Protocol`.
- Produces: `Estimate(point, interval, standard_error, units_by_arm, by_stratum)` for the primary, each guardrail, and each secondary.

- [ ] **Step 1: Failing tests**

```python
def test_post_period_difference_is_offer_minus_control_post_means(): ...
def test_difference_in_differences_uses_change_scores(): ...
def test_bootstrap_is_deterministic_for_a_seed_and_order_insensitive(): ...
def test_bootstrap_resamples_within_arm_and_stratum_cells(): ...
def test_true_null_frame_yields_interval_spanning_zero(): ...
def test_guardrail_breach_uses_the_adverse_interval_bound_not_the_point(): ...
```

- [ ] **Step 2: Implement**

Resample with replacement within each `(experiment_arm, *strata)` cell using `np.random.default_rng(protocol.bootstrap_seed)`, recompute the estimator per draw, take the central `interval` fraction of draws, and report the standard deviation of draws as `standard_error`. Guardrails: `no_decrease` is breached when `interval[0] < -tolerance`; `no_increase` when `interval[1] > tolerance`.

- [ ] **Step 3: Run and commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee/test_estimate.py -v
git add src/analytics_lab/referee/estimate.py tests/referee/test_estimate.py
git commit -m "feat(referee): intent-to-treat estimators with stratified bootstrap"
```

### Task 7: Generator knobs without touching the default stream

**Files:**
- Modify: `src/analytics_lab/generation/base.py`, `src/analytics_lab/generation/hybrid_subscription.py`, `src/analytics_lab/generate.py`
- Modify: `tests/generation/test_hybrid_subscription.py`, `tests/generation/test_cli.py`

**Interfaces:**
- Consumes: `GenerationConfig` with `treatment_effect: float = 0.0` and `allocation_skew: float = 0.5`.
- Produces: identical tables at defaults; extra post-window `offer`-arm sessions and standalone-store transactions at a positive effect; a skewed arm distribution at a non-default skew.

- [ ] **Step 1: Failing tests**

```python
def test_default_knobs_are_frame_identical_to_an_unknobbed_generation(): ...
def test_treatment_effect_adds_post_window_rows_only_for_offer_arm_players(): ...
def test_allocation_skew_changes_only_the_arm_distribution(): ...
def test_cli_accepts_the_knobs_and_records_them_in_the_manifest(): ...
```

The first test compares every table from `generate(config())` against `generate(config(treatment_effect=0.0, allocation_skew=0.5))` with `pdt.assert_frame_equal`, and against a generation on the current `main` captured once as content hashes in the test module for `players`, `sessions`, `store_transactions`, and `marketing_exposures` at the test scale.

- [ ] **Step 2: Implement**

In `_marketing_exposures`, keep `rng.choice(["control", "offer"])` verbatim when `allocation_skew == 0.5`; otherwise `rng.choice(["control", "offer"], p=[1 - skew, skew])`. Apply the treatment effect as a post-pass in `generate()` after every table exists, entered only when `treatment_effect > 0`:

- `lift_rng = np.random.default_rng(config.seed + 1_000_003)`;
- for each `offer`-arm player, append `round(treatment_effect * 7)` sessions and `round(treatment_effect * 2)` `currency_bundle_small` succeeded transactions at `lift_rng` timestamps inside that player's post window, with ids continuing each table's sequence and the same timestamp-evidence columns as the originals;
- record `treatment_effect` and `allocation_skew` in the manifest.

- [ ] **Step 3: Run and commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/generation -v
git add src/analytics_lab/generation src/analytics_lab/generate.py tests/generation
git commit -m "feat(generation): designed treatment lift and allocation skew for the referee"
```

### Task 8: Decision rule, verdict artifact, CLI

**Files:**
- Create: `src/analytics_lab/referee/verdict.py`, `src/analytics_lab/referee/__main__.py`
- Create: `tests/referee/test_verdict.py`, `tests/referee/test_cli.py`
- Create: `tests/referee/fixtures/ship.yaml`, `stop.yaml`, `inconclusive.yaml`

**Interfaces:**
- Consumes: `Protocol`, `Preconditions`, estimates.
- Produces: the verdict document in the spec's shape; `python -m analytics_lab.referee --protocol --db --output [--check-label <committed verdict>]`.

- [ ] **Step 1: Failing tests on frames built in-process from Task 7's generator**

```python
def test_default_generation_is_inconclusive(): ...
def test_lift_above_threshold_ships(): ...
def test_lift_below_threshold_is_inconclusive(): ...
def test_lift_with_planted_stop_guardrail_breach_stops(): ...
def test_skewed_allocation_is_refused_for_sample_ratio(): ...
def test_verdict_one_unit_from_the_threshold_is_near_boundary(): ...
def test_verdict_metadata_is_complete(): ...
def test_cli_exits_zero_on_refuse_and_nonzero_on_malformed_protocol(): ...
def test_check_label_fails_when_the_committed_label_differs(): ...
```

Units frames for these tests are derived from generated tables with a small pure-Python window helper kept in `tests/referee/conftest.py`; it mirrors the units model only closely enough to carry the designed effect through, and the SQL model itself is covered by Task 3.

- [ ] **Step 2: Implement the rule and the margin**

Order: `STOP` if `interval[1] < 0` or any `stop_on_breach` guardrail breached; `SHIP` if `interval[0] > 0`, `point >= practical_threshold`, and no `stop_on_breach` breach; otherwise `INCONCLUSIVE` with reasons (`interval spans zero`, `point estimate below practical threshold`, `units below registered minimum`). Margin: `SHIP` → `min(interval[0], point - practical_threshold)`; `STOP` by interval → `-interval[1]`; `STOP` by guardrail → how far the adverse bound exceeds tolerance; `INCONCLUSIVE` → distance of the nearer bound to zero, or `practical_threshold - point`. `near_boundary` is `margin < standard_error`.

- [ ] **Step 3: Implement the CLI**

Exit `0` for any label; `2` for `ProtocolError` or `ReadoutError`. `--check-label` loads the committed verdict and exits `3` when labels differ, printing both.

- [ ] **Step 4: Run and commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee -v
git add src/analytics_lab/referee tests/referee
git commit -m "feat(referee): decide on the interval and publish the verdict"
```

### Task 9: Memo generation under the governed template

**Files:**
- Create: `src/analytics_lab/referee/memo.py`, `tests/referee/test_memo.py`, `tests/docs/test_experiment_decision_memo.py`
- Modify: `tests/docs/test_templates_are_enforced.py`

- [ ] **Step 1: Failing tests**

`test_memo.py`: the rendered memo contains the five template headings plus `## Verdict` and `## Protocol`; Observed facts are copied from the verdict numbers; the Assumptions section states the estimand is the effect of assignment and the bootstrap covers sampling variation only. `test_experiment_decision_memo.py`: each memo under `reports/experiments/` cites its verdict's `code_version`, `executed_at_utc`, platform, and fingerprint prefix. Add `reports/experiments/hybrid_subscription_launch_offer_decision_memo.md` to `MEMOS` in `test_templates_are_enforced.py`; it fails until Task 10 publishes the file.

- [ ] **Step 2: Implement `render(verdict) -> str` and commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/referee/test_memo.py -v
git add src/analytics_lab/referee/memo.py tests/referee/test_memo.py tests/docs
git commit -m "feat(referee): render the verdict as a governed decision memo"
```

### Task 10: Register the first protocol and publish the verdict

**Files:**
- Create: `docs/experiments/hybrid_subscription_launch_offer.yaml`
- Create: `reports/experiments/hybrid_subscription_launch_offer_verdict.json`, `reports/experiments/hybrid_subscription_launch_offer_decision_memo.md`

**Interfaces:**
- Owner action required. This task cannot be completed by a worker alone.

- [ ] **Step 1: Owner sets the registered values**

Copy the spec's example protocol and set `practical_threshold`, `minimum_detectable_effect`, and `minimum_units_per_arm`. Primary is `total_net_revenue_usd`; estimator is the owner's choice between the two. Record `registered_at_commit` as the current `HEAD` — the commit the protocol was authored against, which the reachability test requires to be an ancestor — and fill `protocol_sha256` with:

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -c "
import yaml, sys
from analytics_lab.referee.protocol import protocol_sha256
print(protocol_sha256(yaml.safe_load(open('docs/experiments/hybrid_subscription_launch_offer.yaml'))))"
```

- [ ] **Step 2: Build and adjudicate on the platform that will own the published numbers**

```bash
bash scripts/validation/run_hybrid_subscription_checks.sh 2>&1 | tail -2
PYTHONPATH="$PWD/src" ./.venv/bin/python -m analytics_lab.referee \
  --protocol docs/experiments/hybrid_subscription_launch_offer.yaml \
  --db game_analytics/dev.duckdb \
  --output reports/experiments/hybrid_subscription_launch_offer_verdict.json
```

Expected: label `INCONCLUSIVE` on the default generation, because the arm is a true null. Any other label on default data is a defect in the referee or the models, not a finding.

- [ ] **Step 3: Render the memo, run the docs tests, commit**

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m analytics_lab.referee.memo \
  reports/experiments/hybrid_subscription_launch_offer_verdict.json \
  > reports/experiments/hybrid_subscription_launch_offer_decision_memo.md
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest tests/docs -v
git add docs/experiments reports/experiments
git commit -m "docs(experiments): register the launch-offer protocol and publish its verdict"
```

### Task 11: Catalogue, trusted questions, guide, README

**Files:**
- Modify: `docs/metrics/hybrid_subscription.md`, `docs/ai-audit/hybrid_subscription_questions.yaml`, `scripts/evaluation/hybrid_subscription_answers.json`, `tests/evaluation/test_hybrid_subscription_questions.py`, `docs/getting_started.md`, `README.md`

- [ ] **Step 1: Catalogue**

Add a row for `mart_hybrid_subscription__experiment_readout` to the supporting-diagnostics table and a `## Experiment referee` section defining the four labels, the preconditions, and the boundary: a `SHIP` is a claim about the effect of assignment within the synthetic population and nothing wider. Run `tests/docs/test_hybrid_subscription_metric_catalogue.py` first; if it pins the heading list, extend it in the same commit.

- [ ] **Step 2: Questions and answers**

Add cases `hybrid_referee_verdict_labels` (standard definition), `hybrid_referee_sample_ratio` (standard definition), `hybrid_referee_immature_readout` (unanswerable, refusal), `hybrid_referee_eventual_subscriber_causal_claim` (adversarial, refusal), `hybrid_referee_relax_guardrail_after_readout` (adversarial, refusal). Mirror each in the answers file. Add the two new relations to `APPROVED_RELATIONS` and the five ids to `RISK_IDS` in the evaluation test.

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m analytics_lab.evaluate \
  --scenario hybrid_subscription \
  --questions docs/ai-audit/hybrid_subscription_questions.yaml \
  --answers scripts/evaluation/hybrid_subscription_answers.json \
  --output reports/hybrid_subscription/agent_evaluation.json
```

Expected: exit 0, every case passing.

- [ ] **Step 3: Guide and README, then commit**

One numbered step in `docs/getting_started.md` after the evaluation step: register, build hybrid, run the referee, read the verdict. One sentence in the README's hybrid case study linking the verdict and memo. The guide test checks every path it names exists, so add the step only after Task 10's files are committed.

```bash
git add docs reports/hybrid_subscription/agent_evaluation.json scripts/evaluation tests/evaluation README.md
git commit -m "docs(hybrid): govern the experiment readout and referee verdicts"
```

### Task 12: Label gate in CI and the final gate

**Files:**
- Modify: `scripts/validation/run_scenario_checks.sh`, `tests/validation/test_ci_quality_gates.py`

- [ ] **Step 1: Extend the scenario gate**

After the dbt build, for every protocol under `docs/experiments/` whose `scenario` matches, run the referee against the fresh build with `--check-label` pointing at the committed verdict. Update `test_ci_quality_gates.py` so its script assertions include the referee invocation.

- [ ] **Step 2: Run the full gate from a clean state**

```bash
./.venv/bin/ruff check src scripts tests
PYTHONPATH="$PWD/src" ./.venv/bin/python -m pytest -q
bash scripts/validation/run_shared_checks.sh 2>&1 | tail -3
for s in live_strategy subscription hybrid_subscription; do
  rm -f game_analytics/dev.duckdb game_analytics/dev.duckdb.wal
  rm -rf data/raw
  bash scripts/validation/run_${s}_checks.sh 2>&1 | tail -2
done
git diff --check
git status --short
```

Expected: Ruff clean; every test passing; `PASS=4`, `PASS=153`, `PASS=102`, and the hybrid count from Task 3, all with `ERROR=0`; the hybrid gate prints the committed label and `label reproduced`; no tracked modifications.

- [ ] **Step 3: Commit, push, open the pull request**

```bash
git add scripts/validation tests/validation
git commit -m "ci: reproduce the committed experiment verdict label in the hybrid gate"
git push -u origin cld/youthful-feynman-q8uzx8
```

Open a PR to `main` summarizing the protocol lock, the preconditions, the estimator and bootstrap, the designed effects, the published verdict and memo, and the exact gate output. The PR is mergeable only when CI reproduces the committed label on Linux.
