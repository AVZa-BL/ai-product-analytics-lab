"""docs/rules.md is generated from the rule code, and must never drift from it."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from referee.rules import CATALOGUE, Escalation, Rule
from referee.rules.docs import GROUPS, render_rules_markdown

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


def test_the_committed_catalogue_is_what_the_rules_generate() -> None:
    assert DOC.read_text(encoding="utf-8") == render_rules_markdown(), (
        "docs/rules.md has drifted from the rule code. From referee/, run: "
        "python -m referee.rules.docs > docs/rules.md"
    )


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


def test_the_file_is_tidy() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\n\n\n" not in text and "\t" not in text and "\r" not in text
    assert not any(line != line.rstrip() for line in text.splitlines())


# --- What it says about the rules ------------------------------------------------------


def test_every_rule_has_a_section_once_in_catalogue_order() -> None:
    headings = re.findall(r"^### ([A-Z]{3}-\d{3}): (.+)$", render_rules_markdown(), re.M)

    assert headings == [(r.id, r.title) for r in CATALOGUE]


def test_each_rule_sits_under_its_own_group() -> None:
    text = render_rules_markdown()
    sections = re.split(r"^## ", text, flags=re.M)
    by_group = {
        name: sections_text
        for name in GROUPS.values()
        for sections_text in sections
        if sections_text.startswith(f"{name} rules")
    }

    for prefix, name in GROUPS.items():
        ids = set(re.findall(r"^### ([A-Z]{3}-\d{3}):", by_group[name], re.M))
        assert ids == {r.id for r in CATALOGUE if r.id.startswith(prefix)}


def test_the_summary_counts_and_lists_every_rule() -> None:
    text = render_rules_markdown()

    assert "22 rules: 7 blockers, 13 warnings, 2 info." in text
    for r in CATALOGUE:
        assert f"| {r.id} | {r.severity} | {r.title} |" in text


def test_each_rules_own_text_appears_in_its_section() -> None:
    sections = re.split(r"^### ", render_rules_markdown(), flags=re.M)[1:]

    for r, section in zip(CATALOGUE, sections, strict=True):
        assert f"- **Severity:** {r.severity}\n" in section
        assert f"- **Fires when:** {r.fires_when}\n" in section
        assert f"- **Why it matters:** {r.why_it_matters}\n" in section
        assert f"- **What to do:** {r.remediation}" in section
        for reference in r.references:
            assert f"  - {reference}" in section


def test_a_rule_without_references_says_so() -> None:
    text = render_rules_markdown([rule("DES-004")])

    assert "- **References:** none" in text and "- **References:**\n" not in text


def test_references_are_listed_under_their_rule() -> None:
    text = render_rules_markdown([rule("DES-004", references=("A paper.", "A book."))])

    assert "- **References:**\n  - A paper.\n  - A book.\n" in text


def test_the_power_notes_name_how_dunnett_is_planned() -> None:
    assert "declares `dunnett` is\n  planned with Bonferroni" in render_rules_markdown()


# --- The "fires when" texts ------------------------------------------------------------


def test_the_catalogue_has_a_fires_when_for_exactly_the_rules_it_lists() -> None:
    assert set(KEY_TERMS) == {r.id for r in CATALOGUE}


@pytest.mark.parametrize("r", CATALOGUE, ids=lambda r: r.id)
def test_a_fires_when_names_what_the_rule_reads_and_is_not_the_why(r: Rule) -> None:
    assert KEY_TERMS[r.id] in r.fires_when
    assert r.fires_when != r.why_it_matters
    assert r.fires_when.endswith(".")


def test_fires_when_texts_are_unique() -> None:
    texts = [r.fires_when for r in CATALOGUE]

    assert len(texts) == len(set(texts))


# --- The generator ---------------------------------------------------------------------


def test_a_rule_whose_prefix_has_no_group_is_refused() -> None:
    with pytest.raises(ValueError, match="XYZ-001 has no group: add 'XYZ' to GROUPS"):
        render_rules_markdown([rule("XYZ-001")])


def test_a_group_with_no_rules_is_left_out() -> None:
    text = render_rules_markdown([rule("HYP-001")])

    assert "## Hypothesis rules (HYP)" in text
    assert "## Design rules" not in text and "## Procedure rules" not in text


def test_the_catalogue_is_deterministic() -> None:
    assert render_rules_markdown() == render_rules_markdown()


def test_an_escalation_is_documented_after_the_fires_when_and_only_for_rules_that_have_one() -> (
    None
):
    escalating = rule(
        "DES-004", escalation=Escalation(to="blocker", when="it is bad.", applies=lambda e: True)
    )

    text = render_rules_markdown([escalating, rule("DES-005")])

    assert text.count("Escalates to") == 1
    lines = text.split("### DES-004")[1].split("### DES-005")[0].splitlines()
    labels = [line.split(":**")[0] for line in lines if line.startswith("- **")]
    assert labels[:3] == ["- **Severity", "- **Fires when", "- **Escalates to blocker when"]
    assert "- **Escalates to blocker when:** it is bad." in text


def test_the_committed_catalogue_documents_the_one_escalation_there_is() -> None:
    escalating = [r.id for r in CATALOGUE if r.escalation is not None]

    assert escalating == ["RES-012"]
    assert DOC.read_text(encoding="utf-8").count("Escalates to") == 1
