from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]  # referee/, the project this suite tests
CI = ROOT.parent / ".github" / "workflows" / "ci.yml"


def _referee_job() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]["referee-quality-gate"]


def test_ci_runs_referee_from_its_own_folder() -> None:
    """The gates are relative to the project, so the job must start inside it.

    The workflow defaults to the lab's folder; this job overrides that. Tying the
    override to this folder's name means a rename that misses CI fails here instead of
    as a confusing "No such file".
    """
    assert _referee_job()["defaults"]["run"]["working-directory"] == ROOT.name


def test_ci_lints_and_tests_referee() -> None:
    """A missing job raises KeyError, so CI silently dropping Referee cannot pass."""
    commands = [step.get("run", "") for step in _referee_job()["steps"]]
    assert "ruff check src tests" in commands
    assert "python -m pytest -q" in commands
