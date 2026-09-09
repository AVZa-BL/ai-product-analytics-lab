# AI Product Analytics Lab

A portfolio project demonstrating governed, reproducible product analytics across three synthetic business scenarios. All data is generated locally; the repository contains no production, customer, or employer data.

## Current status

The shared Python, DuckDB, dbt, governance, and evaluation foundation is complete. Scenario implementations are planned and will be developed independently after the shared quality gate passes.

| Scenario | Analytical focus | Status |
| --- | --- | --- |
| Live strategy game | Retention and progression diagnostic | Planned |
| Subscription product | Conversion and lifecycle diagnostic | Planned |
| Hybrid game subscription | Cannibalization and entitlement diagnostic | Planned |

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
