from pathlib import Path

import yaml

MODEL_DIR = Path("game_analytics/models/hybrid_subscription/marts")
TEST_DIR = Path("game_analytics/tests/hybrid_subscription")
EXPECTED_MODELS = {
    "mart_hybrid_subscription__experiment_arm_daily",
    "mart_hybrid_subscription__experiment_readout",
}
EXPECTED_TESTS = {
    "assert_experiment_arm_daily_reconciles.sql",
    "assert_experiment_readout_reconciles.sql",
}


def test_experiment_marts_publish_governed_contracts() -> None:
    schema = yaml.safe_load((MODEL_DIR / "experiment_schema.yml").read_text())
    models = {model["name"]: model for model in schema["models"]}

    assert set(models) == EXPECTED_MODELS
    assert EXPECTED_MODELS <= {path.stem for path in MODEL_DIR.glob("*.sql")}
    for model in models.values():
        assert "hybrid_subscription" in model["config"]["tags"]


def test_experiment_mart_invariants_have_executable_dbt_tests() -> None:
    assert EXPECTED_TESTS <= {path.name for path in TEST_DIR.glob("*.sql")}


EXPECTED_UNIT_TESTS = {
    "experiment_first_exposure_edge_cases",
    "experiment_first_exposure_tie_break",
    "experiment_eligible_population_verdicts_and_window",
    "experiment_srm_counts_and_threshold",
    "experiment_srm_alarm_threshold_boundary",
    "experiment_arm_daily_buckets_sums_and_nulls",
    "experiment_readout_rates_differences_and_containment",
    "experiment_readout_top_one_percent_rounds_up",
}


def test_experiment_rules_the_data_never_reaches_have_dbt_unit_tests() -> None:
    """At CI scale no experiment is flagged and no player is never exposed.

    So the unit tests alone hold those rules, and they must not be dropped silently.
    """
    names: set[str] = set()
    for path in (
        Path("game_analytics/models/hybrid_subscription/intermediate/schema.yml"),
        MODEL_DIR / "experiment_schema.yml",
    ):
        names |= {test["name"] for test in yaml.safe_load(path.read_text()).get("unit_tests", [])}

    assert EXPECTED_UNIT_TESTS <= names
