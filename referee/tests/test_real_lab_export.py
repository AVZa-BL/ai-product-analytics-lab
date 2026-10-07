"""Referee against real lab output: the 5,000-player experiment, read from the committed CSVs.

The files in tests/data/hybrid_offer_page_5000 were written by DuckDB from the lab's generator
(seed 42; see PROVENANCE.md there), so these tests run on the format the lab produces and on the
planted problems the results rules will have to find, in CI and without the lab installed. The
figures are the ones the lab's readout document publishes, plus the cohort and version patterns
that design section 20.4 states.
"""

import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from referee import data
from referee.data import ExperimentData, load_export
from referee.methods import (
    cohort_heterogeneity,
    heavy_tail_measures,
    srm_test,
    welch_difference,
)

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"
EXPERIMENT = "hybrid_offer_page"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def export() -> ExperimentData:
    return load_export(FIXTURE, EXPERIMENT)


def _weeks(export: ExperimentData, *, by: str) -> dict[str, int]:
    """Weeks since the first assignment, by the week of assignment or of first exposure."""
    start = min(a.assigned_at for a in export.assignments)
    if by == "assignment":
        return {a.player_id: (a.assigned_at - start).days // 7 for a in export.assignments}
    first: dict[str, object] = {}
    for exposure in export.exposures:  # already ordered by player and time
        first.setdefault(exposure.player_id, exposure.exposed_at)
    return {player: (moment - start).days // 7 for player, moment in first.items()}


def _cohorts(export: ExperimentData, arm: str, weeks: dict[str, int]):
    """The sessions difference against control in each week, as Welch gives it."""
    arm_of = {a.player_id: a.arm for a in export.assignments}
    sessions = {o.player_id: float(o.sessions_7d) for o in export.outcomes}
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for player, week in weeks.items():
        groups[(arm_of[player], week)].append(sessions[player])
    usable = [
        w
        for w in sorted({w for _, w in groups})
        if len(groups[(arm, w)]) > 1 and len(groups[("control", w)]) > 1
    ]
    fits = [welch_difference(groups[(arm, w)], groups[("control", w)]) for w in usable]
    return usable, fits


# --- The files themselves ----------------------------------------------------------------


def test_the_files_are_the_ones_the_manifest_describes() -> None:
    assert set(MANIFEST["files"]) == {
        "experiment_assignments.csv",
        "experiment_exposures.csv",
        "experiment_outcomes.csv",
    }
    for name, expected in MANIFEST["files"].items():
        content = (FIXTURE / name).read_bytes()

        assert hashlib.sha256(content).hexdigest() == expected["sha256"], name
        assert content.count(b"\n") - 1 == expected["rows"], name
    assert MANIFEST["generator"] == {
        "scenario": "hybrid_subscription",
        "seed": 42,
        "start_date": "2026-01-01",
        "days": 180,
        "scale": 5000,
    }


def test_the_loader_reads_every_row_of_the_lab_export(export: ExperimentData) -> None:
    assert (len(export.assignments), len(export.exposures), len(export.outcomes)) == (
        2824,
        3974,
        2824,
    )
    assert data.list_experiment_ids(FIXTURE) == (EXPERIMENT,)
    assert {e.config_version for e in export.exposures} == {1, 2}


def test_the_order_of_the_rows_in_the_files_does_not_change_what_is_read(
    export: ExperimentData, tmp_path: Path
) -> None:
    rng = random.Random(3)
    for name in MANIFEST["files"]:
        lines = (FIXTURE / name).read_text(encoding="utf-8").splitlines(keepends=True)
        header, rows = lines[0], lines[1:]
        rng.shuffle(rows)
        (tmp_path / name).write_text(header + "".join(rows), encoding="utf-8")

    assert load_export(tmp_path, EXPERIMENT) == export


def test_a_cut_through_the_last_line_of_the_real_exposures_is_refused(tmp_path: Path) -> None:
    for name in MANIFEST["files"]:
        shutil.copy(FIXTURE / name, tmp_path / name)
    path = tmp_path / data.EXPOSURES_FILE
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:-1]) + "exposure_0003974,hybrid_", encoding="utf-8")

    with pytest.raises(data.DataError) as caught:
        load_export(tmp_path, EXPERIMENT)

    assert caught.value.problems == (
        "experiment_exposures.csv:3975: the file ends in the middle of a row "
        "(fewer fields than the header)",
    )
    assert data.list_experiment_ids(tmp_path) == (EXPERIMENT,)


# --- The planted problems, as the lab's readout document states them ----------------------


