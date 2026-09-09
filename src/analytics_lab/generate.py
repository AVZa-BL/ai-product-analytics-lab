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


def load_generator(
    scenario: str,
) -> Callable[[GenerationConfig], dict[str, pd.DataFrame]]:
    module = importlib.import_module(SCENARIO_MODULES[scenario])
    return module.generate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic analytics scenarios"
    )
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
