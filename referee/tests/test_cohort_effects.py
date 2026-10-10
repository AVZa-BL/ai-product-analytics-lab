"""The statistics of the cohort test (design sections 21.1 and 21.5)."""

import math
from pathlib import Path

import numpy as np
import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, results_spec
from scipy import stats

from referee.cohort_effects import CohortTest, cohort_test
from referee.cohorts import plan_cohorts
from referee.data import load_export
from referee.methods import cohort_heterogeneity, log_mean_ratio, welch_correction, welch_difference
from referee.results import ResultsContext

START = "2026-04-11T00:00:00Z"
SESSIONS = {
    "primary_metric__name": "sessions_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 10.0,
    "primary_metric__baseline_std": 5.0,
    "design__mde_relative": 2.0,
}
THREE_ARMS = [
    {"name": "control", "allocation": 0.4, "is_control": True},
    {"name": "variant_b", "allocation": 0.3},
    {"name": "variant_c", "allocation": 0.3},
]
FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _rows(arm: str, per_block: dict[int, list[int]], *, tag: str = "") -> list[Row]:
    """One player per session count, assigned and first exposed in the given 7-day block."""
    rows = []
    for block, sessions in per_block.items():
        for i, count in enumerate(sessions):
            rows.append(
                Row(
                    f"{arm}{tag}_{block:02d}_{i:04d}",
                    arm,
                    assigned_at=at(7 * block),
                    exposed_at=at(7 * block, 1),
                    sessions=count,
                )
            )
    return rows


def _draws(seed: int, means: dict[int, float], n: int = 80) -> dict[int, list[int]]:
    rng = np.random.default_rng(seed)
    return {block: [int(v) for v in rng.poisson(mean, n)] for block, mean in means.items()}


def _context(raw_spec, rows: list[Row], *, days: int = 28, arms=TWO_ARMS, **more):
    spec = results_spec(
        raw_spec,
        arms=arms,
        design__planned_duration_days=days,
        design__min_duration_days=7,
        design__start_utc=START,
        **{**SESSIONS, **more},
    )
    return ResultsContext.of(spec, build_data(rows))


def _run(context: ResultsContext, arm: str = "variant_b") -> CohortTest:
    plan = plan_cohorts(context, arm)
    return cohort_test(context, plan, context.metrics["sessions_7d"])


def _fade(raw_spec):
    """Four weekly cohorts; the arm's effect fades from +4 to +1 over the weeks."""
    control = _draws(1, {0: 10, 1: 10, 2: 10, 3: 10})
    arm = _draws(2, {0: 14, 1: 12.5, 2: 11, 3: 10.5})
    rows = _rows("control", control) + _rows("variant_b", arm)
    return _context(raw_spec, rows), control, arm


# --- The estimate in each cohort, on both scales ----------------------------------------------


def test_each_cohort_gets_welchs_difference_and_the_corrected_standard_error(raw_spec) -> None:
    context, control, arm = _fade(raw_spec)

    result = _run(context)

    assert (result.arm, result.control, result.metric, result.block_days) == (
        "variant_b",
        "control",
        "sessions_7d",
        7,
    )
    assert [c.block for c in result.absolute.cohorts] == [0, 1, 2, 3]
    for found in result.absolute.cohorts:
        welch = welch_difference(arm[found.block], control[found.block])
        assert found.estimate == welch.difference
        assert found.std_error == welch.std_error
        assert found.degrees_of_freedom == welch.degrees_of_freedom
        assert found.corrected_std_error == pytest.approx(
            welch.std_error * math.sqrt(welch.degrees_of_freedom / (welch.degrees_of_freedom - 2)),
            rel=1e-14,
        )
        assert found.corrected_std_error == welch.std_error * welch_correction(
            welch.degrees_of_freedom
        )
        assert (found.n_arm, found.n_control) == (80, 80)
        assert found.mean_arm == pytest.approx(np.mean(arm[found.block]), rel=1e-12)
        assert found.mean_control == pytest.approx(np.mean(control[found.block]), rel=1e-12)


def test_each_cohort_gets_the_log_ratio_of_means_on_the_relative_scale(raw_spec) -> None:
    context, control, arm = _fade(raw_spec)

    result = _run(context)

    for found in result.log_ratio.cohorts:
        ratio = log_mean_ratio(arm[found.block], control[found.block])
        assert found.estimate == ratio.log_ratio
        assert found.std_error == ratio.std_error
        assert found.corrected_std_error == ratio.std_error * welch_correction(
            ratio.degrees_of_freedom
        )
        assert found.estimate == pytest.approx(
            math.log(np.mean(arm[found.block]) / np.mean(control[found.block])), rel=1e-12
        )


