# AI Product Analytics Lab

A portfolio project demonstrating governed, reproducible product analytics across three synthetic business scenarios. All data is generated locally; the repository contains no production, customer, or employer data.

## Current status

The shared Python, DuckDB, dbt, governance, and evaluation foundation is complete. Scenario implementations are developed independently and validated through scenario-specific quality gates.

| Scenario | Analytical focus | Status |
| --- | --- | --- |
| Live strategy game | Retention and progression diagnostic | Complete |
| Subscription product | Conversion and lifecycle diagnostic | Complete |
| Hybrid game subscription | Cannibalization and entitlement diagnostic | Complete; native dbt and Jupyter execution validated |

## Live Strategy case study

The Live Strategy case study publishes a governed [metric catalogue](docs/metrics/live_strategy.md), [incident register](docs/incidents/live_strategy.md), executable [D7 diagnostic notebook](notebooks/live_strategy/01_d7_retention_diagnostic.py), [decision memo](reports/live_strategy/d7_retention_diagnostic.md), and [trusted evaluation cases](docs/ai-audit/live_strategy_questions.yaml). Together they demonstrate metric contracts, explicit data-defect containment, reproducible observational analysis, causal boundaries, and refusal of requests outside approved marts.

## Subscription case study

The Subscription case study publishes nine governed [metric contracts](docs/metrics/subscription/), a [data-quality incident record](docs/incidents/subscription/2026-08-27-subscription-data-quality.md), an executable [trial-to-paid diagnostic notebook](notebooks/subscription/trial_to_paid_diagnostic.ipynb), a [decision memo](reports/subscription/trial_to_paid_decision_memo.md), an [AI audit](docs/ai-audit/subscription/trial_to_paid_diagnostic.md), and [trusted evaluation cases](scripts/evaluation/subscription_questions.yaml) with a deterministic [score report](reports/subscription/agent_evaluation.json). The diagnostic separates acquisition mix, onboarding performance, activation behavior, payment failures and plan mix as candidate explanations of a mature trial-to-paid decline, and declines to assign a causal driver without a controlled experiment.

## Hybrid subscription case study

The Hybrid Subscription case study publishes a governed [metric catalogue](docs/metrics/hybrid_subscription.md), [incident register](docs/incidents/hybrid_subscription.md), executable [engagement and cannibalization diagnostic](notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py), [decision memo](reports/hybrid_subscription/engagement_cannibalization_decision_memo.md), and [trusted evaluation cases](docs/ai-audit/hybrid_subscription_questions.yaml) with a deterministic [score report](reports/hybrid_subscription/agent_evaluation.json). The [regenerated results JSON](reports/hybrid_subscription/engagement_cannibalization_diagnostic_results.json) publishes matched/unmatched population counts, reconciled engagement and separate standalone/subscription/total cash evidence, monthly KPIs, and conversion/D30 context. The catalogue covers all ten approved KPI contracts. Deterministic matching remains observational and does not establish causality. Native dbt execution, Jupyter kernel execution, and real-checkout HEAD provenance validation succeeded, as recorded in the [native validation report](reports/hybrid_subscription/native_validation.json) and [AI audit](docs/ai-audit/hybrid_subscription.md). The score report evaluates canonical recorded fixtures, not live-agent reasoning or autonomous decisions.

## Requirements

- Python 3.12, compatible with Apple Silicon
- Git
- Homebrew for macOS package management

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
bash scripts/validation/run_shared_checks.sh
```

## Architecture

The approved design and scenario boundaries are documented in [the architecture specification](docs/superpowers/specs/2026-08-27-three-scenario-analytics-lab-design.md).

## Limitations

- This is a local portfolio project, not a production analytics platform.
- All data is synthetic and should not be treated as evidence about a real product.
- The evaluator scores recorded answer artifacts; it does not authorize autonomous decisions.
- Production security, orchestration, warehouse scaling, and deployment are outside the current scope.
