from pathlib import Path

import pytest

from scripts.validation.validate_docs import validate_document

TEMPLATE = Path("docs/templates/decision-memo.md")
MEMOS = [
    Path("reports/live_strategy/d7_retention_diagnostic.md"),
    Path("reports/subscription/trial_to_paid_decision_memo.md"),
    Path("reports/hybrid_subscription/engagement_cannibalization_decision_memo.md"),
]


def required_headings() -> tuple[str, ...]:
    """The template is the single source of truth for what a memo must carry."""
    return tuple(
        line[3:].strip()
        for line in TEMPLATE.read_text().splitlines()
        if line.startswith("## ")
    )


def test_template_declares_the_required_sections() -> None:
    assert required_headings() == (
        "Decision",
        "Observed facts",
        "Assumptions and uncertainty",
        "Data-quality qualification",
        "Reproducibility",
    )


@pytest.mark.parametrize("memo", MEMOS, ids=lambda path: path.parent.name)
def test_every_decision_memo_satisfies_the_template(memo: Path) -> None:
    missing = validate_document(memo, required_headings())
    assert missing == [], f"{memo} is missing {missing}"


def test_validator_detects_a_dropped_section(tmp_path: Path) -> None:
    """Guard the guard: a memo that drops sections must be reported, not passed."""
    partial = tmp_path / "memo.md"
    partial.write_text("# Memo\n\n## Decision\n\nShip it.\n")
    assert validate_document(partial, required_headings()) == [
        "Observed facts",
        "Assumptions and uncertainty",
        "Data-quality qualification",
        "Reproducibility",
    ]