def test_q_and_the_slope_are_worked_out_from_the_corrected_estimates(raw_spec) -> None:
    context, _, _ = _fade(raw_spec)

    result = _run(context)

    for scale in result.scales:
        d = np.array([c.estimate for c in scale.cohorts])
        se = np.array([c.corrected_std_error for c in scale.cohorts])
        w = 1 / se**2
        pooled = (w * d).sum() / w.sum()
        q = (w * (d - pooled) ** 2).sum()
        found = scale.heterogeneity
        assert scale.reason is None and scale.error is None and scale.dropped == ()
        assert found.q_statistic == pytest.approx(q, rel=1e-12)
        assert found.q_p_value == pytest.approx(stats.chi2.sf(q, 3), rel=1e-10, abs=0)
        assert found.cohorts == 4 and found.degrees_of_freedom == 3
    assert result.absolute.heterogeneity.slope < 0  # the effect fades
    assert result.absolute.heterogeneity.slope_p_value < 0.001


def test_the_correction_makes_q_smaller_than_the_raw_standard_errors_give(raw_spec) -> None:
    context, _, _ = _fade(raw_spec)
    scale = _run(context).absolute

    raw = cohort_heterogeneity(
        [c.estimate for c in scale.cohorts], [c.std_error for c in scale.cohorts]
    )

    assert scale.heterogeneity.q_statistic < raw.q_statistic
    ratio = raw.q_statistic / scale.heterogeneity.q_statistic
    assert ratio == pytest.approx(1 / welch_correction(2 * 79) ** 2, rel=0.05)


def test_the_slope_is_over_the_block_numbers_so_a_missing_block_leaves_a_gap(raw_spec) -> None:
    control = _draws(3, {0: 10, 1: 10, 2: 10, 3: 10}, n=80)
    arm = _draws(4, {0: 14, 1: 13, 2: 12, 3: 8}, n=80)
    arm[2] = arm[2][:20]  # block 2 cannot be used: 20 players in the arm
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    scale = _run(context).absolute

    assert [c.block for c in scale.cohorts] == [0, 1, 3]
    d = [c.estimate for c in scale.cohorts]
    se = [c.corrected_std_error for c in scale.cohorts]
    assert scale.heterogeneity.slope == cohort_heterogeneity(d, se, positions=[0, 1, 3]).slope
    assert scale.heterogeneity.slope != cohort_heterogeneity(d, se).slope


def test_only_the_arm_and_control_are_in_the_cohorts_of_a_three_arm_test(raw_spec) -> None:
    control = _draws(5, dict.fromkeys(range(4), 10))
    arm = _draws(6, dict.fromkeys(range(4), 11))
    other = _draws(7, dict.fromkeys(range(4), 30))
    rows = _rows("control", control) + _rows("variant_b", arm) + _rows("variant_c", other)
    context = _context(raw_spec, rows, arms=THREE_ARMS)

    result = _run(context, "variant_b")

    for found in result.absolute.cohorts:
        assert (found.n_arm, found.n_control) == (80, 80)
        assert found.estimate == welch_difference(arm[found.block], control[found.block]).difference
    assert _run(context, "variant_c").absolute.cohorts[0].mean_arm > 25


def test_players_who_are_not_analysed_are_not_in_a_cohort(raw_spec) -> None:
    control = _draws(8, dict.fromkeys(range(4), 10))
    arm = _draws(9, dict.fromkeys(range(4), 11))
    late = [
        Row(
            f"late_{i}",
            "variant_b",
            assigned_at=at(0),
            exposed_at=at(0, 5),
            sessions=500,
            purchases=1,
            first_purchase_at=at(0, 1),
        )
        for i in range(10)
    ]
    never = [Row(f"never_{i}", "variant_b", exposed_at=None, sessions=900) for i in range(10)]
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm) + late + never)

    first = _run(context).absolute.cohorts[0]

    assert first.n_arm == 80 and first.mean_arm == pytest.approx(np.mean(arm[0]), rel=1e-12)


# --- A cohort that cannot give an estimate is dropped, with a reason --------------------------


def _flat(value: int, n: int = 80) -> list[int]:
    return [value] * n


