# Experiment referee design

**Date:** 2026-10-13\
**Branch:** `cld/youthful-feynman-q8uzx8`\
**Status:** Approved design; implementation plan at `docs/superpowers/plans/2026-10-13-experiment-referee.md`

## Purpose

Every decision memo in this repository ends the same way: a decision to test, not to act. Each prescribes the experiment in near-identical terms — randomize before exposure, keep an unchanged control, pre-register the decision rule, stratify assignment, respect guardrails, wait for maturity, and report absolute effects with uncertainty rather than declaring a win from a point estimate. Nothing in the codebase adjudicates any of that. The one randomized field that exists, `eligible_experiment_arm` on `fct_hybrid_subscription__marketing_exposures`, is produced, tested for accepted values, and never read for an effect estimate.

The experiment referee closes that gap. It takes a pre-registered protocol and a governed readout and returns one of four labels — `SHIP`, `STOP`, `INCONCLUSIVE`, or `REFUSE` with a stated reason — together with the evidence that produced the label. The refusal path is the important one. A referee that cannot say "I will not rule on this" is a rubber stamp.

The referee recommends; it does not act. That keeps it inside the repository's standing exclusion of autonomous decision-making. It is also not an experimentation platform: there is no assignment service, no exposure logging, and no rollout. Assignment is whatever the governed marts already record.

## Scope

The first version will:

1. Define a pre-registration protocol format and lock it against post-hoc amendment.
2. Publish an assignment-grain fact and an arm-by-stratum readout mart for the hybrid subscription scenario, which is the only scenario with a randomized field today.
3. Implement the referee as shared Python beside the evaluator, reading governed relations only.
4. Enforce preconditions — protocol integrity, sample-ratio match, assignment before exposure, maturity, incident containment, differential attrition — before any estimate is computed, and refuse when they fail.
5. Estimate an intent-to-treat effect with a stratified bootstrap interval and apply the pre-registered decision rule to the interval, never to the point estimate alone.
6. Publish a verdict artifact and a decision memo that satisfy the existing memo template and enforcement test.
7. Add designed effects to the hybrid generator — a known treatment lift and a known allocation skew — so the referee can be shown to detect what is there, and only what is there, the same way designed defects are detected and contained.
8. Extend the trusted question set so that "did the offer win?" on an immature readout has exactly one correct answer, and it is a refusal.

## Non-goals

The first version will not include sequential or always-valid inference, interim peeking rules, more than two arms, covariate adjustment beyond the pre-specified change-score estimator, Bayesian decision rules, multiple-comparison corrections across secondary outcomes (secondaries are reported, never adjudicated), interference or network effects, automatic rollout, or any claim that a synthetic verdict says anything about a real product. A live-strategy upgrade-cost experiment and a subscription onboarding experiment are natural second and third referee cases, but each needs a randomized field its scenario does not yet generate, and that is separate work.

## Where the referee sits

The referee is shared foundation, not a fourth scenario. Scenarios own their readout models; the referee is scenario-agnostic and owns the protocol format, the preconditions, the estimator, and the verdict.

```text
src/analytics_lab/provenance.py                            shared: input fingerprint, platform, package versions, code version
src/analytics_lab/referee/                                 shared: protocol, readout, preconditions, estimate, verdict, memo, __main__
docs/experiments/<experiment>.yaml                         pre-registered protocol, one per experiment
game_analytics/models/hybrid_subscription/
  intermediate/int_hybrid_subscription__experiment_units.sql
  marts/fct_hybrid_subscription__experiment_units.sql      one row per assigned, eligible, mature unit
  marts/mart_hybrid_subscription__experiment_readout.sql   one row per arm × stratum, numerators and denominators
reports/experiments/<experiment>_verdict.json              the verdict and its evidence
reports/experiments/<experiment>_decision_memo.md          the memo, in the governed template
tests/referee/                                             Python tests for the shared module
```

Invocation mirrors the evaluator:

```bash
./.venv/bin/python -m analytics_lab.referee \
  --protocol docs/experiments/hybrid_subscription_launch_offer.yaml \
  --db game_analytics/dev.duckdb \
  --output reports/experiments/hybrid_subscription_launch_offer_verdict.json
```