def test_the_sample_ratio_mismatch_is_the_published_one(export: ExperimentData) -> None:
    counts = Counter(a.arm for a in export.assignments)

    result = srm_test([counts[a] for a in sorted(counts)], [1 / 3] * 3)

    assert sorted(counts.items()) == [("control", 997), ("variant_b", 1046), ("variant_c", 781)]
    assert result.chi_square == pytest.approx(42.2387, abs=5e-5)
    assert result.p_value == pytest.approx(6.7296e-10, rel=1e-4, abs=0)
    assert result.flagged


def test_the_revenue_is_as_heavy_tailed_as_the_readout_says(export: ExperimentData) -> None:
    result = heavy_tail_measures([o.revenue_usd_7d for o in export.outcomes])

    assert round(result.excess_kurtosis) == 312
    assert (result.top_count, f"{result.top_share:.1%}") == (29, "46.8%")


def test_late_exposure_and_the_configuration_change_have_the_published_sizes(
    export: ExperimentData,
) -> None:
    first_exposure: dict[str, object] = {}
    for exposure in export.exposures:
        first_exposure.setdefault(exposure.player_id, exposure.exposed_at)
    late = [
        o.player_id
        for o in export.outcomes
        if o.first_purchase_at is not None and first_exposure[o.player_id] > o.first_purchase_at
    ]
    version_two = [a for a in export.assignments if a.arm == "variant_b" and a.config_version == 2]

    assert len(late) == 198 and f"{len(late) / 2824:.1%}" == "7.0%"
    assert len(version_two) == 445
    assert {a.config_version for a in export.assignments if a.arm != "variant_b"} == {1}


def test_the_fade_in_variant_b_is_found_and_variant_c_shows_none_by_assignment_week(
    export: ExperimentData,
) -> None:
    weeks = _weeks(export, by="assignment")

    usable, fits = _cohorts(export, "variant_b", weeks)
    fade = cohort_heterogeneity(
        [f.difference for f in fits], [f.std_error for f in fits], positions=usable
    )
    usable_c, fits_c = _cohorts(export, "variant_c", weeks)
    none = cohort_heterogeneity(
        [f.difference for f in fits_c], [f.std_error for f in fits_c], positions=usable_c
    )

    assert usable == [0, 1, 2]
    assert [round(f.difference, 3) for f in fits] == [1.519, 0.645, -0.174]
    assert [round(f.std_error, 3) for f in fits] == [0.257, 0.239, 0.260]
    assert fade.q_statistic == pytest.approx(21.52, abs=0.01) and fade.q_p_value < 1e-4
    assert fade.slope == pytest.approx(-0.847, abs=0.001)
    assert fade.slope_z_statistic == pytest.approx(-4.64, abs=0.01)
    assert none.q_statistic == pytest.approx(3.84, abs=0.01)
    assert none.q_p_value == pytest.approx(0.147, abs=0.001)


def test_by_week_of_first_exposure_the_fade_is_still_found_and_a_tiny_fourth_cohort_appears(
    export: ExperimentData,
) -> None:
    by_assignment = _weeks(export, by="assignment")
    by_exposure = _weeks(export, by="exposure")

    usable, fits = _cohorts(export, "variant_b", by_exposure)
    fade = cohort_heterogeneity(
        [f.difference for f in fits], [f.std_error for f in fits], positions=usable
    )
    sizes = Counter(by_exposure[a.player_id] for a in export.assignments if a.arm == "variant_b")

    assert sum(by_assignment[p] != by_exposure[p] for p in by_assignment) == 106
    assert usable == [0, 1, 2, 3] and sizes[3] == 3
    assert fade.q_statistic == pytest.approx(24.7, abs=0.05)
    assert fade.slope_z_statistic == pytest.approx(-4.85, abs=0.02) and fade.slope_p_value < 1e-5


def test_in_variant_b_the_week_and_the_config_version_move_together_as_section_20_says(
    export: ExperimentData,
) -> None:
    version = {a.player_id: a.config_version for a in export.assignments}
    arm = {a.player_id: a.arm for a in export.assignments}

    def table(weeks: dict[str, int]) -> dict[int, dict[int, int]]:
        counts: dict[int, Counter] = defaultdict(Counter)
        for player, week in weeks.items():
            if arm[player] == "variant_b":
                counts[week][version[player]] += 1
        return {week: dict(sorted(c.items())) for week, c in sorted(counts.items())}

    assert table(_weeks(export, by="assignment")) == {0: {1: 357}, 1: {1: 244, 2: 112}, 2: {2: 333}}
    assert table(_weeks(export, by="exposure")) == {
        0: {1: 334},
        1: {1: 261, 2: 104},
        2: {1: 6, 2: 338},
        3: {2: 3},
    }
