"""The command: its outputs on the examples (golden files) and its exit statuses.

A golden file is the command's exact output. To regenerate one after a change you meant to make,
from the specwright/ folder:

    python -m specwright draft --doc examples/briefs/BRIEF.md \\
        --replay examples/replays/REPLAY.json --out tests/golden/CASE --force

then read the diff. The replays are written by hand; they are not model output.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from referee.loader import load_spec
from referee.review import review_design

from specwright import cli
from specwright.cli import main
from tests.helpers import BRIEFS, REPLAYS, ROOT, SHOP

GOLDEN = ROOT / "tests" / "golden"
CASES = [
    # case, brief, replay, exit status, the spec-like file written, Referee's recommendation
    ("shop-banner", "01-shop-banner", "01-shop-banner", 0, "draft-spec.yaml", "proceed"),
    (
        "shop-banner-repaired",
        "01-shop-banner",
        "01-shop-banner.repair",
        0,
        "draft-spec.yaml",
        "proceed",
    ),
    (
        "infeasible",
        "02-infeasible-niche-event",
        "02-infeasible-niche-event",
        6,
        "draft-spec.yaml",
        "revise",
    ),
    (
        "missing-baseline",
        "03-missing-baseline",
        "03-missing-baseline",
        5,
        "partial-draft.yaml",
        None,
    ),
    (
        "ambiguous-numbers",
        "04-ambiguous-numbers",
        "04-ambiguous-numbers",
        5,
        "partial-draft.yaml",
        None,
    ),
    (
        "buried-in-design-doc",
        "05-buried-in-design-doc",
        "05-buried-in-design-doc",
        0,
        "draft-spec.yaml",
        "proceed",
    ),
    (
        "three-arms",
        "06-three-arms-guardrails",
        "06-three-arms-guardrails",
        0,
        "draft-spec.yaml",
        "proceed",
    ),
    (
        "size-differs",
        "08-stated-size-differs",
        "08-stated-size-differs",
        0,
        "draft-spec.yaml",
        "proceed",
    ),
]


def draft(capsys, *argv: str) -> tuple[int, str]:
    code = main(["draft", *argv])
    return code, capsys.readouterr().err


@pytest.mark.parametrize(
    ("case", "brief", "replay", "status", "spec_file", "recommendation"), CASES
)
def test_the_command_writes_the_golden_files_and_the_status_for_each_example(
    capsys, tmp_path: Path, case, brief, replay, status, spec_file, recommendation
) -> None:
    out = tmp_path / "out"

    code, _ = draft(
        capsys,
        "--doc",
        str(BRIEFS / f"{brief}.md"),
        "--replay",
        str(REPLAYS / f"{replay}.json"),
        "--out",
        str(out),
    )

    assert code == status
    expected = sorted(p.name for p in (GOLDEN / case).iterdir())
    assert sorted(p.name for p in out.iterdir()) == expected
    for name in expected:
        assert (out / name).read_text(encoding="utf-8") == (GOLDEN / case / name).read_text(
            encoding="utf-8"
        ), name
    if (
        recommendation
    ):  # the spec file is one that Referee reads and reviews the way the report says
        assert review_design(load_spec(out / spec_file)).recommendation == recommendation


def test_a_missing_baseline_gives_a_partial_draft_with_the_question_and_no_invented_value(
    tmp_path: Path,
) -> None:
    text = (GOLDEN / "missing-baseline" / "partial-draft.yaml").read_text(encoding="utf-8")

    assert "# QUESTION primary_metric.baseline:" in text
    assert "baseline" not in text.split("primary_metric:")[1].split("design:")[0]


def test_the_report_of_every_example_says_that_passing_proves_consistency_not_design() -> None:
    for report in GOLDEN.glob("*/report.md"):
        text = report.read_text(encoding="utf-8")
        assert "does not prove the experiment is well designed" in text, report
        assert "not that the model read them correctly" in text, report


def run_all(capsys, tmp_path: Path, *extra: str) -> tuple[int, str]:
    return draft(
        capsys,
        "--doc",
        str(BRIEFS / f"{SHOP}.md"),
        "--replay",
        str(REPLAYS / f"{SHOP}.json"),
        "--out",
        str(tmp_path / "out"),
        *extra,
    )


def test_results_are_not_overwritten_without_force_and_force_leaves_only_the_latest_run(
    capsys, tmp_path: Path
) -> None:
    assert run_all(capsys, tmp_path)[0] == 0
    code, err = run_all(capsys, tmp_path)
    assert code == 2 and "use --force" in err

    # a later run with a different status leaves none of the earlier run's other files
    code, _ = draft(
        capsys,
        "--doc",
        str(BRIEFS / "03-missing-baseline.md"),
        "--replay",
        str(REPLAYS / "03-missing-baseline.json"),
        "--out",
        str(tmp_path / "out"),
        "--force",
    )
    assert code == 5
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "draft.json",
        "partial-draft.yaml",
        "report.md",
    ]


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        (["--doc", "nowhere.md"], "nowhere.md"),
        (["--doc", str(BRIEFS / f"{SHOP}.md"), "--max-repairs", "9"], "--max-repairs"),
        (["--doc", str(BRIEFS / f"{SHOP}.md"), "--doc", str(BRIEFS / f"{SHOP}.md")], "named"),
    ],
)
def test_an_input_that_cannot_be_used_is_status_2_and_nothing_is_written(
    capsys, tmp_path: Path, argv: list[str], fragment: str
) -> None:
    code, err = draft(
        capsys, *argv, "--replay", str(REPLAYS / f"{SHOP}.json"), "--out", str(tmp_path / "out")
    )

    assert code == 2 and fragment in err and not (tmp_path / "out").exists()


def test_a_replay_that_runs_out_is_status_4_and_without_credentials_the_model_path_is_too(
    capsys, tmp_path: Path
) -> None:
    bad = tmp_path / "replay.json"
    shutil.copy(REPLAYS / "01-shop-banner.repair.json", bad)
    data = json.loads(bad.read_text())[:1]
    bad.write_text(json.dumps(data))
    code, err = draft(
        capsys,
        "--doc",
        str(BRIEFS / f"{SHOP}.md"),
        "--replay",
        str(bad),
        "--out",
        str(tmp_path / "a"),
    )
    assert code == 4 and "replay has only 1" in err

    code, err = draft(capsys, "--doc", str(BRIEFS / f"{SHOP}.md"), "--out", str(tmp_path / "b"))
    assert code == 4 and "no credentials" in err and not (tmp_path / "b").exists()


def test_a_bug_in_specwright_is_status_3_not_a_bad_input(
    capsys, tmp_path: Path, monkeypatch
) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_draft", boom)

    code, err = run_all(capsys, tmp_path)

    assert code == 3 and "internal error: RuntimeError: boom" in err


def test_progress_is_printed_as_each_attempt_finishes(capsys, tmp_path: Path) -> None:
    code, err = draft(
        capsys,
        "--doc",
        str(BRIEFS / f"{SHOP}.md"),
        "--replay",
        str(REPLAYS / f"{SHOP}.repair.json"),
        "--out",
        str(tmp_path / "out"),
    )

    assert (
        code == 0
        and "attempt 1: 4 problem(s) to repair" in err
        and "attempt 2: 0 problem(s)" in err
    )
