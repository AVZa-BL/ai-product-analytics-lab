"""The incident mart, audit model, register and tests must agree on which codes exist."""

import re
from pathlib import Path

MODELS = Path("game_analytics/models/hybrid_subscription")
MART = (MODELS / "marts/mart_hybrid_subscription__data_quality_incidents.sql").read_text()


def mart_codes() -> set[str]:
    return set(re.findall(r"when '([a-z_]+)'", MART))


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


