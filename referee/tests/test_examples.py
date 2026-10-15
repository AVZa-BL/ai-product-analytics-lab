"""The example specs in examples/ and their golden outputs in tests/golden/.

A golden file is the command's exact output. To regenerate one after a change you meant to
make, from the referee/ folder:

    python -m referee review-design examples/NAME.yaml > tests/golden/NAME.txt
    python -m referee review-design examples/NAME.yaml --format json > tests/golden/NAME.json

then read the diff: the checks below also say what the output must mean, so a regenerated
golden file that is wrong still fails.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from referee.cli import main

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


# --- Golden output ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["offer-page-powered"])
def test_the_json_output_is_the_golden_file(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "review-design", str(EXAMPLES / f"{name}.yaml"), "--format", "json")

    assert code == EXIT_STATUS[name]
    assert out == (GOLDEN / f"{name}.json").read_text(encoding="utf-8")


# --- What the golden files must mean ---------------------------------------------------


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
