#!/usr/bin/env bash
set -euo pipefail

ruff check src scripts tests
pytest -v
(
  cd game_analytics
  dbt deps --profiles-dir .
  dbt build --selector shared --indirect-selection cautious --profiles-dir .
)
