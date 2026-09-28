# Three-Scenario AI Product Analytics Lab — Design

**Date:** 2026-08-27  
**Status:** Approved design, pending repository implementation plan

## 1. Objective

Build one portfolio-grade analytics engineering repository that demonstrates senior product analytics, game analytics, subscription monetization, governed metrics, data-quality controls, and supervised AI-assisted investigation.

The repository contains three independently executable scenarios built on a single technical foundation:

1. Live mobile strategy game.
2. Consumer subscription product.
3. Hybrid free-to-play game with a premium subscription.

The project must demonstrate analytical judgment and reproducibility, not merely generated SQL or polished dashboards.

## 2. Success criteria

The finished repository must:

- Install and run locally on Apple Silicon using Python 3.12, DuckDB, dbt, and Git.
- Generate deterministic synthetic data for all three scenarios.
- Preserve raw, staging, intermediate, and mart layers.
- Define governed metrics with eligibility, grain, exclusions, time rules, and known limitations.
- Include intentional tracking and data-quality failures that are detected and contained.
- Produce one flagship diagnostic analysis and decision memo per scenario.
- Preserve an AI audit trail showing proposed work, human validation, rejected outputs, and corrections.
- Evaluate a constrained analytical agent against trusted questions and expected results.
- Keep each scenario independently buildable and testable.
- Present credible recruiter-facing evidence without claiming production-scale autonomy.

## 3. Architecture decision

Use a monorepo with shared infrastructure and isolated scenario domains. Do not create three repositories or three independent Python environments.

```text
ai-product-analytics-lab/
├── .github/
│   └── workflows/
├── data/
│   ├── raw/
│   │   ├── live_strategy/
│   │   ├── subscription/
│   │   └── hybrid_subscription/
│   └── generated/
├── game_analytics/
│   ├── analyses/
│   ├── macros/
│   ├── models/
│   │   ├── shared/
│   │   ├── live_strategy/
│   │   ├── subscription/
│   │   └── hybrid_subscription/
│   ├── seeds/
│   ├── snapshots/
│   └── tests/
├── notebooks/
│   ├── live_strategy/
│   ├── subscription/
│   └── hybrid_subscription/
├── reports/
│   ├── live_strategy/
│   ├── subscription/
│   └── hybrid_subscription/
├── scripts/
│   ├── generation/
│   ├── evaluation/
│   └── validation/
├── docs/
│   ├── architecture/
│   ├── metrics/
│   ├── incidents/
│   ├── ai-audit/
│   └── superpowers/specs/
├── pyproject.toml
└── README.md
```

DuckDB schemas and dbt selectors keep the three domains isolated. Shared macros, calendar logic, currency conventions, evaluation code, and quality patterns live once in the common layer.

## 4. Common data flow

1. Seeded Python generators create deterministic raw CSV or Parquet files.
2. dbt sources register the raw datasets.
3. Staging models rename, type, standardize, and deduplicate fields.
4. Intermediate models reconstruct business entities and state.
5. Marts publish governed facts, dimensions, cohorts, and KPIs.
6. dbt tests and custom validation queries enforce contracts.
7. Python notebooks perform statistical analysis and visualization using mart data.
8. Reports separate observed facts, inference, assumptions, uncertainty, and recommendations.
9. The constrained analytical agent reads approved definitions and marts only.
10. Evaluation scripts score answers against a trusted question set.

## 5. Shared foundation

The common layer supplies:

- Deterministic random seeds and configurable dataset scale.
- UTC timestamp conventions plus explicit local-time test cases.
- ISO currency fields and documented USD conversion assumptions.
- Calendar and reporting-period dimensions.
- Reusable dbt tests for temporal validity, accepted status values, referential integrity, uniqueness, and reconciliation.
- Standard metric-contract template.
- Standard decision-memo template.
- AI review checklist and provenance format.
- Evaluation schema for question, expected metric, expected population, expected result, tolerance, refusal requirement, latency, and cost.

Scenario-specific business logic must not be hidden in shared macros.

## 6. Scenario A — Live strategy game

### Business premise

A fictional 4X strategy game experiences a D7-retention decline after a season update that changes upgrade costs and event rewards.

### Primary entities

Players, sessions, gameplay events, purchases, progression snapshots, alliances, live events, battles, economy transactions, and configuration versions.

### Governed metrics

New installs, DAU, D1 retention, D7 retention, session frequency, median session duration, payer conversion, ARPDAU, event participation, alliance adoption, and progression velocity.

### Flagship diagnostic

Determine whether the D7-retention decline is caused by progression friction, Android instrumentation loss, acquisition-mix change, or a combination. The final report must quantify each contribution and avoid overstating causality.

### Designed failures

- Duplicate Android client events.
- Missing session ends on one app version.
- Incorrect purchase status before refund reconciliation.
- Events before installation and invalid membership intervals.
- Ambiguous date-level configuration joins for intraday changes.

## 7. Scenario B — Subscription product

### Business premise

A freemium consumer application increases trial volume while trial-to-paid conversion and early paid retention deteriorate.

### Primary entities

Users, onboarding events, product events, subscription lifecycle events, payments, marketing spend, and support tickets.

