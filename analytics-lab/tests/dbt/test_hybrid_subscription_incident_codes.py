"""The incident mart, audit model, register and tests must agree on which codes exist."""

import re
from pathlib import Path

MODELS = Path("game_analytics/models/hybrid_subscription")
TESTS = Path("game_analytics/tests/hybrid_subscription")
MART = (MODELS / "marts/mart_hybrid_subscription__data_quality_incidents.sql").read_text()
AUDIT = (MODELS / "intermediate/int_hybrid_subscription__quality_audit.sql").read_text()
REGISTER = Path("docs/incidents/hybrid_subscription.md").read_text()
RECONCILE = (TESTS / "assert_hybrid_incident_counts_reconcile.sql").read_text()
DETECTED = (TESTS / "assert_expected_hybrid_incidents_detected.sql").read_text()
CONTAINMENT = (TESTS / "assert_hybrid_containment_rules_hold.sql").read_text()
EXPERIMENT_CODES = {
    "experiment_exposure_after_purchase",
    "experiment_sample_ratio_mismatch",
    "experiment_mid_test_config_change",
}


def mart_codes() -> set[str]:
    return set(re.findall(r"when '([a-z_]+)'", MART))


def test_the_mart_publishes_exactly_the_codes_the_audit_and_its_own_union_produce() -> None:
    produced = set(re.findall(r"'([a-z_]+)'\s+as incident_code", AUDIT + MART))

    assert produced == mart_codes()


def case_blocks() -> dict[str, str]:
    """The body of each `case incident_code ... end as <column>` block in the mart, by column."""
    found = re.findall(r"case incident_code\n(.*?)\n\s*end as (\w+)", MART, re.S)
    return {column: body for body, column in found}


def test_every_code_has_an_entry_in_each_case_block_that_has_no_default() -> None:
    # category, affected metric and containment text have no else branch, so a code missing
    # from one publishes NULL. Severity has a default, so a missing entry is not an error there.
    # Each block is checked on its own: five codes also appear in the severity block, so a count
    # over the whole file would let one of them lose a category, metric or containment entry.
    blocks = case_blocks()

    assert set(blocks) == {"incident_category", "severity", "affected_metric", "containment_rule"}
    for column in ("incident_category", "affected_metric", "containment_rule"):
        for code in mart_codes():
            assert f"when '{code}'" in blocks[column], f"{code} has no entry in {column}"


def test_every_code_is_in_the_register_and_recounted_by_the_reconcile_test() -> None:
    for code in mart_codes():
        assert f"`{code}`" in REGISTER, f"{code} is missing from the register"
        assert f"'{code}'" in RECONCILE, f"{code} has no independent recount"


def test_the_experiment_incidents_are_detected_and_their_containment_is_enforced() -> None:
    assert EXPERIMENT_CODES <= mart_codes()
    for code in EXPERIMENT_CODES:
        assert f"'{code}'" in DETECTED, f"{code} is not in the expected-detected test"
        assert f"'{code}'" in CONTAINMENT, f"{code} has no containment enforcement"
