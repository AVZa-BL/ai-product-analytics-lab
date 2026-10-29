"""docs/data-contract.md is generated from the loader's tables, and must never drift from them."""

import subprocess
import sys
from pathlib import Path

from referee.data import _REQUIRED
from referee.data_contract import OPTIONAL_COLUMNS, render_data_contract_markdown
from referee.results import COVARIATE_REASONS, METRICS, REASONS

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "data-contract.md"


def test_the_documented_command_regenerates_the_committed_file() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "referee.data_contract"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0
    assert DOC.read_text(encoding="utf-8") == result.stdout == render_data_contract_markdown()


def test_every_column_metric_and_reason_the_loader_knows_is_in_the_contract() -> None:
    text = render_data_contract_markdown()

    named = [c for columns in _REQUIRED.values() for c in columns]
    named += [c for columns in OPTIONAL_COLUMNS.values() for c in columns]
    named += list(METRICS) + list(REASONS) + list(COVARIATE_REASONS)
    assert [name for name in named if f"`{name}`" not in text] == []
