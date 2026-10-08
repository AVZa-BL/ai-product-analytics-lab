# Referee — Experiment Review Module: Design

**Date:** 2026-09-28
**Status:** Approved design (Alexander Zatey), pending implementation plan
**Amendments:** 1 (2026-09-29): repository layout and settled validation rules, see section 16. 2 (2026-09-30): milestone 2 decisions, see section 17. 3 (2026-10-02): milestone 2c decisions, see section 18. 4 (2026-10-04): milestone 3 decisions, see section 19. 5 (2026-10-05): milestone 4 decisions, see section 20. 6 (2026-10-08): milestone 4b decisions, see section 21. Sections 0 to 15 are unchanged.
**Scope:** New module inside `ai-product-analytics-lab`; first milestone is the experiment spec schema

This document is the handoff from the design conversation into Claude Code. It is self-contained: nothing outside this file and the repository is needed to start.

---

## 0. Before you start — three uncommitted files on `main`

`git status` on `main` shows unfinished work from PR #20 (`fix/live-strategy-provenance`):

```
 M reports/live_strategy/d7_retention_diagnostic.md          (2 lines)
 M reports/live_strategy/d7_retention_diagnostic_results.json (2 lines)
 M tests/docs/test_live_strategy_decision_memo.py            (+18 lines)
```

The test file adds `test_memo_provenance_matches_the_results_artifact`, which asserts that the memo cites the results JSON's `metadata.code_version` and `metadata.executed_at_utc`. **In the current working tree this test fails**: the memo cites `9d97f009…` / `2026-09-24T01:14:31Z`, the JSON carries `e06418d1…` / `2026-09-24T17:28:36Z`. The JSON diff touches only those two metadata lines, so the analytical numbers are identical across runs (deterministic, seed 42). Aligning the memo to the JSON is therefore honest.

Resolve it **first, on its own branch, before any Referee work**, so the two concerns never share a PR:

1. `git switch -c fix/live-strategy-provenance-guard`
2. Edit the memo's two provenance lines to the JSON's values (`e06418d1c1427152f98ef892a620d02358560f8a`, `2026-09-24T17:28:36.426495Z`).
3. Add the missing trailing newline at the end of the test file and remove the whitespace-only line before the new test.
4. `ruff check src scripts tests && python -m pytest tests/docs -q` — the new test must pass.
5. Commit as `test(live_strategy): guard memo provenance against the results artifact`, push, open the PR.
6. Return to `main`, `git pull --ff-only`, confirm `git status --short` is empty.

---

## 1. Objective

Build **Referee**: a deterministic experiment reviewer that takes a structured description of an A/B/n test and returns findings with severity, evidence, and remediation — at design time (hypothesis, power, groups, procedure) and at readout time (method selection, p-values, confidence intervals, guardrails, verdict).

One-line pitch: **ruff for experiments.** Every warning is a named rule. Advice is generated from rules, not improvised.

Referee is advisory. It never ships, stops, or decides anything on its own; it produces a recommendation with the blocking rule IDs attached. This matches the repository's existing stance that the agent evaluation "does not authorize autonomous decisions".

## 2. Why this module, why now

- The lab currently holds **no randomized evidence**. All three diagnostics are observational; the hybrid scenario's matched-control analysis explicitly refuses to claim causality. A randomized module closes the largest capability gap in the portfolio.
- Experimentation (SRM, variance reduction, stopping rules, multiple comparisons) is the most deeply probed skill in senior product-analyst interview loops.
- The hybrid scenario already asks "does the subscription cannibalize store purchases?" and answers with matched controls. A randomized version of the same question, with a section on where the two answers diverge and why, is a stronger story than either alone.

## 3. Naming, placement, conventions

| Item | Value |
|---|---|
| Module name | Referee |
| Package | `src/analytics_lab/referee/` (next to `generation/`, `analysis/`; installed by the existing `pip install -e .`) |
| Tests | `tests/referee/` (no `__init__.py`, matching the other test directories) |
| Docs | `docs/referee/` — rule catalogue, spec template, how-to |
| CLI (milestone 2+) | `python -m analytics_lab.referee review-design <spec.yaml>` and `review-results <spec.yaml> <results.parquet>` |
| Branches | `feat/referee-<topic>` |
| Commits | `feat(referee): …`, `test(referee): …`, `docs(referee): …` |

## 4. Core design decision: rules first, narration second

**Findings engine (deterministic, the product).** Pure Python; every check is a rule with:

```python
@dataclass(frozen=True)
class Finding:
    rule_id: str          # e.g. "DES-003"
    severity: str         # "blocker" | "warning" | "info"
    title: str
    evidence: dict        # the numbers that triggered it
    why_it_matters: str
    remediation: str
    references: tuple[str, ...]
```

A review is a list of findings plus a verdict. Same spec in → same findings out. Fully unit-testable: each rule has a triggering and a non-triggering fixture.

**Narration layer (optional, later).** A language model may restate findings in plain language for a memo. It may only speak about findings the engine emitted; anything else is refused. Its evaluation set is dominated by refusal cases ("can we call it on day 3?", "arm C is significant in Germany, ship there?", "SRM is only 0.4%, fine, right?"). It is not part of milestones 1–4.

Rationale: improvised statistical advice is the version a reviewer will take apart; rule-derived advice is testable, reproducible, and consistent with the repository's evidence discipline.

## 5. Components mapped to requirements

| Requirement (as stated) | Component | Responsibility |
|---|---|---|
| Describe experiment, give parameters | `spec.py` | Typed, validated experiment spec (section 6). Fails loudly on malformed input. |
| Form / evaluate the hypothesis | `rules/hypothesis.py` | Falsifiable? direction stated? primary metric governed? unit of analysis = unit of randomization? ratio declared as ratio? |
| Sample sizes, baselines | `power.py` | Required n per arm and total, duration in full weeks, MDE feasibility; multi-arm α adjustment. |
| Design test groups | `rules/design.py` | Allocation efficiency, stratification suggestions, holdout, bucketing salt, interference risk for social/multiplayer products. |
| Support the test procedure | `rules/procedure.py` | SRM cadence, guardrail monitoring, peeking policy, stopping rule, minimum duration, what to log. |
| Warn: limitations, drawbacks, issues | rule catalogue (section 8) + `docs/referee/rules.md` | Every rule documented with rationale and reference. |
| Method selection | `methods.py` | Decision table: metric kind × distribution × design → test; states what it chose, what it rejected, and why. |
| Results: p-values and all parameters | `analysis.py` | SRM χ², effect (absolute, relative), CI, p, adjusted p, achieved n vs registered n, guardrail deltas, effect by exposure week, sample-ratio drift. |
| Highlight issues, give advice | `report.py` | Verdict ∈ {ship, do_not_ship, inconclusive, invalid} with blocking rule IDs; decision memo in `docs/templates/decision-memo.md` structure; provenance (spec hash, data hash, git SHA). |

## 6. Experiment spec schema (milestone 1 deliverable)

Representation: `@dataclass(frozen=True)` classes built by `ExperimentSpec.from_dict(...)`. Standard library only — no pydantic, no YAML in milestone 1 (YAML loading arrives in milestone 2 together with the CLI; see section 14 on dependencies).