Exit status is zero for any adjudicated label, including `REFUSE`; a refusal is a correct outcome, not a crash. Non-zero exit is reserved for malformed protocols, missing relations, and reconciliation failures between the units fact and the readout mart.

## Protocol contract

A protocol is a YAML file in `docs/experiments/`. Every field below is required. Thresholds in the example are illustrative placeholders: the hybrid memo is explicit that no numerical launch threshold is inferred from the synthetic diagnostic, and the referee inherits that stance. Setting them is a registration act, not a referee default.

```yaml
experiment: hybrid_subscription_launch_offer
scenario: hybrid_subscription

assignment:
  unit: player_id
  relation: fct_hybrid_subscription__marketing_exposures
  arm_column: eligible_experiment_arm
  campaign_id: subscription_launch
  arms: {control: 0.5, offer: 0.5}

population:
  relation: fct_hybrid_subscription__player_behavior_28d
  require: [is_population_eligible, is_window_mature]

outcomes:
  primary: total_net_revenue_usd
  estimator: difference_in_differences        # or post_period_difference
  guardrails:
    - {metric: session_count, direction: no_decrease, tolerance: 0.5, stop_on_breach: true}
    - {metric: standalone_store_net_revenue_usd, direction: no_decrease, tolerance: 1.00, stop_on_breach: false}
  secondary: [liveops_participation_count, subscription_net_revenue_usd]

design:
  strata: [prior_payer_status, platform]
  observation_horizon_hours: 672
  minimum_units_per_arm: 300                   # illustrative
  practical_threshold: 1.00                    # illustrative, outcome units
  minimum_detectable_effect: 1.50              # illustrative, outcome units
  bootstrap: {seed: 42, draws: 2000, interval: 0.95}
  sample_ratio_alpha: 0.001

decision_rule:
  ship: ci_lower > 0 and point_estimate >= practical_threshold and no stop_on_breach guardrail is breached
  stop: ci_upper < 0 or any stop_on_breach guardrail is breached
  otherwise: inconclusive

registration:
  registered_at_commit: <full 40-character SHA>
  protocol_sha256: <SHA-256 of this file with the registration block removed>
```

Rules the referee enforces on the protocol itself:

- `arms` has exactly two entries whose allocations sum to one. The arm column's accepted values in the scenario schema must equal the protocol's arm names.
- `primary`, every guardrail metric, and every secondary must be a column of `population.relation`. The referee does not compute new metrics; it adjudicates governed ones.
- `strata` must be columns of `population.relation` and must be the columns the scenario already uses as exact-match covariates where they exist, so that the referee's strata and the diagnostic's strata cannot silently diverge.
- `observation_horizon_hours` must equal the horizon the population relation was built with. For hybrid that is 672 elapsed hours, stated in hours for the same reason the catalogue states it in hours: invariance across daylight-saving transitions.
- The decision rule is parsed, not evaluated as code. Only the three clauses shown are legal, and their operands are drawn from a fixed vocabulary (`ci_lower`, `ci_upper`, `point_estimate`, `practical_threshold`, guardrail breach). A protocol that tries to express anything else is malformed.

### Registration lock

Pre-registration is worthless if the file can be edited after the readout is seen. The lock has two parts:

1. `protocol_sha256` is the SHA-256 of the canonical YAML with the `registration` block removed. The referee recomputes it on every run and returns `REFUSE: protocol amended after registration` on mismatch. Any edit to a threshold, a guardrail, a stratum, or the decision rule changes the hash.
2. `registered_at_commit` must be an ancestor of the current `HEAD`. A docs test asserts this with `git merge-base --is-ancestor`. The live-strategy artifact was once pinned to a commit on a branch that was later deleted, leaving published evidence pointing at an unreachable object; a registration commit that cannot be checked out is not a registration.

Amending a protocol is allowed. It is done by registering a new one with a new hash and a new commit, and the verdict names the protocol it ruled on. The old verdict stays published under the old hash.

## Governed models

### `fct_hybrid_subscription__experiment_units`

One row per player who is assigned, eligible, and mature. A player enters the units fact only when every one of these holds:

