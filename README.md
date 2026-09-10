# AI Product Analytics Lab

A portfolio project demonstrating governed, reproducible product analytics across three synthetic business scenarios. All data is generated locally; the repository contains no production, customer, or employer data.

## Current status

The shared Python, DuckDB, dbt, governance, and evaluation foundation is complete. Scenario implementations are developed independently and validated through scenario-specific quality gates.

| Scenario | Analytical focus | Status |
| --- | --- | --- |
| Live strategy game | Retention and progression diagnostic | Complete |
| Subscription product | Conversion and lifecycle diagnostic | Complete |
| Hybrid game subscription | Cannibalization and entitlement diagnostic | In progress |

## Live Strategy case study

The Live Strategy case study publishes a governed [metric catalogue](docs/metrics/live_strategy.md), [incident register](docs/incidents/live_strategy.md), executable [D7 diagnostic notebook](notebooks/live_strategy/01_d7_retention_diagnostic.py), [decision memo](reports/live_strategy/d7_retention_diagnostic.md), and [trusted evaluation cases](docs/ai-audit/live_strategy_questions.yaml). Together they demonstrate metric contracts, explicit data-defect containment, reproducible observational analysis, causal boundaries, and refusal of requests outside approved marts.

## Hybrid subscription case study

The Hybrid Subscription case study publishes a governed [metric catalogue](docs/metrics/hybrid_subscription.md), [incident register](docs/incidents/hybrid_subscription.md), executable [engagement and cannibalization diagnostic](notebooks/hybrid_subscription/01_engagement_cannibalization_diagnostic.py), and [decision memo](reports/hybrid_subscription/engagement_cannibalization_decision_memo.md). It is backed by deterministic source generation, tested dbt staging/intermediate/mart layers, entitlement reconstruction, revenue reconciliation, and explicit causal boundaries for engagement-lift and store-cannibalization analysis.

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