### Governed metrics

Signup-to-trial rate, trial-to-paid conversion, activation, trial activation, D30 paid retention, early paid churn, MRR, NRR, and CAC.

### Flagship diagnostic

Explain a 4–6 percentage-point decline in mature trial-to-paid conversion by separating acquisition mix, onboarding performance, activation behavior, payment failures, plan mix, and cohort maturity.

### Designed failures

- Duplicate subscription webhooks.
- Late-arriving cancellations.
- Missing campaign identifiers.
- Inconsistent activation event names.
- Trial-end timestamps stored in local time but labelled UTC.

## 8. Scenario C — Hybrid game subscription

### Business premise

A free-to-play multiplayer game introduces a monthly subscription with currency grants, an exclusive reward track, and store discounts. Leadership must determine whether it creates incremental value or cannibalizes store purchases.

### Primary entities

Players, sessions, subscription events, store transactions, virtual-currency ledger entries, live-event participation, marketing exposures, and product catalogue.

### Governed metrics

MAU, active subscribers, subscription conversion, subscriber churn, D30 subscriber retention, ARPMAU, subscriber incremental net revenue, discount utilization, engagement lift, and LiveOps participation.

### Flagship diagnostic

Compare 28-day pre/post subscriber behavior with matched non-subscriber controls, segmented by prior payer status. Judge performance using total net revenue rather than subscription revenue alone, and distinguish association from causal inference.

### Designed failures

- Duplicate store transaction webhooks.
- Cancellation meaning auto-renew disabled rather than immediate entitlement loss.
- Mixed transaction and session timezones.
- Missing links between currency grants and subscription transactions.
- Experiment exposures arriving after subscription.

## 9. Parallel work model

Parallelism starts only after the shared foundation is stable.

### Sequential dependency

1. Repository cleanup and structure.
2. Python packaging and deterministic generator conventions.
3. Shared dbt source, naming, testing, and metric-contract conventions.
4. Baseline CI and local validation commands.

### Parallel tracks

After that checkpoint, each scenario receives its own GitHub epic and child issues for:

1. Raw-data contract and generator.
2. Staging models and source tests.
3. Intermediate business-state models.
4. KPI marts and metric catalogue.
5. Intentional incident detection and remediation.
6. Flagship notebook.
7. Decision memo.
8. Trusted analytical questions and agent evaluation.

Parallel implementation must use separate Git branches or Git worktrees. No two tracks may edit shared infrastructure without a dedicated shared-foundation issue and review.

## 10. Error handling and quality controls

- Generation scripts fail on invalid configuration rather than silently substituting values.
- dbt tests block publication of marts when primary-key, relationship, temporal, or accepted-value contracts fail.
- Reconciliation checks compare modeled revenue, users, and lifecycle states with trusted control totals.
- Notebook results identify their source models, execution date, filters, and code version.
- Expected designed failures are documented as incidents and repaired downstream without rewriting raw evidence.
- Agent requests outside approved domains or permissions are refused and recorded.

## 11. Testing strategy

### Data generation

- Determinism tests: the same seed produces the same result.
- Referential-integrity tests across generated entities.
- Distribution checks for scenario assumptions and injected failure rates.

### dbt

- Source freshness where meaningful.
- Unique, not-null, accepted-values, relationships, and custom business-rule tests.
- Scenario-specific selectors so each domain can build independently.
- Full `dbt build` as the integration gate.

### Analytics

- Trusted totals and hand-calculated sample cohorts.
- Sensitivity checks for alternative definitions and matching assumptions.
- Explicit cohort-maturity and time-boundary tests.
- Confidence intervals or uncertainty ranges where appropriate.

### Agent evaluation

- Standard, difficult, ambiguous, unanswerable, and adversarial questions.
- Scoring for metric, population, join logic, numeric result, uncertainty, refusal, provenance, latency, and cost.
- Regression runs after changes to models or metric definitions.

## 12. Scope exclusions

The first version will not include:

- Production writes or automatic publishing.
- Slack, email, or executive-message sending.
- Raw personal data.
- Paid warehouse dependencies.
- Multi-agent analytics orchestration.
- Fine-tuning.
- A complex web application or dashboard framework.
- Claims of production deployment or autonomous decision-making.

Docker or a dev container may be added only after the native macOS workflow and all builds are stable.

## 13. Portfolio outputs

The repository will ultimately expose:

- Architecture and setup documentation.
- Three metric catalogues.
- Three data-quality incident logs.
- Three flagship analytical notebooks.
- Three decision memos.
- A shared AI-review checklist.
- An agent evaluation report.
- A concise main README that routes recruiters to the three case studies.

Recommended CV wording after completion:

> Built and evaluated a governed product-analytics lab across gaming, subscription, and hybrid monetization scenarios using dbt, DuckDB, Python, tested semantic definitions, reproducible KPI diagnostics, and supervised AI-assisted analysis.

## 14. Delivery principle

Breadth is acceptable only if every scenario reaches a defensible minimum quality bar. A scenario is not complete until its data model, metrics, tests, diagnostic, limitations, and decision memo agree with one another.
