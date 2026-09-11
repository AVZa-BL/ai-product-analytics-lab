#!/usr/bin/env bash
set -euo pipefail

python -m analytics_lab.generate \
  --scenario hybrid_subscription \
  --seed 42 \
  --start-date 2026-01-01 \
  --days 180 \
  --scale 1000 \
  --output-dir data/raw

(
  cd game_analytics
  dbt deps --profiles-dir .
  dbt parse --profiles-dir . --no-partial-parse
  dbt build --selector hybrid_subscription --profiles-dir .
)