```yaml
referee_spec_version: 1
id: hybrid_offer_page_2026_10            # slug: ^[a-z0-9_]+$
title: Subscription offer page variants
owner: analytics

hypothesis:
  null: "The offer page variant does not change 7-day subscription conversion."
  alternative: "Variant B increases 7-day subscription conversion."
  direction: increase                     # increase | decrease | two_sided

population:
  randomization_unit: player              # player | user | device | session | cluster
  analysis_unit: player                   # defaults to randomization_unit
  eligibility: "Players who open the offer page and are not subscribed at exposure."
  daily_eligible_units: 4200              # integer >= 1
  exposure_trigger: offer_page_view       # the event that marks first exposure

arms:
  - name: control
    allocation: 0.5
    is_control: true
  - name: variant_b
    allocation: 0.5

primary_metric:
  name: subscription_conversion_7d
  kind: binary                            # binary | continuous | ratio
  baseline: 0.032                         # rate (binary) | mean (continuous) | ratio value (ratio)
  baseline_std: null                      # required > 0 for continuous and ratio; must be null for binary
  governed_reference: docs/metrics/hybrid_subscription.md   # optional; rule HYP-002 warns if absent

guardrails:                               # may be empty; rule PRO-003 warns if empty
  - name: refund_rate_14d
    kind: binary
    baseline: 0.018
    harmful_direction: increase           # increase | decrease
    tolerance_relative: 0.10              # breach when worse than baseline × (1 ± tolerance)

design:
  mde_relative: 0.05                      # > 0
  alpha: 0.05                             # 0 < alpha < 1
  power: 0.80                             # 0 < power < 1
  sided: two_sided                        # two_sided | one_sided
  planned_duration_days: 14               # >= 1
  min_duration_days: 14                   # >= 1 and <= planned_duration_days
```

### 6.1 Validation rules (raise `SpecError`, a `ValueError` subclass)

Collect **all** violations, then raise once with every message listed — one round trip for the author, not ten.

- `referee_spec_version` must equal 1.
- Unknown keys at any level are errors (catches typos such as `mde_relativ`).
- `id` matches `^[a-z0-9_]+$`; `title` non-empty.
- `hypothesis.null` and `.alternative` non-empty; `direction` in the enum.
- `population.randomization_unit` in the enum; `analysis_unit` defaults to it when omitted; `daily_eligible_units` integer ≥ 1; `exposure_trigger` non-empty.
- `arms`: at least two; unique names; exactly one `is_control: true`; every allocation > 0; allocations sum to 1 within 1e-9.
- `primary_metric.kind` in the enum; `binary` ⇒ 0 < baseline < 1 and `baseline_std` is null; `continuous`/`ratio` ⇒ `baseline_std` > 0; `baseline` finite.
- `guardrails`: unique names; same metric rules as above; `harmful_direction` in the enum; `tolerance_relative` > 0.
- `design`: bounds as annotated; `min_duration_days ≤ planned_duration_days`.

**Separation of concerns:** validation asks "is the spec well-formed?"; review rules ask "is the experiment well-designed?". An `analysis_unit` different from the `randomization_unit` is *valid* (the schema accepts it) but *reviewable* (rule HYP-003 emits a warning). Keep those two layers apart.

## 7. Milestone 1 tests — `tests/referee/test_spec.py`

Build the dict inline in a fixture (no YAML yet). Required cases:

1. A valid spec round-trips: `from_dict` returns frozen dataclasses with the expected values; `analysis_unit` defaults to `randomization_unit` when omitted.
2. Allocations summing to 0.9 → `SpecError` whose message mentions `allocation`.
3. No control arm, and two control arms → `SpecError`.
4. Binary baseline of 1.2 → `SpecError`; continuous metric without `baseline_std` → `SpecError`.
5. `alpha = 1.0`, `power = 0`, `mde_relative = -0.1` → `SpecError`.
6. Unknown top-level key `mde_relativ` → `SpecError` naming the key.
7. Several violations at once → **one** `SpecError` whose message lists all of them.

## 8. Rule catalogue — seed list

IDs are stable; documentation lives in `docs/referee/rules.md`. Severity is the default; some rules escalate on thresholds.

**Hypothesis (HYP)**
- HYP-001 blocker — hypothesis not falsifiable (no null, no direction, or metric not measurable in the spec).
- HYP-002 warning — primary metric has no governed reference in `docs/metrics/`.
- HYP-003 warning — analysis unit differs from randomization unit (variance underestimated; use cluster-robust SE or aggregate to the randomization unit).
- HYP-004 warning — one-sided test requested; require pre-registered justification.
- HYP-005 warning — primary metric is a ratio of two unit-level quantities; delta method required.

**Design (DES)**
- DES-001 blocker — underpowered: required n exceeds achievable n at planned duration (states the achievable MDE instead).
- DES-002 warning — planned duration not a whole number of weeks (weekly seasonality).
- DES-003 warning — planned duration < 14 days (novelty / primacy effects unobservable).
- DES-004 info — unequal allocation; reports power loss vs equal split.
- DES-005 warning — more than two arms with no α adjustment declared; applies Bonferroni by default, recommends Dunnett.
- DES-006 warning — randomization unit is player/user in a product with social or multiplayer features (interference; consider cluster randomization or state the SUTVA assumption).
- DES-007 blocker — exposure trigger is (or can occur) after the treatment starts acting (post-treatment selection).
- DES-008 warning — no pre-period covariate declared; CUPED unavailable.

**Procedure (PRO)**
- PRO-001 blocker — no stopping rule; peeking without a sequential design is prohibited.
- PRO-002 warning — no SRM check cadence declared (recommend daily).
- PRO-003 warning — no guardrails declared.
- PRO-004 info — bucketing salt not declared; reuse of a previous salt correlates assignment across experiments.

**Results (RES)**
- RES-001 blocker — SRM: χ² p < 0.001 against registered allocation. Verdict becomes `invalid`.
- RES-002 blocker — achieved n below registered n.
- RES-003 blocker — observed duration shorter than registered `min_duration_days`.
- RES-004 blocker — guardrail breached beyond tolerance in the harmful direction.
- RES-005 warning — post-hoc power requested; refused, reports CI width instead.
- RES-006 warning — multiple arms or metrics without adjusted p-values.
- RES-007 warning — effect by exposure week is non-stationary (novelty or decay).
- RES-008 warning — heavy-tailed metric (kurtosis / top-1% share above threshold); bootstrap CI reported alongside t-test.
- RES-009 blocker — ratio metric analysed without delta method.
- RES-010 warning — segment result cited without pre-registration (subgroup fishing).
- RES-011 warning — sample ratio drifts over time even when the total passes.

## 9. Statistics (milestone 2 and 4)

Implementations live in `power.py` and `analysis.py`; every formula is validated in tests against a reference.

- **Two proportions**, per-arm n: `n = (z_{1-α/2}·√(2·p̄·q̄) + z_{1-β}·√(p₁q₁ + p₂q₂))² / (p₂ − p₁)²`. Reference: `statsmodels.stats.power.NormalIndPower` with `proportion_effectsize`.
- **Two means**, per-arm n: `n = 2·σ²·(z_{1-α/2} + z_{1-β})² / δ²`. Reference: `statsmodels.stats.power.TTestIndPower`.
- **Multi-arm**: Bonferroni `α/(k−1)` as the default; Dunnett noted as the less conservative option.
- **Duration**: `ceil(n_total / daily_eligible_units)` rounded up to whole weeks.
- **SRM**: χ² goodness-of-fit of observed arm counts vs registered allocation; flag at p < 0.001 (the threshold used in the Kohavi–Tang–Xu treatment of SRM).
- **Ratio metrics**: delta method, `Var(Y/X) ≈ (1/μ_X²)·[σ_Y² − 2·(μ_Y/μ_X)·σ_XY + (μ_Y/μ_X)²·σ_X²] / n`. Reference: bootstrap on the same fixture.
- **CUPED**: `θ = cov(Y, X_pre) / var(X_pre)`, `Y_adj = Y − θ·(X_pre − mean(X_pre))`. Reference: variance reduction on a fixture with known correlation.
- **Heavy tails**: percentile bootstrap CI (seeded) reported next to Welch t.
- **Multiple comparisons**: Bonferroni and Benjamini–Hochberg; Dunnett if `statsmodels` exposes it in the pinned version, otherwise documented as out of scope.

