"""Referee against real lab output: the 5,000-player experiment, read from the committed CSVs.

The files in tests/data/hybrid_offer_page_5000 were written by DuckDB from the lab's generator
(seed 42; see PROVENANCE.md there), so these tests run on the format the lab produces and on the
planted problems the results rules will have to find, in CI and without the lab installed. The
figures are the ones the lab's readout document publishes, plus the cohort and version patterns
that design section 20.4 states.
"""

import hashlib
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import pytest
from results_helpers import results_spec
from scipy.stats import chi2_contingency

from referee import data
from referee.data import ExperimentData, load_export
from referee.methods import (
    cohort_heterogeneity,
    heavy_tail_measures,
    srm_test,
    welch_difference,
)
from referee.results import ResultsContext

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


def _cohorts(export: ExperimentData, arm: str, weeks: dict[str, int], *, floor: int = 2):
    """The sessions difference against control in each week, as Welch gives it.

    A week is used when both the arm and control hold at least `floor` players in it.
    """
    arm_of = {a.player_id: a.arm for a in export.assignments}
    sessions = {o.player_id: float(o.sessions_7d) for o in export.outcomes}
    groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for player, week in weeks.items():
        groups[(arm_of[player], week)].append(sessions[player])
    usable = [
        w
        for w in sorted({w for _, w in groups})
        if len(groups[(arm, w)]) >= floor and len(groups[("control", w)]) >= floor
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


# --- What section 21 (Amendment 6) quotes from this export ---------------------------------


def test_with_a_floor_of_30_week_3_goes_and_the_corrected_statistics_are_the_ones_section_21_quotes(
    export: ExperimentData,
) -> None:
    weeks = _weeks(export, by="exposure")

    def heterogeneity(arm: str, *, corrected: bool):
        usable, fits = _cohorts(export, arm, weeks, floor=30)
        errors = [
            f.std_error * math.sqrt(f.degrees_of_freedom / (f.degrees_of_freedom - 2))
            if corrected
            else f.std_error
            for f in fits
        ]
        return usable, cohort_heterogeneity([f.difference for f in fits], errors, positions=usable)

    usable_b, b_corrected = heterogeneity("variant_b", corrected=True)
    _, b_raw = heterogeneity("variant_b", corrected=False)
    usable_c, c_corrected = heterogeneity("variant_c", corrected=True)

    assert usable_b == usable_c == [0, 1, 2]
    assert b_corrected.q_statistic == pytest.approx(19.86, abs=0.005)
    assert b_corrected.q_p_value == pytest.approx(4.9e-5, rel=0.02, abs=0)
    assert b_raw.q_statistic == pytest.approx(19.92, abs=0.005)
    assert c_corrected.q_statistic == pytest.approx(3.77, abs=0.005)
    assert c_corrected.q_p_value == pytest.approx(0.15, abs=0.005)


def test_on_the_effect_population_week_3_is_empty_and_q_is_the_one_section_21_quotes_for_it(
    export: ExperimentData, raw_spec
) -> None:
    spec = results_spec(
        raw_spec,
        primary_metric__name="sessions_7d",
        primary_metric__kind="continuous",
        primary_metric__baseline=10.0,
        primary_metric__baseline_std=5.0,
    )
    context = ResultsContext.of(spec, export)
    metric = context.metrics["sessions_7d"]
    sessions: dict[tuple[str, int], list[float]] = defaultdict(list)
    for player in context.analysed:
        sessions[(player.arm, context.week_of(player.first_exposed_at))].append(
            metric.value(player)
        )

    def corrected_q(arm: str):
        weeks = [w for w in range(3) if min(len(sessions[(a, w)]) for a in (arm, "control")) >= 30]
        fits = [welch_difference(sessions[(arm, w)], sessions[("control", w)]) for w in weeks]
        errors = [
            f.std_error * math.sqrt(f.degrees_of_freedom / (f.degrees_of_freedom - 2)) for f in fits
        ]
        return weeks, cohort_heterogeneity([f.difference for f in fits], errors, positions=weeks)

    weeks_b, b = corrected_q("variant_b")
    weeks_c, c = corrected_q("variant_c")

    assert not any(week >= 3 for _, week in sessions), "the 3 + 13 players of week 3 are all late"
    assert weeks_b == weeks_c == [0, 1, 2]
    assert b.q_statistic == pytest.approx(20.19, abs=0.005)
    assert b.q_p_value == pytest.approx(4.1e-5, rel=0.02, abs=0)
    assert c.q_statistic == pytest.approx(3.63, abs=0.005)
    assert c.q_p_value == pytest.approx(0.16, abs=0.005)


def test_the_sample_ratio_fails_in_the_second_and_third_week_of_assignment_but_not_the_first(
    export: ExperimentData,
) -> None:
    arms = ("control", "variant_b", "variant_c")
    start = min(a.assigned_at for a in export.assignments)
    counts: dict[int, Counter] = defaultdict(Counter)
    for a in export.assignments:
        counts[(a.assigned_at - start).days // 7][a.arm] += 1
    equal = [1 / 3] * 3

    p_values = {
        week: srm_test([c[arm] for arm in arms], equal).p_value
        for week, c in sorted(counts.items())
    }
    total = srm_test([sum(c[arm] for c in counts.values()) for arm in arms], equal)

    assert list(p_values) == [0, 1, 2]
    assert p_values[0] == pytest.approx(0.34, abs=0.005)
    assert p_values[1] == pytest.approx(4.0e-5, rel=0.01, abs=0)
    assert p_values[2] == pytest.approx(2.6e-8, rel=0.02, abs=0)
    assert total.p_value == pytest.approx(6.7e-10, rel=0.01, abs=0)
    assert [week for week, p in p_values.items() if p < 0.001 / 3] == [1, 2]  # RES-011's level


def test_late_exposure_is_even_across_the_arms_and_the_first_assignment_is_on_april_11th(
    export: ExperimentData,
) -> None:
    arms = ("control", "variant_b", "variant_c")
    arm_of = {a.player_id: a.arm for a in export.assignments}
    assigned = Counter(arm_of.values())
    first_exposure: dict[str, object] = {}
    for exposure in export.exposures:
        first_exposure.setdefault(exposure.player_id, exposure.exposed_at)
    late = Counter(
        arm_of[o.player_id]
        for o in export.outcomes
        if o.first_purchase_at is not None and first_exposure[o.player_id] > o.first_purchase_at
    )

    _, p_value, *_ = chi2_contingency([[late[a], assigned[a] - late[a]] for a in arms])

    assert [late[a] for a in arms] == [71, 77, 50]
    assert [f"{late[a] / assigned[a]:.1%}" for a in arms] == ["7.1%", "7.4%", "6.4%"]
    assert p_value == pytest.approx(0.72, abs=0.005)
    assert min(a.assigned_at for a in export.assignments).date().isoformat() == "2026-04-11"


def test_eleven_variant_b_players_were_first_exposed_on_a_different_version_than_assigned(
    export: ExperimentData,
) -> None:
    assigned_version = {a.player_id: (a.arm, a.config_version) for a in export.assignments}
    first_exposure: dict[str, object] = {}
    for exposure in export.exposures:
        first_exposure.setdefault(exposure.player_id, exposure)
    differs = Counter(
        assigned_version[player][0]
        for player, exposure in first_exposure.items()
        if exposure.config_version is not None
        and exposure.config_version != assigned_version[player][1]
    )

    assert differs == Counter({"variant_b": 11})


def test_every_outcome_window_is_the_seven_days_after_the_assignment_and_no_export_time_is_given(
    export: ExperimentData,
) -> None:
    assigned = {a.player_id: a.assigned_at for a in export.assignments}

    assert all(o.window_end == assigned[o.player_id] + timedelta(days=7) for o in export.outcomes)
    assert max(o.window_end for o in export.outcomes) == max(assigned.values()) + timedelta(days=7)
    assert export.exported_at is None  # the lab's manifest does not say when it was written