def test_a_cohort_with_no_variation_in_either_arm_is_dropped_on_both_scales(raw_spec) -> None:
    control = _draws(10, dict.fromkeys(range(5), 10))
    arm = _draws(11, dict.fromkeys(range(5), 12))
    control[2], arm[2] = _flat(7), _flat(9)
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm), days=35)

    result = _run(context)

    for scale in result.scales:
        assert scale.dropped == ((2, "no_variation"),)
        assert [c.block for c in scale.cohorts] == [0, 1, 3, 4]
        assert scale.reason is None and scale.heterogeneity.cohorts == 4


def test_one_arm_without_variation_is_still_a_cohort_when_the_other_varies(raw_spec) -> None:
    control = _draws(12, dict.fromkeys(range(4), 10))
    arm = _draws(13, dict.fromkeys(range(4), 12))
    arm[1] = _flat(12)
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    result = _run(context)

    assert result.absolute.dropped == () and result.log_ratio.dropped == ()
    assert [c.block for c in result.absolute.cohorts] == [0, 1, 2, 3]


def test_a_scale_left_with_fewer_than_three_cohorts_is_not_evaluated(raw_spec) -> None:
    control = _draws(14, dict.fromkeys(range(4), 10))
    arm = _draws(15, dict.fromkeys(range(4), 12))
    for block in (1, 3):
        control[block], arm[block] = _flat(7), _flat(9)
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    result = _run(context)

    for scale in result.scales:
        assert scale.reason == "no_variation" and scale.heterogeneity is None
        assert [c.block for c in scale.cohorts] == [0, 2]
        assert scale.dropped == ((1, "no_variation"), (3, "no_variation"))


def test_a_control_mean_of_zero_drops_the_cohort_from_the_log_scale_only(raw_spec) -> None:
    control = _draws(16, dict.fromkeys(range(4), 10))
    arm = _draws(17, dict.fromkeys(range(4), 12))
    control[1] = _flat(0)
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    result = _run(context)

    assert result.absolute.dropped == () and result.absolute.heterogeneity.cohorts == 4
    assert result.log_ratio.dropped == ((1, "non_positive_mean"),)
    assert [c.block for c in result.log_ratio.cohorts] == [0, 2, 3]


def test_two_non_positive_means_leave_the_log_scale_unevaluated_and_the_absolute_scale_fine(
    raw_spec,
) -> None:
    control = _draws(18, dict.fromkeys(range(4), 10))
    arm = _draws(19, dict.fromkeys(range(4), 12))
    control[1], control[3] = _flat(0), _flat(0)
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    result = _run(context)

    assert result.absolute.reason is None and result.absolute.heterogeneity is not None
    assert result.log_ratio.reason == "non_positive_mean"
    assert result.log_ratio.heterogeneity is None
    assert result.log_ratio.dropped == ((1, "non_positive_mean"), (3, "non_positive_mean"))


def test_the_commonest_reason_is_given_and_a_tie_goes_to_the_first_in_the_alphabet(
    raw_spec,
) -> None:
    control = _draws(20, dict.fromkeys(range(4), 10))
    arm = _draws(21, dict.fromkeys(range(4), 12))
    control[0], arm[0] = _flat(7), _flat(9)  # no variation
    control[1], arm[1] = _flat(7), _flat(9)  # no variation
    control[2], control[3] = _flat(0), _flat(0)  # non-positive mean
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    scale = _run(context).log_ratio

    assert sorted(reason for _, reason in scale.dropped) == [
        "no_variation",
        "no_variation",
        "non_positive_mean",
        "non_positive_mean",
    ]
    assert scale.reason == "no_variation"  # tied at 2 each; "no_variation" sorts first
    control[3] = _draws(22, {3: 10})[3]
    third = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))
    assert _run(third).log_ratio.reason == "no_variation"
    control[1] = _flat(0)  # now three non-positive means against one no-variation cohort
    fourth = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))
    assert _run(fourth).log_ratio.reason == "non_positive_mean"


def test_a_tie_is_broken_by_the_alphabet_even_when_the_later_code_was_met_first(raw_spec) -> None:
    control = _draws(25, dict.fromkeys(range(4), 10))
    arm = _draws(26, dict.fromkeys(range(4), 12))
    control[0], control[1] = _flat(0), _flat(0)  # non-positive mean, met first
    control[2], arm[2] = _flat(7), _flat(9)  # no variation
    control[3], arm[3] = _flat(7), _flat(9)  # no variation
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm))

    scale = _run(context).log_ratio

    assert [reason for _, reason in scale.dropped] == [
        "non_positive_mean",
        "non_positive_mean",
        "no_variation",
        "no_variation",
    ]
    assert scale.reason == "no_variation"


