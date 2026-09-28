# Getting started

This repository generates synthetic data for three product-analytics scenarios, models it with dbt into a local DuckDB file, and publishes governed metrics, diagnostics and decision memos. Nothing is deployed and nothing talks to a network — everything below runs on your machine and can be deleted afterwards.

Allow about ten minutes to get from a fresh clone to querying modelled data.

## Prerequisites

- **Python 3.12 exactly.** `pyproject.toml` pins `>=3.12,<3.13`; 3.11 and 3.13 will fail to install.
- **Git**
- **About 2 GB free disk** for the virtual environment, generated Parquet and the DuckDB file
- macOS or Linux, with `bash` or `zsh`

## 1. Install

```bash
git clone https://github.com/AVZa-BL/ai-product-analytics-lab.git
cd ai-product-analytics-lab
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python --version
```

The last line should report 3.12.x.

## 2. Verify the install

```bash
bash scripts/validation/run_shared_checks.sh
```

This runs `ruff`, the full test suite, and a dbt build of the shared layer. Expect `All checks passed!`, a passing test count, and `Done. PASS=4 ... ERROR=0`.

If this fails, stop here. Nothing below will work until it passes.

## 3. Build a scenario

Each scenario is independently buildable:

```bash
bash scripts/validation/run_live_strategy_checks.sh
bash scripts/validation/run_subscription_checks.sh
bash scripts/validation/run_hybrid_subscription_checks.sh
```

Expect `PASS=153`, `PASS=102` and `PASS=348`. The hybrid build takes about two minutes; the other two about thirty seconds each.

Each script generates deterministic synthetic Parquet into `data/raw/`, then builds only that scenario's models and tests. They share `game_analytics/dev.duckdb`, so running all three leaves all three schemas available at once.

The data is seeded, so the generated Parquet is byte-identical on every machine — verified across macOS/arm64 and Linux/x86_64 by SHA-256 over the generated files.

Downstream figures are a weaker guarantee. Re-running a diagnostic on the same platform that produced a published report reproduces it exactly; re-running it on a different platform can shift values slightly. The live-strategy D7 memo documents a measured case: one player moves between periods on Linux/x86_64, and the observed change reads −3.19% instead of the published −3.97%. The published reports name the platform they were produced on, and the cause of the divergence is still being traced. If your numbers differ from a committed report, check the platform before assuming you have found a bug.

## 4. Query the modelled data

**Connect from inside `game_analytics/`.** The models are DuckDB views over Parquet using relative paths; connecting from elsewhere produces confusing catalog errors.

```bash
cd game_analytics
python -c "
import duckdb
c = duckdb.connect('dev.duckdb', read_only=True)
print(c.sql('''
  select metric_date, signups, trial_starts, mrr_usd
  from main_subscription.mart_subscription__kpis_daily
  where signups > 0 order by metric_date limit 5
''').df().to_string(index=False))
c.close()"
cd ..
```

The schemas are `main_shared`, `main_live_strategy`, `main_subscription` and `main_hybrid_subscription`. List what exists with `select table_schema, table_name from information_schema.tables order by 1, 2`.

## 5. Reproduce a published diagnostic

Notebooks are stored as jupytext percent-format Python, not `.ipynb`, so they diff as text. Execute one:

```bash
./.venv/bin/python -m jupytext --to notebook --execute notebooks/live_strategy/01_d7_retention_diagnostic.py --output notebooks/live_strategy/01_d7_retention_diagnostic.ipynb
```

This rewrites `reports/live_strategy/d7_retention_diagnostic_results.json`. Compare it with the committed version. On the platform the report was produced on, every analytical value should be identical, with only `code_version`, `executed_at_utc` and `input_fingerprint` changing. If an analytical value moves on that platform, that is a real finding, not noise — and `input_fingerprint.sha256` tells you immediately whether the inputs changed or only the computation did.

Generated `.ipynb` files and figures are gitignored by design — the committed JSON is the published evidence, not the notebook.

## 6. Run the agent evaluation

```bash
python -m analytics_lab.evaluate --scenario subscription --questions docs/ai-audit/subscription_questions.yaml --answers scripts/evaluation/subscription_answers.json --output reports/subscription/agent_evaluation.json
```

Exit status is 0 only when every case passes. Cases are scored on metric, population, numeric value within tolerance, uncertainty, refusal and provenance.

This scores **recorded answer fixtures**, not a live agent. It is a regression test on governed definitions, and it does not measure model reasoning.

## 7. What to read, and in what order

| Path | What it tells you |
| --- | --- |
| `README.md` | The three case studies and their status |
| `docs/metrics/` | Metric contracts: grain, numerator, denominator, exclusions, interpretation boundary |
| `docs/incidents/` | The intentional data defects, how each is detected and contained |
| `reports/` | The decision memos: the analysis, its uncertainty, and what it refuses to claim |
| `docs/ai-audit/` | What was proposed, what was rejected, what was corrected |
| `docs/superpowers/specs/` | The approved architecture and scenario boundaries |

If you read only one thing, read a decision memo's **Assumptions and uncertainty** section. That is where the project does its real work.

## Troubleshooting

**`python3.12: command not found`** — install Python 3.12. The pin is deliberate; the project will not install on 3.11 or 3.13.

**`zsh: no matches found: --include=*.py`** — zsh expands globs before the command sees them. Quote them: `--include='*.py'`.

**`sed: -i may not be used with stdin`** on macOS — BSD `sed` needs `sed -i ''`. Prefer a Python one-liner or an editor.

**`Catalog Error: Table with name ... does not exist`** — either you are not connected from inside `game_analytics/`, or that scenario has not been built yet. Re-run its check script.

**A scenario build pulls in another scenario's tests** — the check scripts pass `--indirect-selection cautious` for exactly this reason. If you invoke `dbt build` by hand, pass it too, or dbt will drag in any test that touches the shared calendar model.

**Everything passes locally but fails in CI** — you probably have an untracked file that CI does not. Check `git status --short --ignored` before trusting a local green run.
