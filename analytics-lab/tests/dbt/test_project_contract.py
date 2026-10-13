from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_dbt_project_declares_all_scenario_paths_and_variables() -> None:
    project = yaml.safe_load((ROOT / "game_analytics/dbt_project.yml").read_text())
    models = project["models"]["game_analytics"]
    assert set(models) >= {
        "shared",
        "live_strategy",
        "subscription",
        "hybrid_subscription",
    }
    assert project["vars"]["raw_data_root"] == "../data/raw"


def test_selectors_cover_shared_and_all_scenarios() -> None:
    selectors = yaml.safe_load((ROOT / "game_analytics/selectors.yml").read_text())
    names = {selector["name"] for selector in selectors["selectors"]}
    assert names == {
        "shared",
        "live_strategy",
        "subscription",
        "hybrid_subscription",
    }


def test_governed_dbt_connections_enforce_utc():
    profiles = yaml.safe_load((ROOT / "game_analytics/profiles.yml").read_text())
    for output in profiles["game_analytics"]["outputs"].values():
        assert output.get("settings", {}).get("TimeZone") == "UTC"