- the player has a canonical exposure for the protocol's `campaign_id` with a non-null `eligible_experiment_arm`. Exposures that arrive after subscription start — the designed "late experiment exposure" defect, 5% of subscriber exposures — already have a null eligible arm and are excluded here, with the exclusion counted below;
- `is_population_eligible` is true in `int_hybrid_subscription__analysis_population`, so the index is the eligible exposure and matching covariates are valid;
- both the `pre` and `post` rows of `fct_hybrid_subscription__player_behavior_28d` exist and have `is_window_mature` true.

Columns: `player_id`, `experiment_arm`, `index_at_utc`, the strata (`prior_payer_status`, `platform`, `acquisition_channel`), and for each governed outcome a `pre_` and `post_` value and their difference: `session_count`, `liveops_participation_count`, `standalone_store_net_revenue_usd`, `subscription_net_revenue_usd`, `total_net_revenue_usd`. `player_id` is unique. The arm is never null.

### `mart_hybrid_subscription__experiment_readout`

One row per `experiment_arm × prior_payer_status × platform`, publishing counts and sums so every rate and mean the referee reports can be recomputed from the mart after aggregation:

- `assigned_count`: players with a non-null eligible arm for the campaign, before any further exclusion;
- `ineligible_population_count`, `immature_window_count`: players lost to each exclusion, by arm, so differential attrition is visible in the mart and not only in the verdict;
- `unit_count`: rows in the units fact;
- for each outcome, `pre_sum`, `post_sum`, and `change_sum` over units.

A zero `unit_count` produces null means, never zero, following the catalogue's rule for ratios. The mart reconciles to the units fact exactly, and a singular test fails if it does not.

### Selector and tags

Both models are tagged `hybrid_subscription` by path and build under the existing selector with `--indirect-selection cautious`. No shared model changes.

## Preconditions and refusals

The referee evaluates these in order and stops at the first failure. Each failure is a `REFUSE` with a machine-readable reason and the evidence, so that a refusal can be audited rather than merely trusted.

| Precondition | Check | Why the memos require it |
| --- | --- | --- |
| Protocol locked | Recomputed hash equals `protocol_sha256`; registered commit is an ancestor of `HEAD` | Pre-registration is the memos' central demand; an unlocked protocol is not pre-registered |
| Assignment precedes exposure | Every unit's `index_at_utc` is its eligible exposure, which by construction precedes any subscription start | Late exposures are a designed defect; attributing outcomes to them is the failure the raw contract warns about |
| Sample-ratio match | Chi-square of `assigned_count` by arm against `arms` allocation; refuse when `p < sample_ratio_alpha` | A broken randomizer produces a precise, wrong estimate. The P1-8 finding — unmatched subscribers systematically the most engaged — is the observational cousin of this failure |
| Differential attrition | Chi-square of exclusion counts by arm (ineligible, immature); refuse at the same alpha | Randomization at assignment does not survive asymmetric loss afterwards |
| Maturity | `immature_window_count` is zero for both arms, and the newest `index_at_utc + observation_horizon_hours` is at or before the population relation's `ingestion_mature_through_at_utc` | "Wait for maturity" and "mature reporting boundary" appear in every memo; an interim readout is a peek, and the first version does not support peeking |
| Incidents contained | Every incident class in `mart_hybrid_subscription__data_quality_incidents` reports contained status | The diagnostics exercise containment before authoring a memo; the referee holds itself to the same order |
| Minimum sample | `unit_count` per arm at or above `minimum_units_per_arm` | Not a refusal: a mature but underpowered experiment is adjudicated `INCONCLUSIVE` with the shortfall stated, because the honest answer is "we could not tell", not "we will not say" |

## Estimation

The estimand is the intent-to-treat effect of assignment to `offer` relative to `control` on the primary outcome, among units. Analysis is by assigned arm, never by eventual subscription, exactly as the hybrid memo prescribes.

Two estimators are allowed and the protocol names one before launch:

- `post_period_difference`: mean post-window outcome in `offer` minus mean in `control`. Unbiased under randomization; higher variance.
- `difference_in_differences`: mean of `(post − pre)` in `offer` minus mean in `control`. The change score uses the pre-window as a covariate and typically narrows the interval. It is the quantity the matched diagnostic already publishes, so a reader can compare the randomized and observational numbers for the same outcome.

