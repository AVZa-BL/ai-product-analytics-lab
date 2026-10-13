# Shared Analytics Lab Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic Python, DuckDB/dbt, documentation, validation, and CI foundation required by all three analytics scenarios.

**Architecture:** One installable `analytics_lab` Python package owns generation contracts, deterministic Parquet output, and the command-line entry point. The existing dbt project remains in `game_analytics/`, with shared models and macros plus isolated selectors for each scenario. Domain packages implement a fixed `generate(config)` interface without editing shared code.

**Tech Stack:** macOS ARM64, Python 3.12, pandas, PyArrow, DuckDB, dbt-core 1.12, dbt-duckdb 1.11, pytest, Ruff, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-08-27-three-scenario-analytics-lab-design.md`

## Global Constraints

- Use the existing repository and `.venv`; do not add Docker yet.
- All generated data must be synthetic, deterministic for a fixed seed, and excluded from Git.
- Scenario names are exactly `live_strategy`, `subscription`, and `hybrid_subscription`.
- Raw evidence is immutable; designed failures are corrected in modeled layers, never by rewriting raw output.
- Shared code must not contain scenario-specific metric or business logic.
- No production writes, paid warehouse dependency, messaging integration, PII, fine-tuning, or autonomous publishing.
- Every task ends with tests and a focused commit.

---

## File map

| File or directory | Responsibility |
|---|---|
| `pyproject.toml` | Python package metadata, dependencies, pytest and Ruff configuration |
| `src/analytics_lab/generation/base.py` | Immutable generation configuration and scenario-generator protocol |
| `src/analytics_lab/generation/io.py` | Deterministic Parquet persistence and file hashing |
| `src/analytics_lab/generate.py` | CLI validation, lazy scenario loading, generation and manifest output |
| `tests/generation/` | Unit tests for contracts, determinism and CLI behavior |
| `game_analytics/macros/raw_parquet.sql` | One controlled interface for reading scenario Parquet files |
| `game_analytics/models/shared/dim_dates.sql` | Shared calendar dimension |
| `game_analytics/models/shared/_shared__models.yml` | Shared model contracts and tests |
| `game_analytics/selectors.yml` | Independent shared and scenario build selectors |
| `docs/templates/` | Metric contract, incident, decision memo and AI audit templates |
| `scripts/validation/validate_docs.py` | Machine-check required headings in scenario documentation |
| `src/analytics_lab/evaluation.py` | Shared case validation and deterministic scoring of recorded agent answers |
| `src/analytics_lab/evaluate.py` | CLI for scoring scenario answer artifacts against trusted cases |
| `.github/workflows/ci.yml` | Unit, lint and shared-dbt validation on pushes and pull requests |

### Task 1: Replace tutorial scaffolding with an installable project baseline

**Files:**
- Create: `pyproject.toml`
- Create: `src/analytics_lab/__init__.py`
- Create: `tests/test_package.py`
- Modify: `.gitignore`
- Delete: `game_analytics/models/example/my_first_dbt_model.sql`
- Delete: `game_analytics/models/example/my_second_dbt_model.sql`
- Delete: `game_analytics/models/example/schema.yml`

**Interfaces:**
- Produces: importable package `analytics_lab` with `__version__: str`
- Produces: development command `python -m pytest`
- Consumes: Python 3.12 virtual environment already created at `.venv/`

- [ ] **Step 1: Write the package smoke test**

Create `tests/test_package.py`:

```python
from analytics_lab import __version__


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test and verify the package is missing**

Run:

```bash
source .venv/bin/activate
pytest tests/test_package.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'analytics_lab'`.

- [ ] **Step 3: Create package configuration**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "analytics-lab"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "duckdb>=1.3,<2",
  "numpy>=2.1,<3",
  "pandas>=2.2,<3",
  "pyarrow>=18,<22",
]

