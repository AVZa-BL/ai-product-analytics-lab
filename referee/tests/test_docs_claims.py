"""What the README says must match what the code does."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from referee import cli
from referee.rules import ALL_RULES, RESULTS_RULES

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
GOLDEN = ROOT / "tests" / "golden"


def _commands() -> list[list[str]]:
    block = re.search(r"```bash\n((?:python -m referee .*\n)+)```", README)
    assert block, "the README's review-design commands were not found"
    return [line.split()[1:] for line in block.group(1).splitlines()]


# --- The README ------------------------------------------------------------------------


@pytest.mark.slow
def test_the_readme_commands_run_as_written_with_the_statuses_the_prose_promises() -> None:
    statuses = []
    for argv in _commands():
        result = subprocess.run(
            [sys.executable, *argv], capture_output=True, text=True, cwd=ROOT, check=False
        )
        statuses.append(result.returncode)
        assert result.stderr == ""

    assert statuses == [1, 0]
    assert "recommends **revise**" in README and "recommends **proceed**" in README


def test_the_readme_quotes_the_numbers_the_underpowered_review_reports() -> None:
    evidence = next(
        f["evidence"]
        for f in json.loads((GOLDEN / "offer-page-underpowered.json").read_text())["findings"]
        if f["rule_id"] == "DES-001"
    )

    assert f"{evidence['required_total']:,}" == "389,060" and "389,060 units" in README
    assert f"{evidence['achievable_total']:,}" == "58,800" and "58,800" in README
    assert f"{evidence['planned_duration_days']} days" in README
    assert "planned for 98 days" in README
    assert json.loads((GOLDEN / "offer-page-powered.json").read_text())["recommendation"] == (
        "proceed"
    )


def test_the_readme_exit_status_table_matches_the_command() -> None:
    table = README.split("| Exit status | Meaning |")[1].split("\n\n")[0]
    rows = re.findall(r"^\| (\d) \| (.+) \|$", table, re.M)

    assert [int(code) for code, _ in rows] == [
        cli.EXIT_OK,
        cli.EXIT_BLOCKED,
        cli.EXIT_UNREADABLE,
        cli.EXIT_INTERNAL,
    ]


def test_the_readme_counts_the_rules_the_catalogue_has() -> None:
    assert f"the {len(ALL_RULES)} design-review rules" in README


@pytest.mark.parametrize("document", ["README.md", "docs/rules.md"])
def test_every_relative_link_points_at_a_file_that_exists(document: str) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    links = re.findall(r"\]\((?!https?://|#)([^)\s#]+)", text)

    assert all((ROOT / document).parent.joinpath(link).exists() for link in links), links


# --- The design amendment --------------------------------------------------------------
















def test_the_readme_names_every_runtime_dependency_the_project_declares() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = declared["project"]["dependencies"]
    names = [re.match(r"[A-Za-z0-9_.-]+", requirement).group(0) for requirement in requirements]

    assert {"numpy", "pyyaml", "scipy"} <= {n.lower() for n in names}
    for name in names:
        assert name.lower() in README.lower(), f"the README does not name the dependency {name}"


def test_the_readme_names_the_results_rules_that_are_built_and_says_no_command_runs_them() -> None:
    sentence = next(line for line in README.splitlines() if "results rules built so far" in line)

    assert all(rule.id in sentence for rule in RESULTS_RULES)
    assert f"the {len(RESULTS_RULES)} results rules" not in sentence  # the ids, not a count
    assert "no command runs them yet" in sentence




# --- The small-count claims of section 21.4, recomputed -------------------------------------------


def _flag_ratio(n: int, share: float, alpha: float) -> float:
    """How many times its level the chi-square sample-ratio test flags (exact sum)."""
    import numpy as np
    from scipy.stats import binom

    from referee.methods import srm_test

    counts = np.arange(n + 1)
    flags = np.array(
        [srm_test([n - k, k], [1 - share, share], alpha=alpha).flagged for k in counts], dtype=bool
    )
    return float(binom.pmf(counts, n, share)[flags].sum() / alpha)


def _homogeneity_sizes(first: int, second: int, rate: float, alpha: float = 0.001):
    """(chi-square, exact) flag probability, in units of alpha, for two arms sharing one rate."""
    import numpy as np
    from scipy.stats import binom

    from referee import methods

    top_first, top_second = min(45, first), min(20, second)
    weight_first = binom.pmf(np.arange(top_first + 1), first, rate)
    weight_second = binom.pmf(np.arange(top_second + 1), second, rate)
    assert weight_first.sum() > 1 - 1e-12 and weight_second.sum() > 1 - 1e-12
    chi_square = exact = 0.0
    for a, weight_a in enumerate(weight_first):
        for b, weight_b in enumerate(weight_second):
            if a + b == 0:
                continue
            weight = weight_a * weight_b
            chi_square += weight * (
                methods.homogeneity_test([a, b], [first, second]).p_value < alpha
            )
            exact += weight * (methods._exact_homogeneity_p([a, b], [first, second]) < alpha)
    return chi_square / alpha, exact / alpha


def test_the_chi_square_sample_ratio_test_over_flags_small_counts_by_the_known_factors() -> None:
    assert f"{_flag_ratio(50, 0.1, 0.00025):.1f}" == "4.0"
    assert f"{_flag_ratio(100, 0.05, 0.00025):.1f}" == "5.9"
    assert f"{_flag_ratio(50, 0.1, 0.001):.1f}" == "3.2"


def test_the_homogeneity_chi_square_over_flags_and_the_exact_test_does_not() -> None:
    chi_square, exact = _homogeneity_sizes(950, 50, 0.003)
    chi_square_tiny, exact_tiny = _homogeneity_sizes(990, 10, 0.003)

    assert round(chi_square) == 14 and round(chi_square_tiny) == 29
    assert exact < 0.65 and exact_tiny < 0.65
