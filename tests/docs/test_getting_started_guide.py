import re
from pathlib import Path

import pytest

GUIDE = Path("docs/getting_started.md")
# Repo-relative paths with a committed-file extension. Generated artifacts such as
# dev.duckdb, data/raw/ and executed .ipynb files are deliberately not matched.
REFERENCED = re.compile(
    r"(?:^|[\s`(])"
    r"((?:docs|scripts|notebooks|reports|game_analytics)/[\w./-]+\.(?:sh|py|yaml|json|md))"
)


def referenced_paths() -> list[str]:
    # Collected at import time by @parametrize, so a missing guide must not abort
    # collection for the whole suite. test_guide_exists_and_names_paths reports it.
    if not GUIDE.is_file():
        return []
    return sorted(set(REFERENCED.findall(GUIDE.read_text())))


def test_guide_exists_and_names_paths() -> None:
    assert GUIDE.is_file()
    found = referenced_paths()
    assert len(found) >= 6, f"guide names suspiciously few paths: {found}"


@pytest.mark.parametrize("path", referenced_paths(), ids=lambda p: p)
def test_every_path_the_guide_names_exists(path: str) -> None:
    """Onboarding that points at a file which no longer exists is worse than none.

    Converting the subscription notebook to jupytext broke three such references at
    once, and CI caught it only because the stale file still existed in a local
    working tree while a fresh checkout had none.
    """
    assert Path(path).is_file(), f"getting_started.md references a missing path: {path}"


def test_every_scenario_has_a_gate_script_the_guide_documents() -> None:
    text = GUIDE.read_text()
    for scenario in ["live_strategy", "subscription", "hybrid_subscription"]:
        script = f"scripts/validation/run_{scenario}_checks.sh"
        assert script in text, f"guide does not document {scenario}"
        assert Path(script).is_file()


def test_readme_routes_new_readers_to_the_guide() -> None:
    assert "docs/getting_started.md" in Path("README.md").read_text()
