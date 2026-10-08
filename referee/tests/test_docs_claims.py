"""What the README and the design amendment say must match what the code does."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from scipy.stats import chi2, ncx2, norm
from test_spec_canonical import SECTION_6_SHA256

from referee import cli
from referee.rules import ALL_RULES

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs/design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
GOLDEN = ROOT / "tests" / "golden"


def _commands() -> list[list[str]]:
    block = re.search(r"```bash\n((?:python -m referee .*\n)+)```", README)
    assert block, "the README's review-design commands were not found"
    return [line.split()[1:] for line in block.group(1).splitlines()]


# --- The README ------------------------------------------------------------------------


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


def test_the_amendment_states_the_pinned_fingerprint_and_the_exit_statuses() -> None:
    assert SECTION_6_SHA256 in DESIGN
    assert "0 no blocker found, 1 at least one blocker, 2 the spec cannot be read" in DESIGN
    assert "3 a failure inside Referee" in DESIGN
    assert (cli.EXIT_OK, cli.EXIT_BLOCKED, cli.EXIT_UNREADABLE, cli.EXIT_INTERNAL) == (0, 1, 2, 3)


def test_the_design_header_points_at_every_amendment() -> None:
    header = DESIGN.split("**Scope:**")[0]

    for number in (16, 17, 18, 19, 20, 21):
        assert f"see section {number}" in header
    assert all(f"\n## {number}. Amendment" in DESIGN for number in (16, 17, 18, 19, 20, 21))


def test_the_amendment_names_the_files_it_says_exist() -> None:
    amendment = DESIGN.split("\n## 18. Amendment")[1].split("\n## 19. Amendment")[0]
    names = re.findall(r"`(referee/[\w/.\-]+)`", amendment)

    assert {"referee/examples/", "referee/tests/golden/"} <= set(names)
    for name in names:
        assert (ROOT.parent / name).exists(), name


def test_the_milestone_3_amendment_names_the_lab_files_and_incident_codes_that_exist() -> None:
    amendment = DESIGN.split("\n## 19. Amendment")[1].split("\n## 20. Amendment")[0]
    names = re.findall(r"`(analytics-lab/[\w/.\-]+)`", amendment)
    mart = (
        ROOT.parent
        / "analytics-lab/game_analytics/models/hybrid_subscription/marts"
        / "mart_hybrid_subscription__data_quality_incidents.sql"
    ).read_text(encoding="utf-8")

    assert "analytics-lab/docs/metrics/hybrid_subscription_experiment.md" in names
    for name in names:
        assert (ROOT.parent / name).exists(), name
    for code in (
        "experiment_exposure_after_purchase",
        "experiment_sample_ratio_mismatch",
        "experiment_mid_test_config_change",
    ):
        assert f"`{code}`" in amendment, f"{code} is not named in the amendment"
        assert f"when '{code}'" in mart, f"{code} is not in the mart"


def test_the_milestone_4_amendment_names_rules_and_files_that_exist_and_none_built_yet() -> None:
    amendment = DESIGN.split("\n## 20. Amendment")[1].split("\n## 21. Amendment")[0]
    rule_ids = set(re.findall(r"RES-0\d\d", amendment))
    seed_list = DESIGN.split("## 8. Rule catalogue")[1].split("## 9.")[0]
    catalogue = set(re.findall(r"RES-0\d\d", seed_list))
    names = re.findall(r"`(analytics-lab/[\w/.\-]+)`", amendment)

    assert {"RES-007", "RES-012", "RES-013"} <= rule_ids
    assert "analytics-lab/docs/architecture/hybrid_subscription_raw_contract.md" in names
    assert rule_ids - {"RES-012", "RES-013"} <= catalogue, "section 20 names a rule section 8 lacks"
    assert not {"RES-012", "RES-013"} & catalogue, "section 8 must keep the seed list as written"
    for name in [*names, *re.findall(r"`(referee/[\w/.\-]+)`", amendment)]:
        assert (ROOT.parent / name).exists(), name
    assert "referee/src/referee/data.py" in amendment
    assert "1,000 rows" in amendment and "feat/referee-results-data" in amendment
    assert not ({"RES-012", "RES-013"} & {rule.id for rule in ALL_RULES}), (
        "the results rules arrive in 4b; update this test and section 20.4 when they do"
    )


def test_the_milestone_4b_amendment_names_rules_and_files_that_exist_and_none_built_yet() -> None:
    amendment = DESIGN.split("\n## 21. Amendment")[1]
    seed_list = DESIGN.split("## 8. Rule catalogue")[1].split("## 9.")[0]
    catalogue = set(re.findall(r"(?:DES|RES)-0\d\d", seed_list))
    named = set(re.findall(r"(?:DES|RES)-0\d\d", amendment))
    new_rules = {"RES-012", "RES-013", "DES-009"}
    built = {rule.id for rule in ALL_RULES}

    assert {"RES-001", "RES-002", "RES-003", "RES-004", "RES-007", "RES-008"} <= named
    assert {"RES-011", "RES-012", "RES-013", "DES-009"} <= named
    assert named - new_rules <= catalogue, "section 21 names a rule section 8 lacks"
    assert not new_rules & catalogue, "section 8 must keep the seed list as written"
    for name in re.findall(r"`((?:referee|analytics-lab)/[\w/.\-]+)`", amendment):
        assert (ROOT.parent / name).exists(), name
    for branch in ("feat/referee-results-data-fit", "feat/referee-results-effect"):
        assert branch in amendment
    assert not new_rules & built and not any(rule_id.startswith("RES-") for rule_id in built), (
        "the results rules arrive in 4b-1 and 4b-2; update this test and section 21 when they do"
    )


def test_the_milestone_4b_amendment_quotes_the_numbers_the_code_reproduces() -> None:
    amendment = DESIGN.split("\n## 21. Amendment")[1]
    shift = norm.ppf(0.975) + norm.ppf(0.8)  # the slope test's 80%-power point, in standard errors
    powers = [
        100 * ncx2.sf(chi2.ppf(0.95, cohorts - 1), cohorts - 1, shift**2)
        for cohorts in (3, 4, 6, 8, 12)
    ]
    quoted = ", ".join(f"{p:.1f}%" for p in powers[:-1]) + f" and {powers[-1]:.1f}%"
    generator = (
        ROOT.parent / "analytics-lab/src/analytics_lab/generation/hybrid_subscription.py"
    ).read_text(encoding="utf-8")
    provenance = (ROOT / "tests/data/hybrid_offer_page_5000/PROVENANCE.md").read_text(
        encoding="utf-8"
    )

    assert quoted in amendment
    # The fixture figures are pinned by tests/test_real_lab_export.py; the text must match them.
    for figure in ("19.86", "19.92", "Q = 3.77", "p = 0.34, 4.0e-5 and 2.6e-8", "p = 6.7e-10"):
        assert figure in amendment, figure
    for figure in ("198 players (7.0%)", "7.1%, 7.4% and 6.4%", "p = 0.72", "445", "11 have"):
        assert figure in amendment, figure
    # The new-user caveat rests on how the lab's generator places players in time.
    assert 'pd.to_timedelta(120, unit="D")' in generator
    assert 'pd.to_timedelta(30, unit="D")' in generator
    assert "--start-date 2026-01-01" in provenance
    assert "2026-04-11" in amendment and "2026-01-01" in amendment


def test_the_readme_names_every_runtime_dependency_the_project_declares() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = declared["project"]["dependencies"]
    names = [re.match(r"[A-Za-z0-9_.-]+", requirement).group(0) for requirement in requirements]

    assert {"numpy", "pyyaml", "scipy"} <= {n.lower() for n in names}
    for name in names:
        assert name.lower() in README.lower(), f"the README does not name the dependency {name}"
