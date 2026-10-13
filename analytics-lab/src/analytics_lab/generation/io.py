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
