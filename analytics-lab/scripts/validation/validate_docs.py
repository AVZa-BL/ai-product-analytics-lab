from pathlib import Path


def validate_document(path: Path, required_headings: tuple[str, ...]) -> list[str]:
    lines = path.read_text().splitlines()
    headings = {line[3:].strip() for line in lines if line.startswith("## ")}
    return [heading for heading in required_headings if heading not in headings]
