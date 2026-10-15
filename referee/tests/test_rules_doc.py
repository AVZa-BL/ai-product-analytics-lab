"""docs/rules.md is generated from the rule code, and must never drift from it."""

import subprocess
import sys
from pathlib import Path

import pytest

from referee.rules import Rule
from referee.rules.docs import render_rules_markdown

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "rules.md"

# A field each rule's "fires when" must name, so a careless edit of the text is noticed.
KEY_TERMS = {
    "HYP-001": "same text",
    "HYP-002": "primary_metric.governed_reference",
    "HYP-003": "population.analysis_unit",
    "HYP-004": "design.sided",
    "HYP-005": "primary_metric.kind",
    "DES-001": "planned_duration_days",
    "DES-002": "multiple of 7",
    "DES-003": "below 14",
    "DES-004": "not all equal",
    "DES-005": "design.alpha_adjustment",
    "DES-006": "population.interference",
    "DES-007": "population.exposure_timing",
    "DES-008": "design.pre_period_covariate",
    "PRO-001": "procedure.stopping_rule",
    "PRO-002": "procedure.srm_check_cadence",
    "PRO-003": "no guardrails",
    "PRO-004": "procedure.bucketing_salt",
    "RES-001": "arms[].allocation",
    "RES-002": "fewer players than",
    "RES-003": "design.min_duration_days",
    "RES-011": "divided by the number of weeks",
    "RES-012": "after their first purchase",
    "RES-013": "arm_config_version",
}


def rule(rule_id: str, **overrides: object) -> Rule:
    fields: dict = {
        "id": rule_id,
        "severity": "warning",
        "title": f"Title of {rule_id}",
        "fires_when": f"{rule_id} fires.",
        "why_it_matters": f"Why {rule_id}.",
        "remediation": f"Fix {rule_id}.",
        "references": (),
        "check": lambda context: None,
    }
    return Rule(**{**fields, **overrides})


# --- The committed file ----------------------------------------------------------------


def test_the_documented_command_regenerates_the_committed_file() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "referee.rules.docs"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout == DOC.read_text(encoding="utf-8")


# --- What it says about the rules ------------------------------------------------------


# --- The "fires when" texts ------------------------------------------------------------


# --- The generator ---------------------------------------------------------------------


def test_a_rule_whose_prefix_has_no_group_is_refused() -> None:
    with pytest.raises(ValueError, match="XYZ-001 has no group: add 'XYZ' to GROUPS"):
        render_rules_markdown([rule("XYZ-001")])


def test_a_group_with_no_rules_is_left_out() -> None:
    text = render_rules_markdown([rule("HYP-001")])

    assert "## Hypothesis rules (HYP)" in text
    assert "## Design rules" not in text and "## Procedure rules" not in text