References: Kohavi, Tang, Xu, *Trustworthy Online Controlled Experiments* (2020); Deng, Xu, Kohavi, Walker, *Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data* (CUPED, WSDM 2013); Deng, Knoblich, Lu, *Applying the Delta Method in Metric Analytics* (2018, arXiv:1803.06336); Fabijan et al., *Diagnosing Sample Ratio Mismatch in Online Controlled Experiments* (KDD 2019); statsmodels power documentation.

## 10. Synthetic experiment in the hybrid scenario (milestone 3)

Extend the hybrid generator with a three-arm offer test (control, B, C) and two tables: `experiment_assignments` and `experiment_exposures`. Inject pathologies the reviewer must catch:

- SRM in arm C caused by a bucketing bug on one platform (RES-001, RES-011).
- Exposure logged after first purchase for a subset of players (DES-007).
- Heavy-tailed revenue per player (RES-008).
- Week-1 novelty spike that reverses (RES-007).
- A mid-test config change on one arm, recorded in the incident register.

dbt models: `int_hybrid_subscription__experiment_first_exposure` (dedup, first touch), `int_…__experiment_eligible_population` (pre-period covariates attached), `mart_…__experiment_arm_daily`, `mart_…__experiment_readout`. Same staging → intermediate → marts discipline and the same incident-containment pattern as the rest of the scenario.

## 11. Guardrails ("360" requirements)

- No verdict without a pre-registered spec; the results review recomputes the spec hash and refuses on mismatch.
- Refuse a verdict when achieved n < registered n or duration < registered minimum (RES-002, RES-003).
- Never auto-decide: output is a recommendation with reasons and blocking rule IDs.
- Specs carry no personal data by construction (metric names, rates, counts only).
- Deterministic outputs (seeded bootstrap) so CI can diff JSON reports.
- Provenance on every report: spec hash, data hash, git SHA, package versions — same fields the existing diagnostics publish.
- Narration layer, when added, is restricted to emitted findings and evaluated mainly on refusals.
- Keep raw evidence immutable; repairs happen downstream, as in the three existing scenarios.

## 12. Testing strategy

- Every rule: one triggering fixture, one non-triggering fixture.
- Power functions: agreement with `statsmodels` within 1 unit of n across a grid of baselines, MDEs, α, power.
- Delta method: agreement with a seeded bootstrap within tolerance.
- CUPED: variance reduction on a fixture with known ρ equals `1 − ρ²` within tolerance.
- SRM: known χ² fixtures.
- CLI: golden-file tests for `review-design` and `review-results` JSON output.
- Determinism: same inputs → byte-identical report.

## 13. Milestones

| # | Deliverable | Branch | Definition of done |
|---|---|---|---|
| 0 | Resolve section 0 | `fix/live-strategy-provenance-guard` | PR merged; `main` clean |
| 1 | `spec.py` + `tests/referee/test_spec.py` + `docs/referee/spec-template.yaml` | `feat/referee-spec` | ruff clean; pytest green; PR merged |
| 2 | `power.py`, `rules/hypothesis.py`, `rules/design.py`, `rules/procedure.py`, `Finding`, `review-design` CLI, YAML loading, `docs/referee/rules.md` | `feat/referee-design-review` | rules each tested both ways; power validated vs statsmodels |
| 3 | Synthetic experiment + dbt models + tests in the hybrid scenario | `feat/referee-hybrid-experiment` | `run_hybrid_subscription_checks.sh` green with the new nodes |
| 4 | `methods.py`, `analysis.py`, `report.py`, `review-results` CLI; results rules; decision memo | `feat/referee-results-review` | golden-file CLI tests; memo follows the template |
| 5 | Narration layer + refusal-heavy evaluation set; README case-study section | `feat/referee-narration` | evaluation report committed; README routes to it |

Out of v1, to be named in Limitations: sequential testing, bandits, switchback designs, interference *modelling* (detection only), Bayesian readouts.

Effort estimate: 30–40 focused hours across milestones 1–4; uncertainty is concentrated in milestone 4's hand-checked statistical fixtures.

## 14. Repository conventions Claude Code must follow

- Python 3.12 (`requires-python = ">=3.12,<3.13"`); use the project venv: `source .venv/bin/activate`; install with `python -m pip install -e '.[dev]'`.
- Lint: `ruff check src scripts tests` (rules E, F, I, B, UP; line length 100). Imports sorted (rule I).
- Tests: `python -m pytest -q`; `testpaths = ["tests"]`, `pythonpath = ["."]`; test directories have no `__init__.py`; test module names are unique across directories.
- Before opening a PR: `bash scripts/validation/run_shared_checks.sh` must pass; scenario gates are matrixed in CI.
- Dependencies: core = duckdb, numpy, pandas, pyarrow. `pyyaml`, `scipy`, `statsmodels` are dev extras. **Decision for milestone 2:** move `pyyaml` and `scipy` to core dependencies in the same PR that introduces YAML loading and power calculations (`statistics.NormalDist` covers z-quantiles, but χ² with k−1 degrees of freedom needs scipy). Milestone 1 needs neither.
- Never commit `data/raw/`, `*.duckdb`, `target/`, or generated notebooks (`.gitignore` already covers them).
- No production, customer, or employer data; all evidence is synthetic; no claims of autonomous decision-making.
- Commit messages follow the existing `type(scope): summary` style. One concern per PR.
- Explain design choices and show each file before writing it; wait for approval; run ruff and pytest after each file.

## 15. Kickoff prompt for Claude Code

```
Read docs/superpowers/specs/2026-09-28-referee-experiment-review-design.md in full before doing anything.

1. Do section 0 first, exactly as written, on its own branch, and open that PR.
2. Then start milestone 1 on branch feat/referee-spec: implement section 6 (spec schema + validation) and section 7 (tests) only. No power, rules, YAML, or CLI yet.
3. Work step by step in teaching mode: before writing each file, show it to me and explain the design choices; wait for my OK; run ruff and pytest after each file.
4. Follow section 14. Finish with a PR titled "feat(referee): experiment spec schema and validation".
```


---

## 16. Amendment 1: repository layout and settled validation rules (2026-09-29)

Added after the design was approved and while milestone 1 was being implemented. Sections 0 to 15 above are left as written; where they disagree with this section, this section wins.

### 16.1 Repository layout

Pull request #22 moved the analytics lab into `analytics-lab/`, and Referee became a second, independent project in `referee/`, with its own `pyproject.toml`, virtual environment and CI job.

| The design says | Now |
| --- | --- |
| Package `src/analytics_lab/referee/`, installed by the existing `pip install -e .` (section 3) | Package `referee/src/referee/`, import name `referee`, installed from `referee/` with `python -m pip install -e '.[dev]'` |
| Tests in `tests/referee/` (section 3) | `referee/tests/`, flat (no `referee` subfolder) |
| Docs in `docs/referee/` (section 3) | `referee/docs/`; this document is in `referee/docs/design/` |
| CLI `python -m analytics_lab.referee review-design <spec.yaml>` (section 3) | `python -m referee review-design <spec.yaml>`, run from `referee/` |
| `ruff check src scripts tests`, and `bash scripts/validation/run_shared_checks.sh` before a PR (section 14) | From `referee/`: `ruff check src tests` and `python -m pytest -q`. The CI job `referee-quality-gate` runs both. The lab's scripts apply to changes inside `analytics-lab/`. |
| Test module names unique across directories (section 14) | Applies within each project. Referee prefixes its own module names so a run from the repository root cannot clash with the lab's |
| `pyyaml` and `scipy` become core dependencies in milestone 2 (section 14) | Unchanged, applied in `referee/pyproject.toml`. `pyyaml` is already a development dependency, because a CI guard test reads the workflow file |
| The synthetic experiment extends the hybrid generator and dbt models (section 10) | They live in `analytics-lab/`. Referee reads their Parquet output through `review-results`, so the two projects share no Python code |