The interval is a stratified percentile bootstrap: units are resampled with replacement within `arm × stratum`, the estimator is recomputed per draw, and the interval is the central `interval` fraction of draws. The seed and draw count come from the protocol. This reuses the pattern of `bootstrap_difference_ci` in `analytics_lab.analysis.live_strategy_retention`, which resamples within `period × acquisition_channel` strata with a fixed seed. The bootstrap describes sampling variation in the synthetic population under the protocol's design; it does not license any claim beyond the units it was computed on.

Guardrails are evaluated as the same estimator on the guardrail metric, compared against `tolerance` in the protocol's `direction`. A guardrail is breached when the interval's adverse bound crosses the tolerance — the whole interval, not the point estimate, so a guardrail cannot be passed on a lucky draw. Secondary outcomes are reported with intervals and never adjudicated.

## Decision rule

The rule is applied to the interval and the guardrails, in this order:

1. `STOP` if `ci_upper < 0`, or any guardrail with `stop_on_breach: true` is breached. A revenue win with an engagement breach does not ship; the hybrid memo's requirement is "without unacceptable quality or engagement guardrail breaches".
2. `SHIP` if `ci_lower > 0`, the point estimate is at or above `practical_threshold`, and no `stop_on_breach` guardrail is breached. A breached guardrail with `stop_on_breach: false` is reported in the verdict's reasons but does not block.
3. `INCONCLUSIVE` otherwise, with the reason stated: interval spans zero, point estimate below the practical threshold, or sample below the registered minimum.

`minimum_detectable_effect` is not a decision input. It is recorded so a reader can judge whether an inconclusive result was a null or an underpowered design, and a test asserts that the protocol's `minimum_units_per_arm` is consistent with it under a stated variance assumption, so the two cannot be registered in contradiction.

Every verdict publishes its margin: the distance between the interval bound and the threshold that decided it, in outcome units, and `near_boundary: true` when that margin is smaller than one bootstrap standard error. This is the referee's defence against the platform-dependence problem below. A verdict that would flip on a one-player difference says so.

## Verdict artifact

`reports/experiments/<experiment>_verdict.json` carries the same provenance block as the diagnostics, plus the protocol identity:

```json
{
  "metadata": {
    "experiment": "hybrid_subscription_launch_offer",
    "protocol_path": "docs/experiments/hybrid_subscription_launch_offer.yaml",
    "protocol_sha256": "…",
    "registered_at_commit": "…",
    "code_version": "…",
    "executed_at_utc": "…",
    "execution_platform": {"system": "Darwin", "machine": "arm64"},
    "package_versions": {"python": "…", "pandas": "…", "duckdb": "…", "numpy": "…", "pyarrow": "…"},
    "input_relations": [
      "fct_hybrid_subscription__experiment_units",
      "mart_hybrid_subscription__experiment_readout",
      "mart_hybrid_subscription__data_quality_incidents"
    ],
    "input_fingerprint": {"sha256": "…", "row_count": 0, "columns": ["…"]}
  },
  "preconditions": {
    "protocol_locked": true,
    "assignment_precedes_exposure": true,
    "sample_ratio": {"expected": {"control": 0.5, "offer": 0.5}, "observed": {"control": 0, "offer": 0}, "chi_square": 0.0, "p_value": 1.0, "passed": true},
    "differential_attrition": {"by_arm": {"control": {"ineligible": 0, "immature": 0}, "offer": {"ineligible": 0, "immature": 0}}, "p_value": 1.0, "passed": true},
    "maturity": {"horizon_hours": 672, "immature_units": 0, "passed": true},
    "incidents_contained": true,
    "minimum_units": {"required": 300, "control": 0, "offer": 0, "met": true}
  },
  "estimate": {
    "primary": "total_net_revenue_usd",
    "estimator": "difference_in_differences",
    "point": 0.0,
    "interval": [0.0, 0.0],
    "interval_level": 0.95,
    "bootstrap": {"seed": 42, "draws": 2000, "standard_error": 0.0},
    "units": {"control": 0, "offer": 0},
    "by_stratum": []
  },
  "guardrails": [],
  "secondary": {},
  "verdict": {
    "label": "INCONCLUSIVE",
    "reasons": ["interval spans zero"],
    "margin": 0.0,
    "near_boundary": false
  }
}
```

The `input_fingerprint` is the content hash of the units fact, computed by the same `fingerprint_inputs` function the live-strategy diagnostic uses, so a verdict can be told apart from a re-read of a stale build.

