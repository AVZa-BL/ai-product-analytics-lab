import json
import subprocess
import sys
from pathlib import Path

import pytest

from tracewright.cli import main
from tracewright.loader import load_plan
from tracewright.report import plan_report, render_json, render_text
from tracewright.review import review_plan

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"
NAMES = ["checkout-funnel-flawed", "checkout-funnel-clean"]


@pytest.mark.parametrize("name", NAMES)
def test_reports_match_the_golden_files(name):
    plan = load_plan(EXAMPLES / f"{name}.yaml")
    report = plan_report(plan, review_plan(plan))
    assert render_text(report) == (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
    assert render_json(report) == (GOLDEN / f"{name}.json").read_text(encoding="utf-8")


def test_exit_codes(capsys, tmp_path):
    assert main(["review-plan", str(EXAMPLES / "checkout-funnel-clean.yaml")]) == 0
    assert main(["review-plan", str(EXAMPLES / "checkout-funnel-flawed.yaml")]) == 1
    assert main(["review-plan", str(tmp_path / "missing.yaml")]) == 2
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("id: p\n", encoding="utf-8")
    assert main(["review-plan", str(invalid)]) == 2
    assert main([]) == 2  # usage error
    assert "violation" in capsys.readouterr().err


def test_json_output_is_valid_and_deterministic(capsys):
    path = str(EXAMPLES / "checkout-funnel-flawed.yaml")
    main(["review-plan", path, "--format", "json"])
    first = capsys.readouterr().out
    main(["review-plan", path, "--format", "json"])
    assert capsys.readouterr().out == first
    assert json.loads(first)["recommendation"] == "revise"


def test_an_internal_failure_is_exit_3_not_1(monkeypatch, capsys):
    def boom(_path):
        raise RuntimeError("bug")

    monkeypatch.setattr("tracewright.cli.load_plan", boom)
    assert main(["review-plan", "x.yaml"]) == 3
    assert "internal error" in capsys.readouterr().err


def test_python_dash_m_works():
    result = subprocess.run(
        [sys.executable, "-m", "tracewright", "--version"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0
    assert result.stdout.startswith("tracewright ")
