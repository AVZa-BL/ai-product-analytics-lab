from pathlib import Path

import pandas as pd

from analytics_lab.generation.io import write_tables


def test_write_tables_uses_sorted_names_and_parquet(tmp_path: Path) -> None:
    tables = {
        "users": pd.DataFrame({"user_id": [2, 1]}),
        "events": pd.DataFrame({"event_id": [10]}),
    }
    paths = write_tables(tables, tmp_path)
    assert [path.name for path in paths] == ["events.parquet", "users.parquet"]
    assert pd.read_parquet(tmp_path / "users.parquet")["user_id"].tolist() == [2, 1]


