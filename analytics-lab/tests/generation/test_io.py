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
