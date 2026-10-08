"""docs/propose.md lists the problem codes; keep it in step with the code."""

import pytest

from tests.propose_helpers import ROOT
from tracewright.propose.check import PROBLEM_CODES, Problem

DOC = (ROOT / "docs" / "propose.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("code", sorted(PROBLEM_CODES))
def test_every_problem_code_is_documented(code):
    assert f"| `{code}` |" in DOC


def test_the_docs_list_no_code_that_does_not_exist():
    import re

    documented = set(re.findall(r"^\| `([A-Z_]+)` \|", DOC, flags=re.MULTILINE))
    assert documented == set(PROBLEM_CODES)


def test_an_unknown_code_is_refused():
    with pytest.raises(ValueError, match="unknown problem code"):
        Problem(code="TYPO", severity="info", subject="x", message="y")


def test_the_cli_help_points_to_a_file_that_exists():
    assert (ROOT / "docs" / "import-csv.md").exists()