### 16.2 Superseded and deferred items

- Section 0 is superseded. Pull request #21 fixed the provenance guard on `main` before implementation began, and the literal values in section 0 (`e06418d1…`) are stale. Nothing was done for it.
- The milestone 1 deliverable `docs/referee/spec-template.yaml` (section 13) moves to milestone 2, when YAML loading exists and a test can keep the template honest.
- The YAML example in section 6 cannot be loaded as written. PyYAML reads an unquoted `null:` key as Python `None` (`yaml.safe_load('null: x')` returns `{None: 'x'}`), so YAML files, and the milestone 2 template, must quote it: `"null": ...`.

### 16.3 Validation rules settled during milestone 1

Section 6.1 stays authoritative. These rules fill the gaps it left, and `referee/tests/test_spec.py` pins each of them.

- Every string field in the spec (`owner`, `population.eligibility`, every `name`, and the rest) is a non-empty string.
- `population.analysis_unit` takes the same five values as `randomization_unit`, and defaults to it when omitted.
- Guardrails do not accept `governed_reference`; only the primary metric does.
- `guardrails` may be omitted or null (both mean none), `is_control` defaults to false, `baseline_std` may be omitted for a binary metric, and `governed_reference` is optional.
- Integer fields take real integers only: `true` and `4200.0` are rejected, and so is `referee_spec_version: true`.
- Non-finite numbers (`NaN`, infinity) are rejected. `id` must match `^[a-z0-9_]+$` in full, so a trailing newline is not accepted.
- Unknown keys are errors at every level, and a near miss names its likely target (`design: unknown key 'alphaa' (did you mean 'alpha'?)`).
- `ExperimentSpec.from_dict` raises one `SpecError` (a `ValueError`) that lists every violation in schema order. Its result is frozen, hashable and independent of the input.


---

## 17. Amendment 2: milestone 2 decisions (2026-09-30)

Decided before milestone 2 was built. Sections 0 to 16 are left as written; where they disagree with this section, this section wins. "Delivered in" names the pull request that implements a decision: 2a (power), 2b (finding model and rules), 2c (YAML loader, CLI, rule documentation).

### 17.1 Power references (corrects sections 9 and 12)

The formulas in section 9 stand. The references named for them do not agree with them, so the tests use other statsmodels functions. Agreement was measured over grids of baselines, effect sizes, alpha, power, sidedness and unequal allocations.

| Quantity | Reference named in sections 9 and 12 | Measured agreement | Reference used instead |
| --- | --- | --- | --- |
| Two proportions | `NormalIndPower` with `proportion_effectsize` (an arcsine approximation) | 53 of 180 cases within 1 unit; worst gap 1,433 | `samplesize_proportions_2indep_onetail` with `alpha / 2` for a two-sided test: exact in every case |
| Two means | `TTestIndPower` (t-based) | 66 of 96 cases within 1 unit; worst gap 39 | `NormalIndPower` with `alternative="larger"` and `alpha / 2`: exact in every case |

Two conventions the tests must pin: in `samplesize_proportions_2indep_onetail` the returned size belongs to the first group, which is `prop2 + diff` (the treatment), and `ratio` is the second group's size over the first's; and a two-sided `NormalIndPower` call also counts the opposite tail, which the section 9 formula ignores. Delivered in: 2a.

### 17.2 Spec extension

Milestone 2's rules need facts the version-1 schema does not carry. Seven optional fields are added. A spec that is valid today stays valid, and an absent field is what makes the matching rule fire.

| Field | Values | Rule and when it fires |
| --- | --- | --- |
| `design.alpha_adjustment` | `none`, `bonferroni`, `dunnett` | DES-005: more than two arms and the field absent or `none` |
| `design.pre_period_covariate` | metric name | DES-008: absent |
| `population.exposure_timing` | `pre_treatment`, `post_treatment` | DES-007 (blocker): `post_treatment` |
| `population.interference` | `none_expected`, `possible` | DES-006: the randomization unit is `player` or `user` and the value is not `none_expected` |
| `procedure.stopping_rule` | `fixed_horizon`, `sequential` | PRO-001 (blocker): absent |
| `procedure.srm_check_cadence` | `daily`, `weekly`, `none` | PRO-002: absent or `none` |
| `procedure.bucketing_salt` | non-empty string | PRO-004: absent |

`dunnett` is accepted but planned conservatively as Bonferroni until a Dunnett implementation exists. Delivered in: 2b.

### 17.3 Rule semantics

- HYP-001 stays a reserved ID. Spec validation already enforces its listed conditions (a null hypothesis, a direction, a named metric), so they cannot reach a review. It fires as a blocker in one case validation cannot see: the null and alternative statements are identical after case and whitespace normalisation.
- A target effect that cannot exist (for example a rate above 1 after the relative lift) makes DES-001 report that the effect is unattainable, and the review reports it as a blocker.
- DES-004 states the cost of an unequal allocation as the extra units it needs over an equal split for the same power, for example +18.2% for a 70/30 split at a 10% relative effect on a 3.2% baseline.

Delivered in: 2b.

### 17.4 Review outcome, command line and loading

- A design review returns its findings sorted by severity and then rule ID, a list of blocking rule IDs, and a recommendation: `revise` if there is any blocker, otherwise `proceed`. It remains advisory.
- `python -m referee review-design <spec.yaml>` takes `--format text|json`. It exits 0 when there is no blocker, 1 when there is one, and 2 when the input cannot be read or does not validate.
- The report carries the spec's sha256 and the Referee version. The git SHA and package versions arrive with the results report in milestone 4.
- The YAML loader rejects duplicate keys, which PyYAML would otherwise resolve silently, and answers an unquoted `null:` key with a message that says to quote it.
- The rule documentation is generated from the rule code, and a test fails if it drifts.
- The design's section 6 example is underpowered: it needs 389,060 units and its 14 days deliver 58,800, so DES-001 fires. Milestone 2 ships it as an example beside a properly powered one.

Delivered in: 2c.

### 17.5 Dependencies

`pyyaml` becomes a core dependency with the loader (2c). `scipy` stays out of the core until milestone 4, where SRM needs the chi-squared distribution; power needs only `statistics.NormalDist`. This corrects section 14, which assumed both were needed in milestone 2. `statsmodels` is a development dependency, used only by the power tests (2a).

### 17.6 Delivery

Milestone 2 is delivered as three sequential pull requests instead of one branch: 2a `feat/referee-power`, 2b `feat/referee-design-rules`, 2c `feat/referee-cli`. Each needs the one before it.

---

## 18. Amendment 3: milestone 2c decisions (2026-10-02)

Milestone 2c delivers the loader, the report and the `review-design` command. These are the decisions it made that sections 0 to 17 do not record.

### 18.1 The spec's fingerprint

- `ExperimentSpec.sha256()` is the SHA-256 of `canonical_json()` encoded as UTF-8. The canonical JSON has sorted keys, no spaces, non-ASCII written as it is, and refuses NaN. It is built from `to_dict()`, which is schema-ordered and omits whatever was not given.
- The fingerprint covers the parsed spec, not the file's bytes. Comments, key order, flow or block style and number spelling (`4` against `4.0`) do not change it. Any change to a value does, and so does the order of `arms`.
- An absent optional field and an explicit `null` have the same fingerprint, and an empty `procedure` section is dropped, so adding an optional field in a later schema version does not change the fingerprint of an existing spec.
- Text is hashed as written, without Unicode normalisation. `shasum` on the YAML file will not reproduce the fingerprint; a `source_sha256` of the file's bytes was considered for the report and left out.
- The design's section 6 example has the fingerprint `b0332774feccd582db109bfffff10e1330ce418ab28471ccb625fe0b00af10e8`. A test pins it, so the canonical form cannot change unnoticed.

### 18.2 Loading YAML