[project.optional-dependencies]
dev = [
  "dbt-core==1.12.3",
  "dbt-duckdb==1.11.0",
  "pytest>=8.3,<9",
  "jupyterlab>=4.3,<5",
  "jupytext>=1.17,<2",
  "nbconvert>=7.16,<8",
  "matplotlib>=3.9,<4",
  "seaborn>=0.13,<1",
  "scipy>=1.14,<2",
  "statsmodels>=0.14,<1",
  "pyyaml>=6,<7",
  "ruff>=0.12,<1",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Create `src/analytics_lab/__init__.py`:

```python
__version__ = "0.1.0"
```

Add these rules to `.gitignore`:

```gitignore
# Generated analytics data
data/raw/
data/generated/
generation_manifest.json

# Python packaging and coverage
*.egg-info/
.pytest_cache/
.ruff_cache/
```

Delete the three dbt tutorial files listed above, then remove the empty `models/example/` directory.

- [ ] **Step 4: Install the repository in editable mode**

Run:

```bash
python -m pip install -e '.[dev]'
```

Expected: installation ends successfully with `analytics-lab-0.1.0` installed.

- [ ] **Step 5: Run the smoke test and lint**

Run:

```bash
pytest tests/test_package.py -v
ruff check src tests
```

Expected: one test passes and Ruff reports `All checks passed!`.

- [ ] **Step 6: Commit the baseline**

```bash
git add .gitignore pyproject.toml src tests game_analytics/models
git commit -m "build: establish analytics lab package"
```

### Task 2: Define deterministic generation contracts and Parquet output

**Files:**
- Create: `src/analytics_lab/generation/__init__.py`
- Create: `src/analytics_lab/generation/base.py`
- Create: `src/analytics_lab/generation/io.py`
- Create: `tests/generation/test_base.py`
- Create: `tests/generation/test_io.py`

**Interfaces:**
- Produces: `GenerationConfig(scenario: str, seed: int, start_date: date, days: int, scale: int, output_dir: Path)`
- Produces: protocol `ScenarioGenerator.generate(config) -> dict[str, pandas.DataFrame]`
- Produces: `write_tables(tables, output_dir) -> list[Path]`
- Produces: `sha256_file(path) -> str`
- Consumes: pandas DataFrames supplied by scenario packages

- [ ] **Step 1: Write failing configuration tests**

Create `tests/generation/test_base.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from analytics_lab.generation.base import GenerationConfig


def test_generation_config_accepts_valid_values(tmp_path: Path) -> None:
    config = GenerationConfig(
        scenario="live_strategy",
        seed=42,
        start_date=date(2026, 1, 1),
        days=180,
        scale=1000,
        output_dir=tmp_path,
    )
    assert config.seed == 42
    assert config.output_dir == tmp_path


@pytest.mark.parametrize("field,value", [("days", 0), ("scale", 0), ("seed", -1)])
def test_generation_config_rejects_invalid_numeric_values(
    tmp_path: Path, field: str, value: int
) -> None:
    values = {
        "scenario": "subscription",
        "seed": 42,
        "start_date": date(2026, 1, 1),
        "days": 180,
        "scale": 1000,
        "output_dir": tmp_path,
    }
    values[field] = value
    with pytest.raises(ValueError):
        GenerationConfig(**values)
```

- [ ] **Step 2: Run the configuration tests and verify failure**

Run: `pytest tests/generation/test_base.py -v`

Expected: collection fails because `analytics_lab.generation.base` does not exist.

- [ ] **Step 3: Implement the immutable contract**

Create `src/analytics_lab/generation/__init__.py` as an empty file.

Create `src/analytics_lab/generation/base.py`:

```python
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class GenerationConfig:
    scenario: str
    seed: int
    start_date: date
    days: int
    scale: int
    output_dir: Path

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.days < 1:
            raise ValueError("days must be positive")
        if self.scale < 1:
            raise ValueError("scale must be positive")


class ScenarioGenerator(Protocol):
    def generate(self, config: GenerationConfig) -> dict[str, pd.DataFrame]: ...
```

- [ ] **Step 4: Run the configuration tests**

Run: `pytest tests/generation/test_base.py -v`

Expected: four tests pass.

- [ ] **Step 5: Write failing deterministic-output tests**

Create `tests/generation/test_io.py`:

```python
from pathlib import Path

import pandas as pd

from analytics_lab.generation.io import sha256_file, write_tables


def test_write_tables_uses_sorted_names_and_parquet(tmp_path: Path) -> None:
    tables = {
        "users": pd.DataFrame({"user_id": [2, 1]}),
        "events": pd.DataFrame({"event_id": [10]}),
    }
    paths = write_tables(tables, tmp_path)
    assert [path.name for path in paths] == ["events.parquet", "users.parquet"]
    assert pd.read_parquet(tmp_path / "users.parquet")["user_id"].tolist() == [2, 1]


def test_same_dataframe_produces_same_file_hash(tmp_path: Path) -> None:
    frame = pd.DataFrame({"id": [1, 2], "value": ["a", "b"]})
    first = write_tables({"sample": frame}, tmp_path / "first")[0]
    second = write_tables({"sample": frame}, tmp_path / "second")[0]
    assert sha256_file(first) == sha256_file(second)
```

- [ ] **Step 6: Run the output tests and verify failure**

Run: `pytest tests/generation/test_io.py -v`

Expected: collection fails because `analytics_lab.generation.io` does not exist.

- [ ] **Step 7: Implement deterministic Parquet writing**

Create `src/analytics_lab/generation/io.py`:

```python
from hashlib import sha256
from pathlib import Path

import pandas as pd


def write_tables(tables: dict[str, pd.DataFrame], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for table_name in sorted(tables):
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"invalid table name: {table_name}")
        path = output_dir / f"{table_name}.parquet"
        tables[table_name].to_parquet(path, index=False, compression="zstd")
        paths.append(path)
    return paths


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 8: Run all generation-contract tests**

Run:

```bash
pytest tests/generation/test_base.py tests/generation/test_io.py -v
ruff check src tests
```

Expected: six tests pass and Ruff passes.

- [ ] **Step 9: Commit the contracts**

```bash
git add src/analytics_lab/generation tests/generation
git commit -m "feat: add deterministic generation contracts"
```

### Task 3: Add the scenario generation CLI and provenance manifest

**Files:**
- Create: `src/analytics_lab/generate.py`
- Create: `tests/generation/test_cli.py`

**Interfaces:**
- Consumes: each module's `generate(config: GenerationConfig) -> dict[str, DataFrame]`
- Consumes: `write_tables` and `sha256_file`
- Produces: `main(argv: list[str] | None = None) -> int`
- Produces: scenario output at `<output-dir>/<scenario>/*.parquet`
- Produces: `<output-dir>/<scenario>/generation_manifest.json`

- [ ] **Step 1: Write the failing CLI test with an injected generator**

Create `tests/generation/test_cli.py`:

```python
import json
from pathlib import Path

import pandas as pd

from analytics_lab import generate


def test_cli_writes_tables_and_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        generate,
        "load_generator",
        lambda _scenario: lambda _config: {"users": pd.DataFrame({"user_id": [1, 2]})},
    )
    exit_code = generate.main(
        [
            "--scenario", "subscription",
            "--seed", "42",
            "--start-date", "2026-01-01",
            "--days", "180",
            "--scale", "1000",
            "--output-dir", str(tmp_path),
        ]
    )
    manifest_path = tmp_path / "subscription" / "generation_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert exit_code == 0
    assert manifest["scenario"] == "subscription"
    assert manifest["seed"] == 42
    assert manifest["tables"]["users"]["rows"] == 2
    assert len(manifest["tables"]["users"]["sha256"]) == 64
```

- [ ] **Step 2: Run the CLI test and verify failure**

Run: `pytest tests/generation/test_cli.py -v`

Expected: import fails because `analytics_lab.generate` does not exist.

- [ ] **Step 3: Implement the lazy loader, parser, and manifest**

Create `src/analytics_lab/generate.py`:

```python
import argparse
import importlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.io import sha256_file, write_tables

SCENARIO_MODULES = {
    "live_strategy": "analytics_lab.generation.live_strategy",
    "subscription": "analytics_lab.generation.subscription",
    "hybrid_subscription": "analytics_lab.generation.hybrid_subscription",
}


def load_generator(scenario: str) -> Callable[[GenerationConfig], dict[str, pd.DataFrame]]:
    module = importlib.import_module(SCENARIO_MODULES[scenario])
    return module.generate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic analytics scenarios")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIO_MODULES))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--days", required=True, type=int)
    parser.add_argument("--scale", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenario_dir = args.output_dir / args.scenario
    config = GenerationConfig(
        scenario=args.scenario,
        seed=args.seed,
        start_date=args.start_date,
        days=args.days,
        scale=args.scale,
        output_dir=scenario_dir,
    )
    tables = load_generator(args.scenario)(config)
    paths = write_tables(tables, scenario_dir)
    manifest = {
        "scenario": args.scenario,
        "seed": args.seed,
        "start_date": args.start_date.isoformat(),
        "days": args.days,
        "scale": args.scale,
        "tables": {
            path.stem: {
                "rows": len(tables[path.stem]),
                "sha256": sha256_file(path),
            }
            for path in paths
        },
    }
    (scenario_dir / "generation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify the CLI contract**

Run:

```bash
pytest tests/generation/test_cli.py -v
python -m analytics_lab.generate --help
ruff check src tests
```

Expected: the CLI test passes, help lists all three scenarios, and Ruff passes.

- [ ] **Step 5: Commit the CLI**

```bash
git add src/analytics_lab/generate.py tests/generation/test_cli.py
git commit -m "feat: add scenario generation CLI"
```

### Task 4: Establish shared dbt conventions and selectors

**Files:**
- Create: `game_analytics/macros/raw_parquet.sql`
- Create: `game_analytics/models/shared/dim_dates.sql`
- Create: `game_analytics/models/shared/_shared__models.yml`
- Create: `game_analytics/selectors.yml`
- Modify: `game_analytics/dbt_project.yml`
- Create: `tests/dbt/test_project_contract.py`

**Interfaces:**
- Produces: macro `raw_parquet(scenario_name, table_name)` returning a DuckDB `read_parquet(...)` relation
- Produces: model `dim_dates` with `date_day`, `year_number`, `month_number`, `week_start_date`, and `day_of_week_number`
- Produces: selectors `shared`, `live_strategy`, `subscription`, `hybrid_subscription`
- Consumes: scenario Parquet paths under `../data/raw/<scenario>/<table>.parquet`

- [ ] **Step 1: Write the failing dbt-project contract test**

Create `tests/dbt/test_project_contract.py`:

```python
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def test_dbt_project_declares_all_scenario_paths_and_variables() -> None:
    project = yaml.safe_load((ROOT / "game_analytics/dbt_project.yml").read_text())
    models = project["models"]["game_analytics"]
    assert set(models) >= {"shared", "live_strategy", "subscription", "hybrid_subscription"}
    assert project["vars"]["raw_data_root"] == "../data/raw"


def test_selectors_cover_shared_and_all_scenarios() -> None:
    selectors = yaml.safe_load((ROOT / "game_analytics/selectors.yml").read_text())
    names = {selector["name"] for selector in selectors["selectors"]}
    assert names == {"shared", "live_strategy", "subscription", "hybrid_subscription"}
```

Run `python -m pip install -e '.[dev]'` after confirming `pyyaml>=6,<7` is present in the `dev` dependency list created in Task 1.

- [ ] **Step 2: Run the contract test and verify failure**

Run: `pytest tests/dbt/test_project_contract.py -v`

Expected: tests fail because the shared configuration is absent.

- [ ] **Step 3: Create the controlled raw-data macro**

Create `game_analytics/macros/raw_parquet.sql`:

```sql
{% macro raw_parquet(scenario_name, table_name) %}
    {% set allowed_scenarios = ['live_strategy', 'subscription', 'hybrid_subscription'] %}
    {% if scenario_name not in allowed_scenarios %}
        {{ exceptions.raise_compiler_error('Unsupported scenario: ' ~ scenario_name) }}
    {% endif %}
    read_parquet(
        '{{ var("raw_data_root") }}/{{ scenario_name }}/{{ table_name }}.parquet'
    )
{% endmacro %}
```

- [ ] **Step 4: Add the shared date dimension and tests**

Create `game_analytics/models/shared/dim_dates.sql`:

```sql
with date_spine as (
    select cast(range as date) as date_day
    from range(date '2025-01-01', date '2028-01-01', interval 1 day)
)

select
    date_day,
    extract(year from date_day)::integer as year_number,
    extract(month from date_day)::integer as month_number,
    date_trunc('week', date_day)::date as week_start_date,
    extract(isodow from date_day)::integer as day_of_week_number
from date_spine
```

Create `game_analytics/models/shared/_shared__models.yml`:

```yaml
version: 2

models:
  - name: dim_dates
    description: One row per UTC calendar date used by all scenarios.
    columns:
      - name: date_day
        description: Primary calendar date.
        data_tests:
          - unique
          - not_null
      - name: day_of_week_number
        data_tests:
          - accepted_values:
              arguments:
                values: [1, 2, 3, 4, 5, 6, 7]
```

- [ ] **Step 5: Configure scenario model paths and selectors**

Replace the `models:` section of `game_analytics/dbt_project.yml` and add `vars:`:

```yaml
vars:
  raw_data_root: "../data/raw"

models:
  game_analytics:
    shared:
      +schema: shared
      +tags: [shared]
    live_strategy:
      +schema: live_strategy
      +tags: [live_strategy]
    subscription:
      +schema: subscription
      +tags: [subscription]
    hybrid_subscription:
      +schema: hybrid_subscription
      +tags: [hybrid_subscription]
```

Create `game_analytics/selectors.yml`:

```yaml
selectors:
  - name: shared
    definition:
      method: tag
      value: shared
  - name: live_strategy
    definition:
      union:
        - method: tag
          value: shared
        - method: tag
          value: live_strategy
  - name: subscription
    definition:
      union:
        - method: tag
          value: shared
        - method: tag
          value: subscription
  - name: hybrid_subscription
    definition:
      union:
        - method: tag
          value: shared
        - method: tag
          value: hybrid_subscription
```

Every scenario source YAML must use dbt-duckdb's external-source convention so `source()` reads Parquet directly. The scenario-specific pattern is:

```yaml
sources:
  - name: <scenario>_raw
    meta:
      external_location: "../data/raw/<scenario>/{name}.parquet"
```

Staging models must call `source('<scenario>_raw', '<table_name>')`; they must not hard-code `read_parquet` paths.

Create empty model directories for the three scenarios and preserve them with `.gitkeep` until scenario branches add models.

- [ ] **Step 6: Verify dbt configuration and shared build**

Run:

```bash
pytest tests/dbt/test_project_contract.py -v
cd game_analytics
dbt parse
dbt build --selector shared
cd ..
```

Expected: two Python tests pass; dbt parses; `dim_dates` builds and its three tests pass.

- [ ] **Step 7: Commit dbt conventions**

```bash
git add pyproject.toml game_analytics tests/dbt
git commit -m "feat: establish shared dbt conventions"
```

### Task 5: Add governed documentation templates and validation

**Files:**
- Create: `docs/templates/metric-contract.md`
- Create: `docs/templates/data-incident.md`
- Create: `docs/templates/decision-memo.md`
- Create: `docs/templates/ai-audit.md`
- Create: `scripts/validation/validate_docs.py`
- Create: `tests/validation/test_validate_docs.py`

**Interfaces:**
- Produces: `validate_document(path: Path, required_headings: tuple[str, ...]) -> list[str]`
- Produces: a consistent evidence contract used by every scenario plan
- Consumes: Markdown documents stored under `docs/metrics`, `docs/incidents`, `reports`, and `docs/ai-audit`

- [ ] **Step 1: Write failing document-validator tests**

Create `tests/validation/test_validate_docs.py`:

```python
from pathlib import Path

from scripts.validation.validate_docs import validate_document


def test_validate_document_returns_missing_headings(tmp_path: Path) -> None:
    document = tmp_path / "metric.md"
    document.write_text("# DAU\n\n## Formula\nDistinct active players.\n")
    missing = validate_document(document, ("Formula", "Grain", "Exclusions"))
    assert missing == ["Grain", "Exclusions"]


def test_validate_document_accepts_complete_document(tmp_path: Path) -> None:
    document = tmp_path / "metric.md"
    document.write_text("# DAU\n\n## Formula\nX\n## Grain\nY\n## Exclusions\nZ\n")
    assert validate_document(document, ("Formula", "Grain", "Exclusions")) == []
```

- [ ] **Step 2: Run the validator tests and verify failure**

Run: `pytest tests/validation/test_validate_docs.py -v`

Expected: collection fails because `scripts.validation.validate_docs` does not exist.

- [ ] **Step 3: Implement the validator**

Create empty `scripts/__init__.py` and `scripts/validation/__init__.py`, then create `scripts/validation/validate_docs.py`:

```python
from pathlib import Path


def validate_document(path: Path, required_headings: tuple[str, ...]) -> list[str]:
    lines = path.read_text().splitlines()
    headings = {line[3:].strip() for line in lines if line.startswith("## ")}
    return [heading for heading in required_headings if heading not in headings]
```

- [ ] **Step 4: Create the metric-contract template**

Create `docs/templates/metric-contract.md` with these exact second-level headings:

```markdown
# Metric name

## Business purpose
## Formula
## Grain
## Numerator
## Denominator
## Eligibility
## Exclusions
## Time and timezone
## Currency
## Data latency
## Dimensions
## Owner
## Validation
## Known limitations
```

- [ ] **Step 5: Create the remaining evidence templates**

Create `docs/templates/data-incident.md` with headings `Detection`, `Affected data`, `Root cause`, `Containment`, `Validation`, and `Residual risk`.

Create `docs/templates/decision-memo.md` with headings `Decision`, `Observed facts`, `Analytical inference`, `Assumptions`, `Uncertainty`, `Recommendation`, `Risks`, and `Next measurement`.

Create `docs/templates/ai-audit.md` with headings `Objective`, `Permitted context`, `Agent proposal`, `Tool calls and queries`, `Human validation`, `Rejected output`, `Corrections`, `Final reviewer`, and `Known limitations`.

- [ ] **Step 6: Verify templates and validator**

Run:

```bash
pytest tests/validation/test_validate_docs.py -v
ruff check scripts tests
```

Expected: two tests pass and Ruff passes.

- [ ] **Step 7: Commit governance templates**

```bash
git add docs/templates scripts tests/validation
git commit -m "docs: add governed analytics evidence templates"
```

### Task 6: Add the shared agent-evaluation schema and scorer

**Files:**
- Create: `src/analytics_lab/evaluation.py`
- Create: `src/analytics_lab/evaluate.py`
- Create: `tests/evaluation/test_scoring.py`

**Interfaces:**
- Produces: `load_cases(path: Path) -> list[dict[str, object]]`
- Produces: `score_answer(case: dict[str, object], answer: dict[str, object]) -> dict[str, object]`
- Produces: CLI `python -m analytics_lab.evaluate --scenario NAME --questions FILE --answers FILE --output FILE`
- Consumes: trusted YAML cases and recorded JSON agent answers; it does not call a model or execute SQL

- [ ] **Step 1: Write failing scorer tests**

Create `tests/evaluation/test_scoring.py`:

```python
from analytics_lab.evaluation import score_answer


def test_numeric_answer_passes_only_with_governed_semantics_and_provenance() -> None:
    case = {
        "id": "q01",
        "expected_metric": "d7_retention",
        "expected_population": "android_installs",
        "expected_value": 0.31,
        "tolerance": 0.005,
        "requires_refusal": False,
        "approved_relations": ["mart_retention"],
    }
    answer = {
        "id": "q01",
        "metric": "d7_retention",
        "population": "android_installs",
        "value": 0.312,
        "refused": False,
        "relations": ["mart_retention"],
        "uncertainty": "95% interval reported",
        "latency_ms": 850,
        "cost_usd": 0.01,
    }
    result = score_answer(case, answer)
    assert result["passed"] is True
    assert result["numeric_score"] == 1


def test_unanswerable_case_requires_refusal() -> None:
    case = {
        "id": "q02",
        "expected_metric": None,
        "expected_population": None,
        "expected_value": None,
        "tolerance": None,
        "requires_refusal": True,
        "approved_relations": [],
    }
    answer = {
        "id": "q02",
        "metric": None,
        "population": None,
        "value": None,
        "refused": False,
        "relations": [],
        "uncertainty": "",
        "latency_ms": 200,
        "cost_usd": 0.0,
    }
    assert score_answer(case, answer)["passed"] is False
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/evaluation/test_scoring.py -v`

Expected: collection fails because `analytics_lab.evaluation` does not exist.

- [ ] **Step 3: Implement deterministic answer scoring**

Create `src/analytics_lab/evaluation.py`:

```python
from pathlib import Path

import yaml

REQUIRED_CASE_FIELDS = {
    "id", "category", "question", "expected_metric", "expected_population",
    "expected_value", "tolerance", "requires_refusal", "approved_relations",
}


def load_cases(path: Path) -> list[dict[str, object]]:
    cases = yaml.safe_load(path.read_text())["questions"]
    for case in cases:
        missing = REQUIRED_CASE_FIELDS - set(case)
        if missing:
            raise ValueError(f"case {case.get('id', '<unknown>')} missing {sorted(missing)}")
    return cases


def score_answer(case: dict[str, object], answer: dict[str, object]) -> dict[str, object]:
    refusal_score = int(bool(answer["refused"]) == bool(case["requires_refusal"]))
    metric_score = int(answer["metric"] == case["expected_metric"])
    population_score = int(answer["population"] == case["expected_population"])
    approved = set(case["approved_relations"])
    provenance_score = int(set(answer["relations"]) <= approved)
    if case["expected_value"] is None:
        numeric_score = int(answer["value"] is None)
    else:
        numeric_score = int(
            answer["value"] is not None
            and abs(float(answer["value"]) - float(case["expected_value"]))
            <= float(case["tolerance"])
        )
    uncertainty_score = int(bool(answer["uncertainty"]) or bool(answer["refused"]))
    scores = {
        "metric_score": metric_score,
        "population_score": population_score,
        "numeric_score": numeric_score,
        "uncertainty_score": uncertainty_score,
        "refusal_score": refusal_score,
        "provenance_score": provenance_score,
        "latency_ms": answer["latency_ms"],
        "cost_usd": answer["cost_usd"],
    }
    scores["passed"] = all(
        scores[name] == 1
        for name in (
            "metric_score", "population_score", "numeric_score",
            "uncertainty_score", "refusal_score", "provenance_score",
        )
    )
    return scores
```

- [ ] **Step 4: Implement the scoring CLI**

Create `src/analytics_lab/evaluate.py`:

```python
import argparse
import json
from pathlib import Path

from analytics_lab.evaluation import load_cases, score_answer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    answers = {item["id"]: item for item in json.loads(args.answers.read_text())["answers"]}
    results = [
        {"id": case["id"], **score_answer(case, answers[case["id"]])}
        for case in load_cases(args.questions)
    ]
    payload = {
        "scenario": args.scenario,
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify and commit the evaluator**

Run:

```bash
pytest tests/evaluation/test_scoring.py -v
ruff check src tests
git add src/analytics_lab/evaluation.py src/analytics_lab/evaluate.py tests/evaluation/test_scoring.py
git commit -m "feat: add governed agent evaluation scorer"
```

Expected: two tests pass, Ruff passes, and the commit succeeds.

### Task 7: Add continuous integration and the shared quality gate

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `scripts/validation/run_shared_checks.sh`
- Modify: `README.md`

**Interfaces:**
- Produces: local command `bash scripts/validation/run_shared_checks.sh`
- Produces: GitHub Actions checks for Python 3.12, unit tests, Ruff and shared dbt build
- Consumes: editable development installation and the `shared` dbt selector

- [ ] **Step 1: Create the local quality-gate script**

Create `scripts/validation/run_shared_checks.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ruff check src scripts tests
pytest -v
(
  cd game_analytics
  dbt deps
  dbt build --selector shared
)
```

Make it executable:

```bash
chmod +x scripts/validation/run_shared_checks.sh
```

- [ ] **Step 2: Run the quality gate locally**

Run: `bash scripts/validation/run_shared_checks.sh`

Expected: Ruff passes, all Python tests pass, and the shared dbt model plus tests pass.

- [ ] **Step 3: Add the GitHub Actions workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  shared-quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install project
        run: python -m pip install -e '.[dev]'
      - name: Run shared checks
        run: bash scripts/validation/run_shared_checks.sh
```

- [ ] **Step 4: Replace the tutorial README with the foundation contract**

Write `README.md` with:

- Project purpose and explicit synthetic-data statement.
- Current status: shared foundation before scenario completion.
- Requirements: Apple Silicon-compatible Python 3.12, Git and Homebrew.
- Setup commands: activate `.venv`, install editable dependencies, run shared checks.
- Architecture link to the approved design specification.
- A three-row scenario table with status `Planned`.
- Limitations: local portfolio project, no production data, no autonomous decisions.

- [ ] **Step 5: Run the final shared-foundation verification**

Run:

```bash
bash scripts/validation/run_shared_checks.sh
git diff --check
git status --short
```

Expected: all checks pass, `git diff --check` prints nothing, and only the workflow, script and README changes are listed.

- [ ] **Step 6: Commit and push the shared foundation**

```bash
git add .github/workflows/ci.yml scripts/validation/run_shared_checks.sh README.md
git commit -m "ci: enforce shared analytics quality gate"
git push origin main
```

Expected: GitHub Actions reports the `shared-quality-gate` job as successful.

### Task 8: Create parallel scenario workstreams after the shared gate passes

**Files:**
- No source files changed.
- Create: GitHub issues and local Git worktrees.

**Interfaces:**
- Consumes: clean `main` with passing GitHub Actions
- Produces: branches `scenario/live-strategy`, `scenario/subscription`, and `scenario/hybrid-subscription`
- Produces: sibling worktrees under `~/Projects/ai-product-analytics-worktrees/`

- [ ] **Step 1: Confirm the dependency gate**

Run:

```bash
git switch main
git pull --ff-only
git status --short
gh run list --branch main --limit 1
```

Expected: working tree is clean and the latest CI run has status `completed` with conclusion `success`.

- [ ] **Step 2: Create the three scenario branches and worktrees**

Run:

```bash
mkdir -p ~/Projects/ai-product-analytics-worktrees
git worktree add -b scenario/live-strategy ~/Projects/ai-product-analytics-worktrees/live-strategy main
git worktree add -b scenario/subscription ~/Projects/ai-product-analytics-worktrees/subscription main
git worktree add -b scenario/hybrid-subscription ~/Projects/ai-product-analytics-worktrees/hybrid-subscription main
git worktree list
```

Expected: the main checkout plus three scenario worktrees are listed on distinct branches.

- [ ] **Step 3: Create one GitHub tracking issue per scenario**

Run:

```bash
gh issue create --title "Scenario: live strategy retention diagnostic" --body "Implement the live-strategy scenario according to docs/superpowers/plans/2026-08-27-live-strategy-scenario.md. Exit gate: generator, dbt models/tests, governed metrics, incident log, flagship notebook, decision memo, and agent evaluation all pass."
gh issue create --title "Scenario: subscription conversion diagnostic" --body "Implement the subscription scenario according to docs/superpowers/plans/2026-08-27-subscription-scenario.md. Exit gate: generator, dbt models/tests, governed metrics, incident log, flagship notebook, decision memo, and agent evaluation all pass."
gh issue create --title "Scenario: hybrid subscription cannibalization diagnostic" --body "Implement the hybrid-subscription scenario according to docs/superpowers/plans/2026-08-27-hybrid-subscription-scenario.md. Exit gate: generator, dbt models/tests, governed metrics, incident log, flagship notebook, decision memo, and agent evaluation all pass."
```

Expected: three issue URLs are returned.

- [ ] **Step 4: Record the clean parallel starting point**

Run:

```bash
git worktree list
gh issue list --state open --limit 10
```

Expected: three scenario worktrees and the three open scenario issues are visible. Do not implement two scenarios in the same worktree.

## Foundation completion gate

The shared foundation is complete only when:

1. `bash scripts/validation/run_shared_checks.sh` passes locally.
2. GitHub Actions passes on `main`.
3. The generation CLI exposes all three fixed scenario names.
4. The dbt project can build `shared` independently.
5. Governance templates and their validator are committed.
6. Each scenario has a dedicated plan, GitHub issue, branch, and worktree.
