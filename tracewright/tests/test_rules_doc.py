"""docs/rules.md is generated from the rule code, and must never drift from it."""

from pathlib import Path

from tracewright.rules import ALL_RULES
from tracewright.rules.docs import render_rules_markdown

DOC = Path(__file__).resolve().parent.parent / "docs" / "rules.md"


def test_the_committed_catalogue_is_what_the_rules_generate():
    assert DOC.read_text(encoding="utf-8") == render_rules_markdown(), (
        "docs/rules.md has drifted from the rule code. From tracewright/, run: "
        "python -m tracewright.rules.docs > docs/rules.md"
    )


def test_every_rule_appears_in_the_catalogue():
    text = render_rules_markdown()
    assert all(f"### {rule.id}:" in text for rule in ALL_RULES)
