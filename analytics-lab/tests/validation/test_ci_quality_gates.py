import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
SCENARIOS = ("live_strategy", "subscription", "hybrid_subscription")


class _DuplicateKeyLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently keeping the last one."""


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


@pytest.mark.parametrize(
    "workflow",
    sorted((ROOT / ".github/workflows").glob("*.yml")),
    ids=lambda path: path.name,
)
def test_workflow_has_no_duplicate_keys(workflow: Path) -> None:
    """GitHub Actions rejects a duplicate key and then runs no jobs at all.

    Two independent single-purpose edits can each add the same top-level key at
    different offsets and merge without a Git conflict, so the check has to be
    explicit rather than left to review.
    """
    yaml.load(workflow.read_text(), _DuplicateKeyLoader)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_script_generates_fixture_then_builds_isolated_selector(
    scenario: str, tmp_path: Path
) -> None:
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
        ["bash", str(ROOT / f"scripts/validation/run_{scenario}_checks.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    commands = log.read_text().splitlines()
    expected = [
        f"-m analytics_lab.generate --scenario {scenario} --seed 42 "
        "--start-date 2026-01-01 --days 180 --scale 1000 --output-dir data/raw",
        "deps --profiles-dir .",
        "parse --profiles-dir . --no-partial-parse",
        # cautious indirect selection is what keeps another scenario's singular
        # tests from entering this build through the shared calendar model.
        f"build --selector {scenario} --indirect-selection cautious --profiles-dir .",
    ]
    positions = [
        next(i for i, line in enumerate(commands) if fragment in line)
        for fragment in expected
    ]
    assert positions == sorted(positions)


def test_scenario_script_rejects_an_unknown_scenario() -> None:
    completed = subprocess.run(
        ["bash", str(ROOT / "scripts/validation/run_scenario_checks.sh"), "not_a_scenario"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "unknown scenario" in completed.stderr


def test_ci_gates_every_scenario() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["scenario-quality-gate"]
    assert sorted(job["strategy"]["matrix"]["scenario"]) == sorted(SCENARIOS)
    run_commands = [step.get("run", "") for step in job["steps"]]
    assert "bash scripts/validation/run_${{ matrix.scenario }}_checks.sh" in run_commands


def test_ci_runs_the_shared_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    run_commands = [
        step.get("run", "") for step in workflow["jobs"]["shared-quality-gate"]["steps"]
    ]
    assert "bash scripts/validation/run_shared_checks.sh" in run_commands