The loader reads with `SafeLoader` and refuses, with a message naming the file, line and column, what PyYAML would resolve silently: a repeated key (it keeps the last), an unquoted `null:` key and other keys YAML reads as booleans or numbers, aliases and merge keys, and more than one document. A missing, unreadable or non-UTF-8 file is a `LoadError` naming the path. A mapping that is not a valid spec raises the spec's own `SpecError`.

One consequence of PyYAML implementing YAML 1.1: a number such as `5e-2` or `1e-2` is read as text, because a float needs a dot. It is reported by spec validation as a non-number; `0.05` or `5.0e-2` works.

### 18.3 Report and command line

- `python -m referee review-design <spec.yaml> [--format text|json]`. Exit status: 0 no blocker found, 1 at least one blocker, 2 the spec cannot be read or is not valid (and usage errors), 3 a failure inside Referee. Status 3 is added to section 17.4's three, because an uncaught Python exception exits with 1, which a pipeline would read as a blocker.
- Results go to stdout. Errors go to stderr as plain text with nothing on stdout, also under `--format json`.
- The report is one dict with a fixed key order and a `report_version` of 1: Referee version, the spec's id, title and fingerprint, the recommendation, the blocking rule IDs, counts by severity, and the findings. The JSON and the text are both made from that dict. It holds no timestamp, host or path, so the same spec reviewed by the same Referee gives the same bytes.
- The report does not carry the power plan itself; DES-001's evidence states the numbers that matter.

### 18.4 Rule documentation

- Every rule has a `fires_when` sentence beside its title, why-it-matters and remediation. `docs/rules.md` is generated from the rule code by `python -m referee.rules.docs`, and a test fails if the committed file differs. This replaces the file's planned location `docs/referee/rules.md` in section 3, in line with section 16.1.
- The page documents the rule definitions. No test can prove that a `fires_when` sentence describes its check function; the trigger and non-trigger tests of each rule are what pin the behaviour.
- A rule whose ID prefix has no group in the generator is refused, so the results rules (`RES`) cannot be added without deciding how they are documented.

### 18.5 Examples and the spec template

- Section 16.2 moved `docs/referee/spec-template.yaml` to milestone 2. It is replaced by two examples in `referee/examples/`: `offer-page-underpowered.yaml` (the section 6 example, which gets `revise` with blockers DES-001 and PRO-001) and `offer-page-powered.yaml` (the same experiment planned for 98 days with every optional field declared, which gets `proceed`). The second serves as the template: it is commented and every optional field is present.
- Each example's text and JSON output is stored in `referee/tests/golden/` and compared by a test, with checks of what the files must mean so that one regenerated from a broken build still fails. The two examples are checked to differ in exactly nine fields.

Delivered in: 2c.


## 19. Amendment 4: milestone 3 decisions (2026-10-04)

Milestone 3 builds the synthetic experiment that the results reviewer will be judged on. These are the decisions it made that sections 0 to 18 do not record. Section 10 is left as written; where it disagrees with this section, this section wins.

### 19.1 Delivery

- Section 13 names one branch for milestone 3. It was delivered in three changes: 3a, the generator, the raw tables, their source declarations and the staging models; 3b-1, the intermediate models, the two marts and the document that says what each planted problem looks like in them; 3b-2, the incident entries and this amendment.
- Everything lives in the analytics lab, in the hybrid subscription scenario. Nothing in the Referee package changed in milestone 3 except this document and the test that checks it.

### 19.2 Three raw tables, not two

- Section 10 names two tables. A third, `experiment_outcomes` (one row per logged player: sessions, purchases and revenue in the seven days after assignment, and the first purchase time), was added. Novelty and heavy-tailed revenue need outcomes that depend on the arm, and rewriting the scenario's existing `store_transactions` would have changed all eight existing tables, whose contents are pinned by fingerprints.
- The experiment draws from its own random stream, so the eight existing tables have the same content as before the experiment existed. A test pins each table's content with a fingerprint.
- Players who never subscribe are assigned to `control`, `variant_b` or `variant_c` by hashing the player ID with a salt, over a 21-day window that opens ten days after the subscription launch. The tables carry UTC timestamps only; no timestamp defect is planted in them.
- A player lost to the bucketing bug has no row in any experiment table. The absence is the evidence.
- A hybrid scenario shorter than 90 days is refused with a `ValueError`, because the experiment does not fit in it.

### 19.3 Five models, not four

- Section 10 names four dbt models. A fifth, `int_hybrid_subscription__experiment_srm`, was added: the incident audit sits in the intermediate layer and cannot read a mart without breaking the layering, and computing the statistic twice would let the copies drift.
- `int_…__experiment_eligible_population` keeps every assigned player and flags exclusions with a reason (`never_exposed`, `exposed_after_first_purchase`) instead of dropping them. Section 10's "pre-period covariates attached" is delivered as segment attributes and a 28-day session count measured over 672 elapsed hours before assignment.
- That session count is uncorrelated with the outcomes (an absolute correlation below 0.03), because outcomes are generated independently of the scenario's `sessions` table. It cannot demonstrate variance reduction on this data, so milestone 4 must not rely on it for CUPED here. Making it informative would change the raw contract and is a separate change.
- The marts are descriptive only. They publish counts, means, rates and point differences, with no p-values, intervals or verdicts for effects. The one test they run is the sample-ratio check, described next.

### 19.4 The sample-ratio check in SQL

- The check compares assigned players with an equal split across the three arms. With three arms the chi-square has 2 degrees of freedom, so the p-value is exactly `exp(-chi_square / 2)`. It is flagged at p < 0.001.
- The equal split is an assumption, because the warehouse holds no pre-registered allocation. The results reviewer recomputes the check against the allocation registered in the spec (sections 6 and 9); the SQL check does not bind it.
- When the check is flagged, every difference against control is NULL for every arm of that experiment, because an arm comparison is not valid then.
- At the 1,000-player scale that continuous integration builds, the mismatch is present but not detectable (p about 0.03), and the planted novelty reversal is not visible. A results-review fixture therefore needs the 5,000-player scale, which the generator takes as `--scale 5000`. Milestone 4 chooses how Referee reads the data and at what scale; milestone 3 defines no file or table interface.

### 19.5 Incidents

- Three incidents join the shared incident mart, as section 10 asks for the configuration change: `experiment_exposure_after_purchase` (high), `experiment_sample_ratio_mismatch` (high) and `experiment_mid_test_config_change` (medium). The `experiment_` prefix keeps them apart from `post_subscription_exposure`, which concerns marketing-campaign exposure.
- The mart's status logic is the shared generic one: any affected rows means `contained`. For the configuration change, `contained` means disclosed, not corrected: the readout flags it and the outcomes stay pooled across versions. The incident counts players by the version they were assigned under, as the readout does; it does not look at the version in force when a player was first exposed.
- The sample-ratio incident counts the experiment's assigned players when the flag is set and zero otherwise, so it is `clear` at the 1,000-player scale and `contained` at 5,000. A reader must not take `clear` there to mean absent.
- The committed diagnostic results and decision memo are a dated snapshot of an earlier build and list six incidents, while the live mart lists nine. They were not regenerated. Whoever next executes the notebook must also update the provenance that committed tests pin (source version, execution time, validation record) and the memo's incident table, which a test requires to match the JSON.

### 19.6 What the planted problems measure

- The sizes of the five planted problems are in the generator's `PlantedParameters`, and `ground_truth()` returns the plan as data. The measured figures, for seed 42 at 5,000 players and for both populations (all assigned players and eligible players), are in `analytics-lab/docs/metrics/hybrid_subscription_experiment.md`. A test recomputes them from the generator and requires their exact text to appear there, so they are not repeated here.
- Some of what section 10 plants is weak at that scale. The week-3 novelty reversal is within one standard error of zero (the lift fades to about zero; a negative value is not established), and the bias from the bucketing bug is small next to the mismatch itself, which is what invalidates the arm. Milestone 4's rules should be judged against what is detectable, not against what was planted.
- Section 10's mapping of problems to rules is unchanged. No results rule yet covers exposure after purchase or the configuration change; milestone 4 decides whether one should.