## Decision memo

`reports/experiments/<experiment>_decision_memo.md` is generated from the verdict and satisfies the five required headings in `docs/templates/decision-memo.md` — Decision, Observed facts, Assumptions and uncertainty, Data-quality qualification, Reproducibility — so that `tests/docs/test_templates_are_enforced.py` applies to it with no special case. The memo adds a `## Verdict` section naming the label and reasons, and a `## Protocol` section naming the registered hash and commit.

Observed facts are copied from the verdict JSON, not recalculated in prose. The Assumptions section states that the estimand is the effect of assignment under the protocol's design, that the bootstrap covers sampling variation only, and — because a randomized assignment is the one place this repository can use the word — that a `SHIP` label is a claim about the causal effect of assignment to the offer within the synthetic population and nothing wider. The Reproducibility section cites `code_version`, `executed_at_utc`, the platform, and the input fingerprint, and the memo guard test asserts each appears in the text.

## Designed effects

Designed defects are what make the incident registers credible: the failure is planted, named, detected, and contained. The referee needs the same discipline for effects, or its `INCONCLUSIVE` on the current data proves nothing.

As the hybrid generator stands, `experiment_arm` is drawn once per player with `rng.choice(["control", "offer"])` and never read again; sessions and store transactions branch on `is_subscriber`, which the generator chooses independently of the arm. The arm is therefore a true null, and that is the first fixture: on the default generation the referee must return `INCONCLUSIVE`, and the scenario gate asserts it.

Two generator knobs make the other outcomes demonstrable:

- `--treatment-effect <float>` (default `0.0`): a multiplicative lift applied to `offer`-arm players' post-window session count and standalone-store transaction count. The referee must return `SHIP` on a fixture generated with a lift comfortably above the registered threshold, and must not return `SHIP` on a lift below it.
- `--allocation-skew <float>` (default `0.5`): the probability of `offer`. The referee must return `REFUSE: sample ratio mismatch` on a fixture generated at a skew the chi-square can detect at the registered alpha and the configured scale.

Both knobs are constrained so that the default generation stays byte-identical to today's. At the default value the code path consumes no random draws and performs no arithmetic on generated values; the effect branch is entered only when the knob is non-default, and it draws from its own generator seeded from the scenario seed so the main stream is never touched. The generation tests assert this directly: a generation with the knobs at their defaults must be frame-for-frame equal to one that never mentions them, and the hybrid tables' content fingerprints at the gate's scale are recorded at implementation and verified on both macOS/arm64 and Linux/x86_64, as the live-strategy tables already were (`players.parquet` `6767331d224dc305`, `sessions.parquet` `097a4964e0bcf6c6`). A knob that perturbs the default stream is a defect, because it would silently change every published number in the scenario.

Numeric fixtures are produced in-process by the generator with explicit knobs and are never hand-edited, following the rule the subscription question set established: generated, never transcribed. Only test-only protocol files live under `tests/referee/fixtures/`.

## Reproducibility and platform dependence

The live-strategy memo documents that the same commit and byte-identical generated inputs produce `post_update_eligible_players` of 477 on macOS/arm64 and 478 on Linux/x86_64, with every downstream figure moving. The cause is not yet established, and the referee inherits the exposure: a verdict is a threshold decision on exactly the kind of count that moved.

The referee's response is disclosure plus a gate, not a workaround:

- every verdict records `execution_platform` and `input_fingerprint`, and the memo states the platform the label holds on;
- every verdict publishes its margin and `near_boundary` flag;
- a committed verdict is publishable only when its **label** reproduces in CI on Linux. The scenario gate runs the referee against the freshly built mart and compares the label, and only the label, to the committed artifact. Numerical values may differ within the disclosed divergence; a label that differs fails the gate and the verdict is not published until the divergence is understood or the protocol's margin is widened.

This is the first place in the repository where cross-platform agreement is a hard gate rather than a documented caveat, and it is deliberately the referee, because a verdict that depends on the operating system is not a verdict.

## Tests

Implementation follows the repair spec's discipline: each test fails first against the branch, then passes after the focused change that it motivates.

Python, in `tests/referee/`:

