"""The experiment is part of the hybrid scenario, and the scenario's own tables did not move."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from analytics_lab import generate as generate_cli
from analytics_lab.generation.base import GenerationConfig
from analytics_lab.generation.hybrid_experiment import TABLE_NAMES as EXPERIMENT_TABLES
from analytics_lab.generation.hybrid_subscription import generate

SCENARIO_TABLES = (
    "currency_ledger",
    "live_event_participation",
    "marketing_exposures",
    "players",
    "product_catalogue",
    "sessions",
    "store_transactions",
    "subscription_events",
)

# SHA-256 of each table's CSV text at the CI settings (seed 42, 2026-01-01, 180 days, 1,000
# players), computed on the code before the experiment existed. If one of these changes, the
# scenario's data changed, and every governed result built on it with it.
CI_TABLE_FINGERPRINTS = {
    "currency_ledger": "4b8cfa37cc0d6c7803f08b1fc83e970b7779f3644a3b99933f7c45e7532212d6",
    "live_event_participation": "403dee814998f4e4629a4e9ffcaeb9ad421e820017719ec0e69fbbc15de361d8",
    "marketing_exposures": "a3ebd3014e3ad142f99215cfbd7dec4a447d9b6cef2a01d8bccb6233e753b968",
    "players": "f6dd95971cadb7a71c01cd96ef30ac79e07552716d82aeb047f07e52be30f7ea",
    "product_catalogue": "ae28e108e14e2ae7e99261ede1df70952b8e89edefaaaab1fdf364826ef617d9",
    "sessions": "47b72e942bd3a9f300220a3d7a0ae3b30cb85e360b64c39fcfff806ce4ebb328",
    "store_transactions": "5d72062fec801f72638c8b771f4bda5dc44959f6b8067e6b3cb5f4e3521ab06b",
    "subscription_events": "15281f13c55f677f9156e6575c4b3ef12561d5b4d16494b6f1e00bd86f62e5d6",
}


def config(scale: int = 1_000, days: int = 180, seed: int = 42) -> GenerationConfig:
    return GenerationConfig(
        scenario="hybrid_subscription",
        seed=seed,
        start_date=date(2026, 1, 1),
        days=days,
        scale=scale,
        output_dir=Path("data/raw"),
    )


@pytest.fixture(scope="module")
def ci_tables() -> dict[str, pd.DataFrame]:
    return generate(config())


def fingerprint(frame: pd.DataFrame) -> str:
    return hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()


def test_the_eight_old_tables_match_their_fingerprints_from_before_the_experiment(
    ci_tables: dict[str, pd.DataFrame],
) -> None:
    assert {name: fingerprint(ci_tables[name]) for name in SCENARIO_TABLES} == (
        CI_TABLE_FINGERPRINTS
    )


def test_the_command_line_writes_all_eleven_tables_and_lists_them_in_the_manifest(
    tmp_path: Path,
) -> None:
    exit_code = generate_cli.main(
        [
            "--scenario",
            "hybrid_subscription",
            "--seed",
            "42",
            "--start-date",
            "2026-01-01",
            "--days",
            "180",
            "--scale",
            "300",
            "--output-dir",
            str(tmp_path),
        ]
    )
    folder = tmp_path / "hybrid_subscription"
    manifest = json.loads((folder / "generation_manifest.json").read_text())

    assert exit_code == 0
    assert set(manifest["tables"]) == set(SCENARIO_TABLES) | set(EXPERIMENT_TABLES)
    assert all(len(entry["sha256"]) == 64 for entry in manifest["tables"].values())
    assert all(entry["rows"] > 0 for entry in manifest["tables"].values())
    assert {path.stem for path in folder.glob("*.parquet")} == set(manifest["tables"])