Delivered in: 3a, 3b-1, 3b-2.

---

## 20. Amendment 5: milestone 4 decisions (2026-10-05)

Milestone 4 builds the results review. These are the decisions made before it starts that sections 0 to 19 do not record. Section 13 names one branch for it; where this section disagrees with sections 8 to 13, this section wins.

### 20.1 Delivery

- Milestone 4 is delivered in three changes, each needing the one before it: 4a `feat/referee-results-data`, which reads the data and implements the statistics; 4b `feat/referee-results-rules`, the results rules; 4c `feat/referee-results-cli`, the report, the `review-results` command and the decision memo.
- This amendment is delivered in 4a. The thresholds the rules need are chosen in 4b and written down there.

### 20.2 What Referee reads

- `review-results` reads a directory of three CSV files in full: `experiment_assignments.csv`, `experiment_exposures.csv` and `experiment_outcomes.csv`. They carry the columns of the lab's raw tables of the same names, which `analytics-lab/docs/architecture/hybrid_subscription_raw_contract.md` describes as Parquet tables. The CSV form is defined by the loader, `referee/src/referee/data.py`: UTF-8, a header row, the columns it requires, and ISO 8601 timestamps with a zero UTC offset. The analytics lab, not Referee, writes them from its Parquet tables. Referee reads no Parquet and has no dependency on the lab.
- The input is never truncated or sampled. A statistic computed from some of the rows is not the statistic of the experiment, and the first rows are the earliest assignments, which is where a novelty effect sits.
- The data's `experiment_id` column selects the experiment. The lab's id (`hybrid_offer_page`) differs from the spec's example id, so the command takes the data's id explicitly and, when it is absent, lists the ids the files contain.
- The files carry one row per player in the assignments and the outcomes tables, so the outcomes are joined to the arm through the assignments. The outcomes hold seven-day totals only, with no daily series.
- Referee's own tests read a committed real export of the lab's 5,000-player experiment, `referee/tests/data/hybrid_offer_page_5000/`, written by DuckDB from the lab's generator (seed 42; its `PROVENANCE.md` gives the commands and a manifest pins the files byte for byte), so the loader and the statistics are tested on the lab's own output in CI. It is a snapshot: regenerating it is a deliberate act.
- Referee assumes no scale. The planted problems are detectable at 5,000 players and mostly not at 1,000 (section 19.4), so a fixture that is meant to find them uses 5,000. How long reading takes at larger sizes is measured in 4a and reported there.

### 20.3 What is capped

- Only what a person reads is capped. A text report lists at most 1,000 rows per listing and says so (for example, "showing 1,000 of 120,000; the full list is in the JSON report"). The JSON report holds every row.
- The cap changes no computation, count, finding or recommendation. A test runs a review with the cap at 1,000 and without it and requires the same numbers and the same verdict.

### 20.4 Three results rules

- RES-007, which section 8 already lists, is the effect over time. It is defined as a test of whether an arm's difference against control differs between cohorts of players grouped by the week of their first exposure (Cochran's Q across the cohorts, with the slope per week reported next to it), not as a check that the last week is negative. The week-3 lift in the planted data is within one standard error of zero, so a sign check would miss a fade that the cohort test detects. At 1,000 players the standard errors are about 2.2 times larger and the test is not expected to detect it.
- RES-012 is new: players first exposed after their first purchase, in the seven-day window the outcomes cover. It is a warning that reports the count, the share of assigned players and of purchasers, and how the estimate changes without them. It is the results-time counterpart of DES-007 (section 8): a purchase made before the player first saw the change cannot be an effect of it.
- RES-013 is new: an arm's configuration version changes during the test. It is a warning that reports the versions by cohort week and, where one week holds both versions, the difference between them. The exposures table carries the version too, so the rule may use the version in force at first exposure.
- Section 8's rule list does not change otherwise. The IDs RES-012 and RES-013 are the next two unused.
- In the planted data the configuration change confounds RES-007 for `variant_b`: the change is at day 12 of the 21-day window, so with weeks counted from the first assignment the first week holds only version 1, the second both, and the third only version 2 (measured at 5,000 players, seed 42; a Referee test pins the counts on the committed export, by week of assignment and by week of first exposure). A fade in that arm cannot be attributed to novelty alone. When RES-013 fires for an arm, a RES-007 finding for the same arm says so.

### 20.5 What stays out, and what stays open

- A daily outcomes table is not added. It would allow a curve by days since exposure within a player, but it changes the generator's tables and the lab's raw contract, and the cohort test answers the question the rule asks.
- Open for 4b: the thresholds. RES-007's significance level, and whether and where RES-012 escalates from a warning to a blocker (no published threshold for the share of late-exposed players is known to the author, so any value is a judgement and is written as one). Open for 4c: the writer of the three CSV files in the lab.
- `scipy` and `numpy` become core dependencies in 4a. `scipy` supplies the distributions (chi-squared for the sample-ratio check and the cohort test, t and normal for the intervals and tests), as section 17.5 anticipated for the sample-ratio check; `numpy` draws the bootstrap resamples. `statsmodels` stays a development dependency, used to validate the statistics.
- Dunnett's test, which section 9 names, is not implemented (section 9 allows that). The corrections are Bonferroni, Benjamini-Hochberg and, when the dependence between the tests is unknown, Benjamini-Yekutieli, applied to p-values.

Delivered in: 4a (this amendment), 4b, 4c.

## 21. Amendment 6: milestone 4b decisions (2026-10-08)

Milestone 4b builds the results rules. Before writing them, the cohort rule RES-007 was examined for existing players and for a new-user product in development or soft launch: by simulation, by reading the code, and by independent attempts to break the conclusions. This section records what that settled. Where it disagrees with sections 8 to 13 or section 20, this section wins.

### 21.1 Evidence, and its limits

- The simulations were written for the purpose, and each was checked against `referee/src/referee/methods.py`: the vectorised statistics matched `welch_difference` and `cohort_heterogeneity` to within a relative 2e-12 on several hundred explicit cases. Their scripts are not in the repository. A figure marked (re-run) was reproduced by the author with Referee's own functions; a figure marked (reported) comes from a study and was not re-run. 4b-2 commits the small simulations its thresholds rest on, and where a committed test and this section disagree the test wins and this section is corrected.
- (re-run) One small cohort kept next to two of 300 players per arm, normal data, 20,000 runs per row, seed 20261201 (Monte Carlo error 0.15 points at the 5% level, 0.07 at 1%): Cochran's Q flags 7.22% and 2.14% (nominal 5% and 1%) at 6 players per arm, 6.39% and 1.60% at 10, 5.55% and 1.32% at 20, 5.54% and 1.19% at 30, 5.11% and 1.08% at 50. A cohort of 6 players is not safe.
- (re-run) Thirty players per arm in every cohort, 6,000 runs per row, seed 20261202 (error 0.28 and 0.13 points): Q flags 5.92% and 1.33% with 3 cohorts, 6.73% and 1.58% with 8, 6.75% and 2.00% with 12, 7.27% and 1.60% with 26. With each cohort's standard error multiplied by √(ν/(ν−2)), ν being the Welch degrees of freedom, the rates are 5.47% and 1.23%, 5.47% and 1.13%, 5.55% and 1.57%, 5.52% and 1.12%. The 12-cohort cell at 1% reads high in the same sample in which its uncorrected rate does; the studies' 100,000-run rows read 1.0% to 1.2% (reported). The cause is that the weights of Q are estimated from small samples. The correction is the studies' proposal, validated by simulation only; the author knows of no published source for it.
- (re-run) The slope test's 80%-power shift is not Q's. For a linear fade of the size the slope test detects with 80% power, Q detects it with probability 70.9%, 64.5%, 55.5%, 49.3% and 40.9% for 3, 4, 6, 8 and 12 cohorts (noncentral chi-squared).
- (re-run) On the committed export, with cohorts by week of first exposure and a floor of 30 players per arm, `variant_b` keeps weeks 0 to 2 (week 3 holds 3 players against 13) and its Q, with the correction, is 19.86 (p = 4.9e-5; 19.92 without it); `variant_c` keeps weeks 0 to 2 and has Q = 3.77 (p = 0.15). A test pins these.
- (read) The lab's players cannot stand for new users: its generator acquires them 30 to 120 days before the scenario's start date (`analytics-lab/src/analytics_lab/generation/hybrid_subscription.py`), and the committed export's first assignment is 100 days after that date (2026-04-11, against a start date of 2026-01-01), so they are about 130 to 220 days old at assignment. Nothing validated on the committed export covers a product whose players are all new.
- Section 20.4 said the cohort test is not expected to detect the planted fade at 1,000 players. The studies put the chance that Q flags it there at about 46% (simulation) and 42% (bootstrap), and at 32% by normal theory with the realised standard errors (all reported). "Not flagged" at that size is therefore a likely outcome for a real fade, and a finding must not turn it into "stable".