- a malformed protocol (missing field, three arms, allocation not summing to one, unknown outcome column, decision rule outside the vocabulary) is rejected before any data is read;
- an amended protocol is refused with the hash mismatch stated;
- a registration commit that is not an ancestor of `HEAD` fails the docs test;
- sample-ratio mismatch is refused at the registered alpha and passes on a balanced fixture, with the chi-square statistic checked against a hand-calculated value;
- differential attrition is refused when exclusions are asymmetric by arm;
- an immature readout is refused and never produces an estimate;
- an uncontained incident is refused;
- the true-null default fixture is `INCONCLUSIVE`;
- an injected lift above threshold is `SHIP`, below threshold is `INCONCLUSIVE`, and a lift with a planted `stop_on_breach` guardrail breach is `STOP`;
- the bootstrap is deterministic for a fixed seed and the interval is order-insensitive;
- the verdict's metadata block is complete, including `input_fingerprint` and `execution_platform`;
- the margin and `near_boundary` flag are correct on a fixture constructed one unit away from the threshold.

dbt, in `game_analytics/tests/hybrid_subscription/`:

- `player_id` is unique in the units fact and `experiment_arm` is non-null with the protocol's accepted values;
- every unit has mature `pre` and `post` behaviour rows;
- late exposures appear in `assigned_count` exclusions, never in units;
- the readout mart reconciles to the units fact on every count and sum;
- zero `unit_count` yields null means.

Generation, in `tests/generation/`:

- default knobs reproduce the existing table fingerprints exactly;
- the treatment lift changes only `offer`-arm post-window rows;
- the allocation skew changes only the arm column's distribution.

Docs and evaluation:

- the experiment memo satisfies the template and cites the verdict's provenance;
- the metric catalogue documents the readout mart and the verdict labels;
- the new trusted questions pass, including the refusal cases.

CI: the hybrid scenario gate builds the two new models, runs the referee on the default data, asserts `INCONCLUSIVE`, and compares the committed verdict's label.

## Documentation and artifacts

- `docs/metrics/hybrid_subscription.md`: add the readout mart to the supporting diagnostics table and a short section defining the four verdict labels and the preconditions, with the same grain/numerator/denominator/boundary structure the catalogue uses for everything else.
- `docs/ai-audit/hybrid_subscription_questions.yaml`: add cases for verdict-label definitions, sample-ratio semantics, a refusal on an immature readout, a refusal on a causal claim about eventual subscribers rather than assignment, and one adversarial case asking the referee to relax a guardrail after the readout.
- `docs/getting_started.md`: one step — register a protocol, build hybrid, run the referee, read the verdict.
- `README.md`: one sentence under the hybrid case study naming the referee and linking the verdict and memo.

Commit the protocol, the verdict JSON, the memo, the fixtures, and the catalogue and question updates. Do not commit generated notebooks or figures; the referee produces none.

## Delivery order

1. Protocol loader and validation, with the registration lock, against a hand-written protocol and no data.
2. Units fact and readout mart, with their dbt tests, built under the hybrid selector.
3. Preconditions, one at a time, each with its refusing fixture.
4. Estimator and bootstrap, verified on the true-null default.
5. Generator knobs, with the byte-identity tests passing before the lift is exercised.
6. Decision rule, margin, and verdict artifact.
7. Memo generation and template enforcement.
8. Catalogue, questions, guide, README.
9. CI gate for label reproduction.

A pull request can be opened when every test above passes on the final head, the committed verdict's label reproduces in CI, the full hybrid selector builds green with the new models, the shared gate passes, and the working tree is clean of untracked artifacts.

## Decisions taken at review

- **Primary outcome: `total_net_revenue_usd`.** The first registered protocol adjudicates the hybrid memo's value guardrail, not session count. The generator's designed lift therefore has to move standalone-store spend, not only sessions, for the `SHIP` fixture to be meaningful; the designed-effects section already requires both.
- **Thresholds and minimum sample: deferred to registration.** No value is set in this design and none will be defaulted by the referee. Test fixtures carry their own test-only protocols with values chosen to exercise each label; the first registered protocol's values are set by the owner at registration and nowhere else.
- **Both estimators stay.** `difference_in_differences` and `post_period_difference` remain available, chosen at registration and fixed by the lock.

## Open questions

- Whether the referee should run on the other two scenarios' memos' prescriptions once each has a randomized field. That is the natural next design, and it is out of scope here.
