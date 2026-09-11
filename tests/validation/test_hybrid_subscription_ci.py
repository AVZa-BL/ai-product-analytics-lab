import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_hybrid_validation_script_generates_fixture_and_builds_full_selector(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    shim = bin_dir / "command-shim"
    shim.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$0 $*" >> "$COMMAND_LOG"\n')
    shim.chmod(0o755)
    for command in ("python", "dbt"):
        (bin_dir / command).symlink_to(shim)

    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}", "COMMAND_LOG": str(log)}
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts/validation/run_hybrid_subscription_checks.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    commands = log.read_text().splitlines()
    assert any(
        "-m analytics_lab.generate --scenario hybrid_subscription --seed 42 "
        "--start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw" in line
        for line in commands
    )
    assert any("parse --profiles-dir . --no-partial-parse" in line for line in commands)
    assert any(
        "build --selector hybrid_subscription --profiles-dir ." in line for line in commands
    )


def test_ci_runs_hybrid_validation_job():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    assert "hybrid-subscription-quality-gate" in jobs
    run_commands = [
        step.get("run", "") for step in jobs["hybrid-subscription-quality-gate"]["steps"]
    ]
    assert "bash scripts/validation/run_hybrid_subscription_checks.sh" in run_commands