### 21.2 Delivery

- Section 20.1's single 4b branch is replaced by two changes. 4b-1 `feat/referee-results-data-fit`: the data-fit rules of 21.4, the results context and verdict words of 21.3, and the spec and loader additions of 21.8. 4b-2 `feat/referee-results-effect`: RES-007, RES-008 and RES-004, the new design rule DES-009 (21.8) and the analysis they share. 4c is as in 20.1, plus the lab's CSV writer and the optional columns of 21.8.
- This amendment is delivered in 4b-1, as its first step.

### 21.3 What the results rules analyse

- Metrics. `review-results` analyses the spec's primary metric and guardrails by name from a closed registry of what the export holds: `sessions_7d`, `purchases_7d`, `revenue_usd_7d` and `purchased_7d` (binary: `purchases_7d` above 0). A metric outside the registry is refused with exit status 2 and the registry is listed. The spec's baselines stay the registered values; Referee does not replace them with the data's. Retention is not in the registry: the export holds seven-day totals only (20.2), so a retention metric needs a column that no milestone plans.
- Populations. The sample-ratio rules (RES-001, RES-011) use every assigned player, so that dropping players from the analysis cannot hide a mismatch. The effect rules (RES-004, RES-007, RES-008) use the players the lab's own analysis uses: assigned, exposed, and not first exposed after their first purchase. RES-012 reports the estimate with and without the late-exposed players.
- Verdict. A results review ends `invalid` when any blocker fires, `caution` when only warnings do, and `clear` otherwise. The words differ from the design review's `revise` and `proceed` on purpose: `clear` does not say the effect is real.
- Refusals. A results review is refused, with every problem listed, and no rule runs, when the export has an arm the spec does not list; when a metric of the spec is not in the registry or has another kind there; when no player was assigned at or after `design.start_utc`; or when an assigned player has no outcome row.
- `design.planned_duration_days` is the assignment (accrual) window. The seven-day outcome window comes after it and is not part of it. The text of the design did not say; `plan_power` already multiplies daily eligible units by the planned days.

### 21.4 Data-fit rules (4b-1)

- RES-001 (blocker): the sample-ratio check of section 9 on every assigned player, χ² p below 0.001 against the registered allocation. The evidence carries the same check for each 7-day week of assignment.
- RES-002 (blocker): in the effect analysis, an arm has fewer players than that arm's required n from `plan_power(spec)`, found by arm name. A design that cannot be sized at all is reported as the design review does (DES-001), with the reason.
- RES-003 (blocker): the observed duration, first to last assignment in whole days rounded up, is shorter than `min_duration_days`. Rows before `design.start_utc` (21.8) are left out and listed, in the finding and in the report.
- RES-011 (warning): the total passes but a week of assignment fails, each week tested at 0.001 divided by the number of weeks that hold assigned players. On the committed export the three weeks give p = 0.34, 4.0e-5 and 2.6e-8 (re-run); the total fails there (p = 6.7e-10), so RES-001 fires and RES-011 does not.
- RES-012 (warning): players first exposed after their first purchase; the count, their share of assigned players and of purchasers, and the estimate with and without them. It becomes a blocker when the share differs between arms (χ² homogeneity, p below 0.001). No published threshold is known to the author, so this is a judgement. On the committed export 198 players (7.0%) are late-exposed, 7.1%, 7.4% and 6.4% by arm (homogeneity p = 0.72), so it stays a warning there (re-run).
- RES-013 (warning): an arm's configuration version changes during the test; the versions by cohort week, the version at first exposure, and, where one week holds both, the difference between them. On the committed export 445 `variant_b` players are on version 2 and 11 have a first-exposure version that differs from the assigned one (re-run).
- RES-005, RES-006, RES-009 and RES-010 are not built. They check how someone else analysed the data; Referee computes the analysis itself, with Bonferroni, Benjamini-Hochberg or Benjamini-Yekutieli corrections and the delta method (20.5), so there is nothing for them to check.

### 21.5 The cohort test, RES-007 (4b-2)

