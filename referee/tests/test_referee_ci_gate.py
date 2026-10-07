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


def _job(name: str) -> dict:
    return yaml.safe_load(CI.read_text())["jobs"][name]


def _python_version(job: dict) -> str:
    return job["steps"][1]["with"]["python-version"]  # the setup-python step


def test_the_linux_job_keeps_its_name_and_runner() -> None:
    """A branch-protection rule may require this exact job name, so it must not be renamed."""
    assert _job("referee-quality-gate")["runs-on"] == "ubuntu-latest"


def test_the_same_gate_runs_on_macos_as_a_job_of_its_own() -> None:
    """The statistics depend on compiled numeric libraries, so CI checks them on macOS too."""
    linux, macos = _job("referee-quality-gate"), _job("referee-quality-gate-macos")

    assert macos["runs-on"] == "macos-latest"
    assert macos["defaults"] == linux["defaults"]
    assert [s.get("run") for s in macos["steps"]] == [s.get("run") for s in linux["steps"]]
    assert [s.get("uses") for s in macos["steps"]] == [s.get("uses") for s in linux["steps"]]
    assert _python_version(macos) == _python_version(linux)
