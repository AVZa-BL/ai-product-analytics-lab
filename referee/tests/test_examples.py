"""The example specs in examples/ and their golden outputs in tests/golden/.

A golden file is the command's exact output. To regenerate one after a change you meant to
make, from the referee/ folder:

    python -m referee review-design examples/NAME.yaml > tests/golden/NAME.txt
    python -m referee review-design examples/NAME.yaml --format json > tests/golden/NAME.json

then read the diff: the checks below also say what the output must mean, so a regenerated
golden file that is wrong still fails.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from referee.cli import main
from referee.loader import load_spec
from referee.review import review_design
from referee.rules import ReviewContext
from referee.spec import ExperimentSpec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"

EXIT_STATUS = {"offer-page-underpowered": 1, "offer-page-powered": 0}
NAMES = sorted(EXIT_STATUS)

# What the powered example changes, and nothing else, compared with the underpowered one.
DIFFERENCES = {
    "id",
    "title",
    "population.exposure_timing",
    "population.interference",
    "design.planned_duration_days",
    "design.pre_period_covariate",
    "procedure.stopping_rule",
    "procedure.srm_check_cadence",
    "procedure.bucketing_salt",
}


def _paths(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        flat: dict[str, object] = {}
        for key, item in value.items():
            flat.update(_paths(item, f"{prefix}{key}."))
        return flat
    return {prefix.rstrip("."): value}


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- The folders agree -----------------------------------------------------------------


def test_every_example_has_both_golden_files_and_nothing_is_left_over() -> None:
    assert sorted(path.stem for path in EXAMPLES.glob("*.yaml")) == NAMES
    assert sorted(path.name for path in GOLDEN.iterdir()) == sorted(
        f"{name}.{kind}" for name in NAMES for kind in ("txt", "json")
    )


# --- Golden output ---------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_text_output_is_the_golden_file(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "review-design", str(EXAMPLES / f"{name}.yaml"))

    assert code == EXIT_STATUS[name]
    assert out == (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_the_json_output_is_the_golden_file(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "review-design", str(EXAMPLES / f"{name}.yaml"), "--format", "json")

    assert code == EXIT_STATUS[name]
    assert out == (GOLDEN / f"{name}.json").read_text(encoding="utf-8")


# --- What the golden files must mean ---------------------------------------------------


def test_the_underpowered_example_is_blocked_for_the_reasons_the_design_gives() -> None:
    report = json.loads((GOLDEN / "offer-page-underpowered.json").read_text(encoding="utf-8"))
    des_001 = next(f for f in report["findings"] if f["rule_id"] == "DES-001")

    assert report["recommendation"] == "revise"
    assert report["blocking_rule_ids"] == ["DES-001", "PRO-001"]
    assert report["counts"] == {"blocker": 2, "warning": 3, "info": 1}
    # Design section 17.4: it needs 389,060 units and its 14 days deliver 58,800.
    assert des_001["evidence"]["required_total"] == 389_060
    assert des_001["evidence"]["achievable_total"] == 58_800
    assert des_001["evidence"]["required_days_whole_weeks"] == 98


def test_the_powered_example_gets_a_clean_proceed() -> None:
    report = json.loads((GOLDEN / "offer-page-powered.json").read_text(encoding="utf-8"))

    assert report["recommendation"] == "proceed"
    assert report["blocking_rule_ids"] == []
    assert report["findings"] == []


def test_the_underpowered_example_is_the_design_example_whatever_its_layout(
    raw_spec: dict,
) -> None:
    """Comments and flow style in the file do not change the fingerprint of section 6."""
    example = load_spec(EXAMPLES / "offer-page-underpowered.yaml")

    assert example.sha256() == ExperimentSpec.from_dict(raw_spec).sha256()


def test_the_powered_example_differs_from_the_underpowered_one_only_as_documented() -> None:
    before = _paths(load_spec(EXAMPLES / "offer-page-underpowered.yaml").to_dict())
    after = _paths(load_spec(EXAMPLES / "offer-page-powered.yaml").to_dict())

    changed = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}

    assert changed == DIFFERENCES
    assert after["design.planned_duration_days"] == 98


def test_the_powered_example_really_is_powered_by_the_margin_its_comments_state() -> None:
    plan = ReviewContext.of(load_spec(EXAMPLES / "offer-page-powered.yaml")).plan

    assert plan is not None and plan.is_powered
    assert (plan.required_total, plan.achievable_total) == (389_060, 411_600)


@pytest.mark.parametrize("name", NAMES)
def test_an_example_reviews_the_same_when_loaded_and_reviewed_directly(name: str) -> None:
    review = review_design(load_spec(EXAMPLES / f"{name}.yaml"))

    assert (review.recommendation == "revise") == (EXIT_STATUS[name] == 1)


# --- As a user would run it ------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_command_in_each_examples_header_gives_the_golden_text(name: str) -> None:
    """Run from the referee/ folder with a relative path, exactly as the header says."""
    result = subprocess.run(
        [sys.executable, "-m", "referee", "review-design", f"examples/{name}.yaml"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == EXIT_STATUS[name]
    assert result.stdout == (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
    assert result.stderr == ""