- Cohorts. A cohort is the players of one arm whose first exposure falls in one block of 7 days, counted from `design.start_utc` when the spec registers one and from the first assignment otherwise. For each non-control arm and cohort: the Welch difference against control (absolute scale) and the log ratio of the means (relative scale; a cohort whose mean in either arm is not positive is dropped with the reason `non_positive_mean`). Each standard error is multiplied by the correction of 21.1. Q and the slope per block come from `cohort_heterogeneity`.
- Usable cohorts. A floor of 30 players per arm, never lowered. The registered size adds a preference: the minimum per arm is the larger of 30 and ⌈7·R / (4·D)⌉ (R the arm's required n by name, D the planned duration), used only if it keeps at least 90% of the cohorts that reach the floor and at least 3; otherwise the floor is used and the finding says so. The finding always reports the registered size, the achieved size, the preferred minimum and the one used. The preference is bounded because it changed no result on a plan that is on schedule: with a minimum of ¼ of the planned weekly share, applied whenever at least 3 cohorts reached it, it kept the same cohorts and gave the same results as the floor alone in 6,840 of 6,840 simulated on-plan cells, and the fall-back to the floor happens when the registered size is more than about four times what can be enrolled, a plan that DES-001 already blocks (both reported; the 90% guard is new and was not simulated). A cohort with no variation is dropped with the reason `no_variation`.
- Block length. Weekly blocks when at least 3 cohorts are usable, there is a usable cohort in each half of the weekly blocks inside the assignment window, and the median size of those blocks (empty ones counted as 0) in the smaller of the two arms is at least 60 players. Otherwise 14-day blocks, when the plan is at least 42 days, at least 3 of them are usable and there is a usable one in each half; otherwise not evaluated. The choice uses cohort sizes only, never outcomes; the finding names the block length used and never reports both. A coverage rule of "half the blocks" alone let a test cover only the first half of the window, and without the 60-player rule power fell from 52.4% to 41.2% as traffic rose from 8 to 10 installs a day (both reported).
- Flag. A scale shows heterogeneity when Q or the slope has p below 0.025 divided by the number of non-control arms (Bonferroni, as `plan_power` does). RES-007 flags an arm only when both scales show it. Neither scale is invariant: with a constant relative effect and a baseline that a build or campaign moves, Q on the absolute scale flags 9.2%, 21%, 66% and 99.6% of runs at 100, 300, 1,000 and 3,000 installs a day, and on the log scale a constant absolute effect does the same (27.7% at 100 installs a day). Requiring both kept false alarms at 3.3% to 4.4% in the rows tested, at a cost in power for a fade (75.9% to 49.5% at 40 installs a day) (all reported, binary outcomes). Q-or-slope at these levels and the two scales were not measured together: 4b-2 measures the false-alarm rate of the combination under the null before it fixes the levels, and records the result here.
- Number of tests. The finding prints the number of arm and metric tests run and the number of flags chance alone would give.

### 21.6 When the cohort test does not run

RES-007 is not evaluated, with a reason code and the cohort sizes, when:

- `fewer_than_3_cohorts_reach_minimum`, or `window_holds_fewer_than_3_blocks` (a plan of 14 days or less holds 2 weekly blocks);
- `no_variation` leaves fewer than 3 cohorts;
- `unit_not_independent`: `randomization_unit` or `analysis_unit` is `session` or `cluster`, or the two are in different classes. `player` and `user` are one class; `device` is its own class and passes only when both fields say `device`. With 6 players to a cluster and a within-cluster correlation of 0.05, Q flags 9.1% of runs with 3 cohorts and 12.8% with 8 (design-effect arithmetic, reported);
- `ratio_metric_not_validated`: the metric is a ratio. The cohort test was never simulated for one;
- `allocation_too_unequal`: the floor rises with the ratio r between the arms' realised cohort sizes, to ⌈30·max(1, (r / 1.5)^1.2)⌉ (judgement, fitted to floors of about 50, 100 and 150 to 250 at 2:1, 4:1 and 9:1 that the studies found, reported); beyond 9:1 the test is not evaluated. With a binary rate of 10% at 9:1, 8 cohorts and 30 players in the small arm, the false-alarm rate is 16.5% (reported);
- `outcome_window_incomplete`: an explicit as-of time (21.8) falls before the end of some cohort's outcome window; those cohorts are excluded and listed. With a real effect of 22% of the control mean and 300 players per arm in each of 3 cohorts, a last cohort whose windows were cut 2 to 0 days short gave 10.9% to 34.5% false alarms (reported). Without an as-of time the test runs and the report says completeness was not checked.

Segment cohorts (channel, country, platform), cohorts defined by something that happens after assignment, and retention curves read from the same players are not defined for RES-007 and are refused. Running it repeatedly on accumulating data flags 11% to 13% of null experiments (reported); the report labels an interim run as one and the test belongs at the planned end.

How much traffic it takes (reported; exact Poisson arithmetic, flat arrivals, floor of 30, and the earlier coverage rule of half the blocks, which the rule of 21.5 changes little but which was not re-measured; total installs a day for 95% of runs to have 3 usable weekly cohorts): with 2 arms 13.0, 11.5, 10.5, 10.0 and 9.5 for plans of 21, 28, 42, 56 and 84 days; with 3 arms 19.5, 17.0, 15.5, 15.0 and 14.0; with 14-day blocks and 2 arms 6.5, 6.0 and 5.5 for 42, 56 and 84 days. Spiky arrivals need 1.5 to 3 times as much, so the finding computes the traffic needed from the observed cohort sizes, not from these figures. Being testable is not being informative: the shift a test can see is set by the experiment's own minimum detectable effect, not by traffic, at 80% power, for 4 to 12 cohorts, at about 2.4 to 2.9 times it for a step and 2.7 to 3.2 times (slope test) or 3.2 to 4.7 times (Q) for a linear fade (reported).

### 21.7 What a finding says

- It says that the effect differs between cohorts of first exposure, not why. It never says "novelty", "decay" or "stable" as a conclusion, and never "found no difference" next to a significant trend. It states what the test cannot tell apart: a change tied to the cohort's week (a launch, a promotion, a build, the acquisition mix) from one tied to each player's own time since first exposure, which the seven-day totals do not show. For `existing_users` it adds that players who see a change first can be the most active.
- A result that is not flagged states the smallest change the test could have seen with 80% probability, computed for the trigger actually used and naming its shape (a linear fade or a step), in the metric's units and as a share of the control mean. Section 21.1 shows why the slope test's figure is not Q's.
- A result is labelled low information when that shift exceeds the control mean, when it exceeds 4 times the registered minimum detectable effect, or when a binary metric has fewer than 5 expected events per arm and cohort. A flagged result that is also low information says so and calls the flag a lead to re-check.
- The control arm's mean by cohort is printed with a 95% interval and a homogeneity p value; the sentence that a changing baseline can raise Q is shown only when that p is below 0.05.
- One finding per rule. RES-007 raises one warning finding when any arm and metric is flagged, not evaluated, or flagged with low information; its evidence lists every arm and metric with its status. A RES-007 that is entirely quiet raises none, but the report always prints one line, "RES-007: N tests, k flagged, m not evaluated, j low information", so that a test that did not run cannot read as a pass. When RES-013 fires for an arm, the RES-007 finding for it says the version change falls in the same weeks.

### 21.8 Spec and export additions

- `population.kind`, optional: `new_users`, `existing_users` or `mixed`. The spec declares it; Referee cannot check it, because the export has no column for how long a player existed, and says so in the finding. A declaration never lowers a warning: DES-008 is not suppressed by `new_users`. DES-003's text changes for `new_users` to say that the accrual window and the seven-day outcome window must fit, and that 4 weekly cohorts need 28 days of accrual. Absent means unknown.
- `design.start_utc`, optional, ISO 8601 with a zero UTC offset. Blocks count from it and assignments before it are ignored and listed. Without it, a stray early row moves every block edge: moving the origin by one day changed the verdict in 5.2% to 5.7% of null experiments and three days in 6.8% to 7.8% (reported). The report states whether the verdict is unchanged for origins 0 to 6 days earlier and prints no range of p values, because at least one of 7 origins flags in about 17% of null experiments (reported).
- Both fields are optional and are dropped from the fingerprint when absent, so the pinned fingerprint of existing specs does not change (18.1). Both are parsed in 4b-1.
- The loader reads `window_end_utc` from the outcomes file, which the lab already writes and the loader ignores. An as-of time comes from the manifest (`exported_at_utc`) or from `review-results --as-of`; it is never derived from the files' own timestamps.
- 4c, in the lab's CSV writer: an optional `first_seen_at_utc` in the assignments file, so that `population.kind` can be checked.
- DES-009 (info), new in 4b-2: 7 × `daily_eligible_units` × the smallest allocation is below 45 players per arm and week, or the planned window holds fewer than 3 weekly blocks, so RES-007 will probably not be evaluated.

### 21.9 Judgement constants, and what stays open

- Judgement, with no published source known to the author: the floor of 30; the preferred minimum's share (¼) and its 90% guard; 60 players to choose weekly blocks; 42 days for the fallback; the log-ratio scale as the second scale; 0.025 per statistic; the low-information thresholds (the control mean, 4 times the minimum detectable effect, 5 events); the allocation floor's exponent; 45 players for DES-009; and 0.001 for RES-012's escalation.
- Open for 4b-2: the false-alarm rate and power of the combined trigger (21.5), the simulations that pin the constants above, and how RES-008's bootstrap enters the cohort test for heavy-tailed metrics. Not simulated by any study: three or more arms, bots and test accounts (a burst of inactive installs gave 7% to 85% flags with a real effect, reported), per-player heterogeneity of the effect, delayed or arm-dependent first exposure, and mid-week build changes.
- Literature was checked in part: Kohavi's recommendation to look at the effect over time and at new users separately, and Viechtbauer (2007) on Q with estimated variances, were read in saved extracts; Higgins and Thompson (2002) was read as an abstract only. No source known to the author studies cohort heterogeneity among the new users of a game. The 355·s² rule of Kohavi, Deng, Longbotham and Xu (2014) asks for far more than 30 players per cohort for skewed metrics, and the floor of 30 rests on the simulations, not on it.

Delivered in: 4b-1 (this amendment), 4b-2, 4c.