def test_values_the_statistics_cannot_handle_drop_the_cohort_as_not_estimable(raw_spec) -> None:
    control = _draws(23, dict.fromkeys(range(5), 10))
    arm = _draws(24, dict.fromkeys(range(5), 12))
    arm[2][0] = 10**400  # beyond any float: infinite for the statistics
    context = _context(raw_spec, _rows("control", control) + _rows("variant_b", arm), days=35)

    result = _run(context)

    for scale in result.scales:
        assert scale.dropped == ((2, "not_estimable"),)
        assert [c.block for c in scale.cohorts] == [0, 1, 3, 4]


def test_a_failure_of_q_itself_is_reported_not_raised(raw_spec, monkeypatch) -> None:
    from referee import cohort_effects
    from referee.methods import StatsError

    def refuse(*args, **kwargs):
        raise StatsError("the standard errors are too small or too large to weigh the cohorts")

    monkeypatch.setattr(cohort_effects, "cohort_heterogeneity", refuse)
    context, _, _ = _fade(raw_spec)

    scale = _run(context).absolute

    assert scale.heterogeneity is None and scale.reason == "not_estimable"
    assert scale.error == "the standard errors are too small or too large to weigh the cohorts"
    assert len(scale.cohorts) == 4


def test_a_plan_that_is_not_evaluated_is_refused(raw_spec) -> None:
    context = _context(
        raw_spec, _rows("control", {0: _flat(5)}) + _rows("variant_b", {0: _flat(6)})
    )
    plan = plan_cohorts(context, "variant_b")

    assert not plan.evaluated
    with pytest.raises(ValueError, match="not evaluated"):
        cohort_test(context, plan, context.metrics["sessions_7d"])


def test_the_cohort_test_is_the_same_whatever_order_the_players_arrive_in(raw_spec) -> None:
    from dataclasses import replace

    context, _, _ = _fade(raw_spec)
    reversed_players = replace(context, players=context.players[::-1])

    assert _run(reversed_players) == _run(context)


# --- The committed export ---------------------------------------------------------------------


def test_on_the_committed_export_the_fade_is_found_and_the_two_scales_agree_with_a_hand_check(
    raw_spec,
) -> None:
    spec = results_spec(
        raw_spec,
        design__planned_duration_days=21,
        **SESSIONS,
    )
    context = ResultsContext.of(spec, load_export(FIXTURE, "hybrid_offer_page"))
    metric = context.metrics["sessions_7d"]

    b = cohort_test(context, plan_cohorts(context, "variant_b"), metric)
    c = cohort_test(context, plan_cohorts(context, "variant_c"), metric)

    assert (b.block_days, c.block_days) == (7, 7)
    assert [x.block for x in b.absolute.cohorts] == [0, 1, 2]
    assert b.absolute.heterogeneity.q_statistic == pytest.approx(20.185, abs=0.0005)
    assert b.absolute.heterogeneity.q_p_value == pytest.approx(4.14e-5, rel=0.01, abs=0)
    assert c.absolute.heterogeneity.q_statistic == pytest.approx(3.631, abs=0.0005)
    assert c.absolute.heterogeneity.q_p_value == pytest.approx(0.1628, abs=0.0005)

    # An independent check of variant_b on the relative scale, from the raw sessions.
    sessions = {(p.arm, context.block_of(p.first_exposed_at, 7)): [] for p in context.analysed}
    for p in context.analysed:
        sessions[(p.arm, context.block_of(p.first_exposed_at, 7))].append(float(p.sessions_7d))
    d, se = [], []
    for block in (0, 1, 2):
        t, k = np.array(sessions[("variant_b", block)]), np.array(sessions[("control", block)])
        part = t.var(ddof=1) / (len(t) * t.mean() ** 2) + k.var(ddof=1) / (len(k) * k.mean() ** 2)
        a_part = t.var(ddof=1) / (len(t) * t.mean() ** 2)
        b_part = k.var(ddof=1) / (len(k) * k.mean() ** 2)
        dof = part**2 / (a_part**2 / (len(t) - 1) + b_part**2 / (len(k) - 1))
        d.append(math.log(t.mean() / k.mean()))
        se.append(math.sqrt(part) * math.sqrt(dof / (dof - 2)))
    w = 1 / np.array(se) ** 2
    pooled = (w * np.array(d)).sum() / w.sum()
    q = (w * (np.array(d) - pooled) ** 2).sum()
    assert b.log_ratio.heterogeneity.q_statistic == pytest.approx(q, rel=1e-10)
