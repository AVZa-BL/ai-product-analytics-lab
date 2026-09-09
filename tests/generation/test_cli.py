import json
from pathlib import Path

import pandas as pd

from analytics_lab import generate


def test_cli_writes_tables_and_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        generate,
        "load_generator",
        lambda _scenario: lambda _config: {
            "users": pd.DataFrame({"user_id": [1, 2]})
        },
    )
    exit_code = generate.main(
        [
            "--scenario",
            "subscription",
            "--seed",
            "42",
            "--start-date",
            "2026-01-01",
            "--days",
            "180",
            "--scale",
            "1000",
            "--output-dir",
            str(tmp_path),
        ]
    )
    manifest_path = tmp_path / "subscription" / "generation_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert exit_code == 0
    assert manifest["scenario"] == "subscription"
    assert manifest["seed"] == 42
    assert manifest["tables"]["users"]["rows"] == 2
    assert len(manifest["tables"]["users"]["sha256"]) == 64
