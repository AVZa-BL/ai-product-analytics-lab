from datetime import date
from pathlib import Path

import pytest

from analytics_lab.generation.base import GenerationConfig


@pytest.mark.parametrize("field,value", [("days", 0), ("scale", 0)])
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
