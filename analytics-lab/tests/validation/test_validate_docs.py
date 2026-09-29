from pathlib import Path

from scripts.validation.validate_docs import validate_document


def test_validate_document_returns_missing_headings(tmp_path: Path) -> None:
    document = tmp_path / "metric.md"
    document.write_text("# DAU\n\n## Formula\nDistinct active players.\n")
    missing = validate_document(document, ("Formula", "Grain", "Exclusions"))
    assert missing == ["Grain", "Exclusions"]


def test_validate_document_accepts_complete_document(tmp_path: Path) -> None:
    document = tmp_path / "metric.md"
    document.write_text("# DAU\n\n## Formula\nX\n## Grain\nY\n## Exclusions\nZ\n")
    assert validate_document(document, ("Formula", "Grain", "Exclusions")) == []
