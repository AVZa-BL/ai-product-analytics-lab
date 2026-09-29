#!/usr/bin/env bash
# Build one scenario in isolation: generate its deterministic fixture, then run
# only that scenario's governed dbt nodes.
#
# --indirect-selection cautious is required for isolation. Every scenario
# selector unions tag:shared, and dbt's default eager indirect selection pulls
# in any test with at least one selected parent. Without cautious, a singular
# test that references the shared calendar model is dragged into every other
# scenario's build, where its own relations do not exist.
set -euo pipefail

SCENARIO="${1:?usage: run_scenario_checks.sh <scenario>}"

case "${SCENARIO}" in
  live_strategy | subscription | hybrid_subscription) ;;
  *)
    echo "unknown scenario: ${SCENARIO}" >&2
    exit 2
    ;;
esac

python -m analytics_lab.generate \
  --scenario "${SCENARIO}" \
  --seed 42 \
  --start-date 2026-01-01 \
  --days 180 \
  --scale 1000 \
  --output-dir data/raw

(
  cd game_analytics
  dbt deps --profiles-dir .
  dbt parse --profiles-dir . --no-partial-parse
  dbt build --selector "${SCENARIO}" --indirect-selection cautious --profiles-dir .
)
