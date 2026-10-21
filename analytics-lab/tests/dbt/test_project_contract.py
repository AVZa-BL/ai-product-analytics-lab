from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_governed_dbt_connections_enforce_utc():
    profiles = yaml.safe_load((ROOT / "game_analytics/profiles.yml").read_text())
    for output in profiles["game_analytics"]["outputs"].values():
        assert output.get("settings", {}).get("TimeZone") == "UTC"
