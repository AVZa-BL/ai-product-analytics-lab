"""Prevent the revenue/population/player-dimension dependency cycle."""

import re
from pathlib import Path

import pytest

MODEL_ROOT = Path(__file__).resolve().parents[2] / "game_analytics" / "models"


def referenced_models(source):
    return set(re.findall(r"\bref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", source))


@pytest.mark.parametrize(
    "source",
    ["{{ ref('model') }}", '{{ ref("model") }}', "{{ ref ( 'model' ) }}", "{{ ref(\n'model'\n) }}"],
)
def test_dependency_parser_handles_literal_ref_quote_and_whitespace_variants(source):
    assert referenced_models(source) == {"model"}


def test_transaction_fact_reads_player_attributes_without_population_dependency():
    source = (
        MODEL_ROOT / "hybrid_subscription/marts/fct_hybrid_subscription__store_transactions.sql"
    ).read_text()
    refs = referenced_models(source)
    assert "stg_hybrid_subscription__players" in refs
    assert "dim_hybrid_subscription__players" not in refs


def test_hybrid_model_dependency_graph_is_acyclic():
    models = {path.stem: path for path in MODEL_ROOT.rglob("*.sql")}
    dependencies = {name: referenced_models(path.read_text()) for name, path in models.items()}
    visited = set()

    def visit(name, active):
        assert name not in active, f"Dependency cycle: {' -> '.join([*active, name])}"
        if name in visited:
            return
        assert name in dependencies, f"Missing dependency model: {name}"
        for dependency in sorted(dependencies[name]):
            visit(dependency, [*active, name])
        visited.add(name)

    for name in sorted(models):
        if "hybrid_subscription" in name:
            visit(name, [])
