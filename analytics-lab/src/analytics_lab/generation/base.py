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
