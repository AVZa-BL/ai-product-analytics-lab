"""The statistics of the cohort test (design sections 21.1 and 21.5)."""

import itertools
import math
from pathlib import Path

import numpy as np
import pytest
from cohort_helpers import (
    SESSIONS,
    START,
    THREE_ARMS,
    cohort_context,
    cohort_draws,
    cohort_rows,
)
from results_helpers import TWO_ARMS, Row, at, build_data, results_spec
from scipy import stats

from referee.cohort_effects import (
    TRIGGER_LEVEL,
    CohortTest,
    ControlBaseline,
    ScaleTest,
    Trigger,
    cohort_test,
    control_baseline,
    detectable_shifts,
    low_information,
    min_expected_events,
    registered_mde,
    shows_heterogeneity,
    trigger,
)
from referee.cohorts import plan_cohorts
from referee.data import load_export
from referee.methods import (
    cohort_detectable_shift,
    cohort_heterogeneity,
    log_mean_ratio,
    welch_correction,
    welch_difference,
)
from referee.results import ResultsContext

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _run(context: ResultsContext, arm: str = "variant_b") -> CohortTest:
    plan = plan_cohorts(context, arm)
    return cohort_test(context, plan, context.metrics["sessions_7d"])


def _fade(raw_spec):
    """Four weekly cohorts; the arm's effect fades from +4 to +1 over the weeks."""
    control = cohort_draws(1, {0: 10, 1: 10, 2: 10, 3: 10})
    arm = cohort_draws(2, {0: 14, 1: 12.5, 2: 11, 3: 10.5})
    rows = cohort_rows("control", control) + cohort_rows("variant_b", arm)
    return cohort_context(raw_spec, rows), control, arm


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
    control = cohort_draws(3, {0: 10, 1: 10, 2: 10, 3: 10}, n=80)
    arm = cohort_draws(4, {0: 14, 1: 13, 2: 12, 3: 8}, n=80)
    arm[2] = arm[2][:20]  # block 2 cannot be used: 20 players in the arm
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    scale = _run(context).absolute

    assert [c.block for c in scale.cohorts] == [0, 1, 3]
    d = [c.estimate for c in scale.cohorts]
    se = [c.corrected_std_error for c in scale.cohorts]
    assert scale.heterogeneity.slope == cohort_heterogeneity(d, se, positions=[0, 1, 3]).slope
    assert scale.heterogeneity.slope != cohort_heterogeneity(d, se).slope


def test_only_the_arm_and_control_are_in_the_cohorts_of_a_three_arm_test(raw_spec) -> None:
    control = cohort_draws(5, dict.fromkeys(range(4), 10))
    arm = cohort_draws(6, dict.fromkeys(range(4), 11))
    other = cohort_draws(7, dict.fromkeys(range(4), 30))
    rows = (
        cohort_rows("control", control)
        + cohort_rows("variant_b", arm)
        + cohort_rows("variant_c", other)
    )
    context = cohort_context(raw_spec, rows, arms=THREE_ARMS)

    result = _run(context, "variant_b")

    for found in result.absolute.cohorts:
        assert (found.n_arm, found.n_control) == (80, 80)
        assert found.estimate == welch_difference(arm[found.block], control[found.block]).difference
    assert _run(context, "variant_c").absolute.cohorts[0].mean_arm > 25


def test_players_who_are_not_analysed_are_not_in_a_cohort(raw_spec) -> None:
    control = cohort_draws(8, dict.fromkeys(range(4), 10))
    arm = cohort_draws(9, dict.fromkeys(range(4), 11))
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
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm) + late + never
    )

    first = _run(context).absolute.cohorts[0]

    assert first.n_arm == 80 and first.mean_arm == pytest.approx(np.mean(arm[0]), rel=1e-12)


# --- A cohort that cannot give an estimate is dropped, with a reason --------------------------


def _flat(value: int, n: int = 80) -> list[int]:
    return [value] * n


def test_a_cohort_with_no_variation_in_either_arm_is_dropped_on_both_scales(raw_spec) -> None:
    control = cohort_draws(10, dict.fromkeys(range(5), 10))
    arm = cohort_draws(11, dict.fromkeys(range(5), 12))
    control[2], arm[2] = _flat(7), _flat(9)
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm), days=35
    )

    result = _run(context)

    for scale in result.scales:
        assert scale.dropped == ((2, "no_variation"),)
        assert [c.block for c in scale.cohorts] == [0, 1, 3, 4]
        assert scale.reason is None and scale.heterogeneity.cohorts == 4


def test_one_arm_without_variation_is_still_a_cohort_when_the_other_varies(raw_spec) -> None:
    control = cohort_draws(12, dict.fromkeys(range(4), 10))
    arm = cohort_draws(13, dict.fromkeys(range(4), 12))
    arm[1] = _flat(12)
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    result = _run(context)

    assert result.absolute.dropped == () and result.log_ratio.dropped == ()
    assert [c.block for c in result.absolute.cohorts] == [0, 1, 2, 3]


def test_a_scale_left_with_fewer_than_three_cohorts_is_not_evaluated(raw_spec) -> None:
    control = cohort_draws(14, dict.fromkeys(range(4), 10))
    arm = cohort_draws(15, dict.fromkeys(range(4), 12))
    for block in (1, 3):
        control[block], arm[block] = _flat(7), _flat(9)
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    result = _run(context)

    for scale in result.scales:
        assert scale.reason == "no_variation" and scale.heterogeneity is None
        assert [c.block for c in scale.cohorts] == [0, 2]
        assert scale.dropped == ((1, "no_variation"), (3, "no_variation"))


def test_a_control_mean_of_zero_drops_the_cohort_from_the_log_scale_only(raw_spec) -> None:
    control = cohort_draws(16, dict.fromkeys(range(4), 10))
    arm = cohort_draws(17, dict.fromkeys(range(4), 12))
    control[1] = _flat(0)
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    result = _run(context)

    assert result.absolute.dropped == () and result.absolute.heterogeneity.cohorts == 4
    assert result.log_ratio.dropped == ((1, "non_positive_mean"),)
    assert [c.block for c in result.log_ratio.cohorts] == [0, 2, 3]


def test_two_non_positive_means_leave_the_log_scale_unevaluated_and_the_absolute_scale_fine(
    raw_spec,
) -> None:
    control = cohort_draws(18, dict.fromkeys(range(4), 10))
    arm = cohort_draws(19, dict.fromkeys(range(4), 12))
    control[1], control[3] = _flat(0), _flat(0)
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    result = _run(context)

    assert result.absolute.reason is None and result.absolute.heterogeneity is not None
    assert result.log_ratio.reason == "non_positive_mean"
    assert result.log_ratio.heterogeneity is None
    assert result.log_ratio.dropped == ((1, "non_positive_mean"), (3, "non_positive_mean"))


def test_the_commonest_reason_is_given_and_a_tie_goes_to_the_first_in_the_alphabet(
    raw_spec,
) -> None:
    control = cohort_draws(20, dict.fromkeys(range(4), 10))
    arm = cohort_draws(21, dict.fromkeys(range(4), 12))
    control[0], arm[0] = _flat(7), _flat(9)  # no variation
    control[1], arm[1] = _flat(7), _flat(9)  # no variation
    control[2], control[3] = _flat(0), _flat(0)  # non-positive mean
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    scale = _run(context).log_ratio

    assert sorted(reason for _, reason in scale.dropped) == [
        "no_variation",
        "no_variation",
        "non_positive_mean",
        "non_positive_mean",
    ]
    assert scale.reason == "no_variation"  # tied at 2 each; "no_variation" sorts first
    control[3] = cohort_draws(22, {3: 10})[3]
    third = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )
    assert _run(third).log_ratio.reason == "no_variation"
    control[1] = _flat(0)  # now three non-positive means against one no-variation cohort
    fourth = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )
    assert _run(fourth).log_ratio.reason == "non_positive_mean"


def test_a_tie_is_broken_by_the_alphabet_even_when_the_later_code_was_met_first(raw_spec) -> None:
    control = cohort_draws(25, dict.fromkeys(range(4), 10))
    arm = cohort_draws(26, dict.fromkeys(range(4), 12))
    control[0], control[1] = _flat(0), _flat(0)  # non-positive mean, met first
    control[2], arm[2] = _flat(7), _flat(9)  # no variation
    control[3], arm[3] = _flat(7), _flat(9)  # no variation
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    scale = _run(context).log_ratio

    assert [reason for _, reason in scale.dropped] == [
        "non_positive_mean",
        "non_positive_mean",
        "no_variation",
        "no_variation",
    ]
    assert scale.reason == "no_variation"


def test_values_the_statistics_cannot_handle_drop_the_cohort_as_not_estimable(raw_spec) -> None:
    control = cohort_draws(23, dict.fromkeys(range(5), 10))
    arm = cohort_draws(24, dict.fromkeys(range(5), 12))
    arm[2][0] = 10**400  # beyond any float: infinite for the statistics
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm), days=35
    )

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
    context = cohort_context(
        raw_spec, cohort_rows("control", {0: _flat(5)}) + cohort_rows("variant_b", {0: _flat(6)})
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


# --- The trigger ------------------------------------------------------------------------------


def _scale(q_p: float | None, slope_p: float | None) -> ScaleTest:
    """A scale test with the given p values, or not evaluated when `q_p` is None."""
    from referee.methods import CohortHeterogeneity

    found = None
    if q_p is not None:
        found = CohortHeterogeneity(
            cohorts=4,
            pooled_difference=0.0,
            q_statistic=1.0,
            degrees_of_freedom=3,
            q_p_value=q_p,
            i_squared=0.0,
            slope=0.0,
            slope_std_error=1.0,
            slope_z_statistic=0.0,
            slope_p_value=slope_p,
        )
    return ScaleTest(
        scale="absolute",
        cohorts=(),
        dropped=(),
        reason=None if found else "no_variation",
        error=None,
        heterogeneity=found,
    )


def _pair(absolute: ScaleTest, log_ratio: ScaleTest) -> CohortTest:
    return CohortTest(
        arm="a",
        control="c",
        metric="m",
        block_days=7,
        absolute=absolute,
        log_ratio=log_ratio,
    )


def test_the_level_of_each_statistic_is_a_40th_divided_by_the_non_control_arms() -> None:
    assert TRIGGER_LEVEL == 0.025
    quiet = _scale(0.5, 0.5)

    assert [trigger(_pair(quiet, quiet), m).level for m in (1, 2, 3, 5)] == [
        0.025,
        0.0125,
        0.025 / 3,
        0.005,
    ]
    with pytest.raises(ValueError, match="at least one non-control arm"):
        trigger(_pair(quiet, quiet), 0)


@pytest.mark.parametrize(
    ("q_p", "slope_p", "shows"),
    [
        (0.01, 0.5, True),
        (0.5, 0.01, True),
        (0.01, 0.01, True),
        (0.5, 0.5, False),
        (0.025, 0.025, False),
        (0.0249999, 0.5, True),
        (0.5, 0.0249999, True),
    ],
)
def test_a_scale_shows_heterogeneity_when_q_or_the_slope_is_below_the_level(
    q_p: float, slope_p: float, shows: bool
) -> None:
    assert shows_heterogeneity(_scale(q_p, slope_p), 0.025) is shows


def test_a_scale_that_was_not_evaluated_shows_nothing_either_way() -> None:
    assert shows_heterogeneity(_scale(None, None), 0.025) is None


def test_an_arm_is_flagged_only_when_both_scales_show_heterogeneity() -> None:
    loud, quiet, missing = _scale(0.001, 0.5), _scale(0.5, 0.5), _scale(None, None)

    assert trigger(_pair(loud, loud), 1) == Trigger(level=0.025, absolute=True, log_ratio=True)
    assert trigger(_pair(loud, loud), 1).flagged is True
    assert trigger(_pair(loud, quiet), 1).flagged is False
    assert trigger(_pair(quiet, loud), 1).flagged is False
    assert trigger(_pair(quiet, quiet), 1).flagged is False
    assert trigger(_pair(loud, missing), 1) == Trigger(level=0.025, absolute=True, log_ratio=None)
    assert trigger(_pair(loud, missing), 1).flagged is False
    assert trigger(_pair(missing, missing), 1).flagged is False


def test_a_level_made_stricter_by_more_arms_can_unflag_an_arm() -> None:
    borderline = _scale(0.02, 0.5)

    assert trigger(_pair(borderline, borderline), 1).flagged is True
    assert trigger(_pair(borderline, borderline), 2).flagged is False


def test_the_planted_fade_in_the_committed_export_is_flagged_for_variant_b_and_not_variant_c(
    raw_spec,
) -> None:
    spec = results_spec(raw_spec, design__planned_duration_days=21, **SESSIONS)
    context = ResultsContext.of(spec, load_export(FIXTURE, "hybrid_offer_page"))
    metric = context.metrics["sessions_7d"]
    b = cohort_test(context, plan_cohorts(context, "variant_b"), metric)
    c = cohort_test(context, plan_cohorts(context, "variant_c"), metric)

    assert trigger(b, 2).flagged is True
    assert trigger(c, 2).flagged is False


# --- The shift a quiet result could have seen -------------------------------------------------


def test_the_detectable_shifts_come_from_the_corrected_errors_and_block_numbers_the_trigger_used(
    raw_spec,
) -> None:
    context, _, _ = _fade(raw_spec)
    scale = _run(context).absolute

    found = detectable_shifts(scale, 0.025)

    errors = [c.corrected_std_error for c in scale.cohorts]
    for shape in ("linear_fade", "step"):
        expected = cohort_detectable_shift(
            errors, positions=[0, 1, 2, 3], shape=shape, level=0.025, power=0.8
        )
        assert found[shape] == expected
    assert 0 < found["step"] < found["linear_fade"]
    assert set(found) == {"linear_fade", "step"}


def test_the_detectable_shift_follows_the_level_and_the_gap_between_blocks(raw_spec) -> None:
    control = cohort_draws(31, {0: 10, 1: 10, 2: 10, 3: 10})
    arm = cohort_draws(32, {0: 12, 1: 12, 2: 12, 3: 12})
    arm[2] = arm[2][:20]
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )
    scale = _run(context).absolute

    gapped = detectable_shifts(scale, 0.025)
    stricter = detectable_shifts(scale, 0.0125)

    assert [c.block for c in scale.cohorts] == [0, 1, 3]
    errors = [c.corrected_std_error for c in scale.cohorts]
    assert gapped["linear_fade"] == cohort_detectable_shift(
        errors, positions=[0, 1, 3], shape="linear_fade", level=0.025
    )
    assert stricter["step"] > gapped["step"] and stricter["linear_fade"] > gapped["linear_fade"]


def test_a_scale_that_was_not_evaluated_has_no_detectable_shift() -> None:
    assert detectable_shifts(_scale(None, None), 0.025) is None


# --- Why a result tells little ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("shift", "control_mean", "mde", "events", "labels"),
    [
        (1.0, 1.0, None, None, ()),
        (1.0001, 1.0, None, None, ("shift_exceeds_control_mean",)),
        (4.0, 10.0, 1.0, None, ()),
        (4.0001, 10.0, 1.0, None, ("shift_exceeds_4_times_registered_mde",)),
        (1.0, 10.0, None, 5.0, ()),
        (1.0, 10.0, None, 4.9999, ("fewer_than_5_expected_events",)),
        (
            50.0,
            10.0,
            1.0,
            2.0,
            (
                "shift_exceeds_control_mean",
                "shift_exceeds_4_times_registered_mde",
                "fewer_than_5_expected_events",
            ),
        ),
        (5.0, 10.0, None, 0.0, ("fewer_than_5_expected_events",)),
    ],
)
def test_a_result_is_low_information_by_the_three_rules_of_section_21_7(
    shift: float, control_mean: float, mde: float | None, events: float | None, labels: tuple
) -> None:
    got = low_information(
        shift=shift, control_mean=control_mean, registered_mde=mde, expected_events=events
    )

    assert got == labels


def test_the_registered_effect_is_the_primary_metrics_alone(raw_spec) -> None:
    guardrail = {
        "name": "sessions_7d",
        "kind": "continuous",
        "baseline": 10.0,
        "baseline_std": 5.0,
        "harmful_direction": "decrease",
        "tolerance_relative": 0.05,
    }
    spec = results_spec(raw_spec, arms=TWO_ARMS, guardrails=[guardrail], design__mde_relative=0.3)
    context = ResultsContext.of(spec, build_data([Row("p1")]))

    assert registered_mde(context, context.metrics["purchased_7d"]) == pytest.approx(0.3 * 0.05)
    assert registered_mde(context, context.metrics["sessions_7d"]) is None


def _binary_rows(arm: str, rates: dict[int, float], n: int = 200) -> list[Row]:
    """`n` players per block, a share `rate` of them buying after their first exposure."""
    rows = []
    for block, rate in rates.items():
        buyers = round(rate * n)
        for i in range(n):
            bought = i < buyers
            rows.append(
                Row(
                    f"{arm}_{block:02d}_{i:04d}",
                    arm,
                    assigned_at=at(7 * block),
                    exposed_at=at(7 * block, 1),
                    purchases=int(bought),
                    first_purchase_at=at(7 * block, 2) if bought else None,
                )
            )
    return rows


def _binary_context(raw_spec, control: dict[int, float], arm: dict[int, float], n: int = 200):
    spec = results_spec(
        raw_spec,
        arms=TWO_ARMS,
        design__planned_duration_days=28,
        design__min_duration_days=7,
        design__start_utc=START,
        design__mde_relative=2.0,
    )
    rows = _binary_rows("control", control, n) + _binary_rows("variant_b", arm, n)
    return ResultsContext.of(spec, build_data(rows))


def test_the_fewest_events_in_any_arm_and_cohort_is_the_expected_count_of_a_binary_metric(
    raw_spec,
) -> None:
    context = _binary_context(
        raw_spec,
        control={0: 0.10, 1: 0.10, 2: 0.10, 3: 0.10},
        arm={0: 0.10, 1: 0.03, 2: 0.10, 3: 0.10},
    )
    metric = context.metrics["purchased_7d"]

    scale = cohort_test(context, plan_cohorts(context, "variant_b"), metric).absolute

    assert min_expected_events(scale) == pytest.approx(0.03 * 200)  # 6 buyers of 200
    assert min_expected_events(_scale(None, None)) is None


# --- The control arm across the cohorts -------------------------------------------------------


def test_the_control_mean_by_cohort_has_a_95_percent_interval_and_a_pooled_mean(raw_spec) -> None:
    context, control, _ = _fade(raw_spec)
    plan = plan_cohorts(context, "variant_b")

    baseline = control_baseline(context, plan, context.metrics["sessions_7d"])

    assert [c.block for c in baseline.cohorts] == [0, 1, 2, 3]
    for found in baseline.cohorts:
        values = np.array(control[found.block], float)
        low, high = stats.t.interval(0.95, len(values) - 1, values.mean(), stats.sem(values))
        assert found.n == 80 and found.mean == pytest.approx(values.mean(), rel=1e-12)
        assert found.ci_low == pytest.approx(low, rel=1e-9)
        assert found.ci_high == pytest.approx(high, rel=1e-9)
    everyone = np.concatenate([control[b] for b in range(4)]).astype(float)
    assert baseline.pooled_mean == pytest.approx(everyone.mean(), rel=1e-12)


def test_the_homogeneity_of_a_continuous_control_is_cochrans_q_of_its_means(raw_spec) -> None:
    context, control, _ = _fade(raw_spec)
    plan = plan_cohorts(context, "variant_b")

    baseline = control_baseline(context, plan, context.metrics["sessions_7d"])

    means = np.array([np.mean(control[b]) for b in range(4)])
    ses = np.array([stats.sem(np.array(control[b], float)) for b in range(4)])
    ses = ses * np.array([welch_correction(79)] * 4)
    w = 1 / ses**2
    q = (w * (means - (w * means).sum() / w.sum()) ** 2).sum()
    assert baseline.homogeneity_p == pytest.approx(stats.chi2.sf(q, 3), rel=1e-9)
    assert baseline.moves is False  # the control is drawn from one distribution


def test_a_control_whose_mean_drifts_across_the_cohorts_is_said_to_move(raw_spec) -> None:
    control = cohort_draws(41, {0: 8, 1: 10, 2: 12, 3: 14})
    arm = cohort_draws(42, {0: 10, 1: 10, 2: 10, 3: 10})
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
    )

    assert baseline.homogeneity_p < 0.001 and baseline.moves is True


def test_the_homogeneity_of_a_binary_control_is_the_chi_squared_test_of_its_counts(
    raw_spec,
) -> None:
    context = _binary_context(
        raw_spec,
        control={0: 0.05, 1: 0.10, 2: 0.15, 3: 0.20},
        arm={0: 0.10, 1: 0.10, 2: 0.10, 3: 0.10},
        n=400,
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["purchased_7d"]
    )

    table = [[20, 40, 60, 80], [380, 360, 340, 320]]
    expected = stats.chi2_contingency(table, correction=False)[1]
    assert baseline.homogeneity_p == pytest.approx(expected, rel=1e-6)
    assert baseline.moves is True
    assert [c.mean for c in baseline.cohorts] == pytest.approx([0.05, 0.10, 0.15, 0.20])


def test_the_homogeneity_of_a_rare_event_control_is_the_exact_test_and_not_chi_squared(
    raw_spec,
) -> None:
    # 2, 3, 2 and 9 buyers of 80: the chi-squared test says the control moves (p = 0.030), the
    # exact test, which small counts call for (design 21.4), that it does not (p = 0.068)
    events = {0: 2, 1: 3, 2: 2, 3: 9}
    context = _binary_context(
        raw_spec,
        control={b: e / 80 for b, e in events.items()},
        arm=dict.fromkeys(range(4), 0.10),
        n=80,
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["purchased_7d"]
    )

    sizes, total = [80] * 4, sum(events.values())

    def chance_of(counts) -> float:
        ways = math.prod(math.comb(n, e) for n, e in zip(sizes, counts, strict=True))
        return ways / math.comb(sum(sizes), total)

    observed = chance_of(list(events.values()))
    every_table = itertools.product(*(range(min(n, total) + 1) for n in sizes))
    exact = sum(
        chance_of(counts)
        for counts in every_table
        if sum(counts) == total and chance_of(counts) <= observed * (1 + 1e-9)
    )
    assert baseline.homogeneity_p == pytest.approx(exact, rel=1e-9)
    assert baseline.homogeneity_p == pytest.approx(0.0684, abs=5e-5) and baseline.moves is False


def test_a_cohort_that_both_scales_left_out_of_the_test_is_not_in_the_control_baseline(
    raw_spec,
) -> None:
    # no buyer in either arm in block 2: nothing to compare there on either scale
    context = _binary_context(
        raw_spec,
        control={0: 0.10, 1: 0.10, 2: 0.0, 3: 0.10},
        arm={0: 0.10, 1: 0.10, 2: 0.0, 3: 0.10},
    )
    plan = plan_cohorts(context, "variant_b")
    metric = context.metrics["purchased_7d"]
    test = cohort_test(context, plan, metric)

    baseline = control_baseline(context, plan, metric)

    assert 2 in plan.usable
    assert [block for block, _ in test.absolute.dropped] == [2]
    assert [block for block, _ in test.log_ratio.dropped] == [2]
    assert [c.block for c in baseline.cohorts] == [0, 1, 3]
    assert baseline.pooled_mean == pytest.approx(0.10)


def test_a_cohort_kept_by_one_scale_is_in_the_control_baseline(raw_spec) -> None:
    # variant_b sells nothing in block 2: the log ratio has no cohort there, the difference has
    control = cohort_draws(61, dict.fromkeys(range(4), 10))
    arm = cohort_draws(62, dict.fromkeys(range(4), 10))
    arm[2] = [0] * 80
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )
    plan, metric = plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
    test = cohort_test(context, plan, metric)

    baseline = control_baseline(context, plan, metric)

    assert [b for b, _ in test.log_ratio.dropped] == [2] and not test.absolute.dropped
    assert [c.block for c in baseline.cohorts] == [0, 1, 2, 3]


def test_a_baseline_of_a_test_that_compared_no_cohort_is_refused(raw_spec) -> None:
    control = {b: [7] * 80 for b in range(4)}
    arm = {b: [9] * 80 for b in range(4)}  # no variation in either arm: both scales drop all
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    with pytest.raises(ValueError, match="compared no cohort"):
        control_baseline(
            context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
        )


def test_the_homogeneity_cannot_be_worked_out_when_the_control_does_not_vary(raw_spec) -> None:
    control = {b: [7] * 80 for b in range(4)}
    arm = cohort_draws(43, {0: 10, 1: 10, 2: 10, 3: 10})
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
    )

    assert baseline.homogeneity_p is None and baseline.moves is False
    assert [c.ci_low for c in baseline.cohorts] == [7.0] * 4


@pytest.mark.parametrize(
    ("p", "moves"), [(0.0499, True), (0.05, False), (0.7, False), (None, False)]
)
def test_a_baseline_moves_when_its_homogeneity_p_is_below_005(p: float | None, moves: bool) -> None:
    assert ControlBaseline(cohorts=(), pooled_mean=1.0, homogeneity_p=p).moves is moves


def test_the_baseline_of_a_plan_that_is_not_evaluated_is_refused(raw_spec) -> None:
    context = cohort_context(
        raw_spec, cohort_rows("control", {0: _flat(5)}) + cohort_rows("variant_b", {0: _flat(6)})
    )

    with pytest.raises(ValueError, match="not evaluated"):
        control_baseline(
            context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
        )


def test_the_fewest_events_can_be_in_control_as_well_as_in_the_arm(raw_spec) -> None:
    context = _binary_context(
        raw_spec,
        control={0: 0.10, 1: 0.02, 2: 0.10, 3: 0.10},
        arm={0: 0.10, 1: 0.10, 2: 0.10, 3: 0.10},
    )
    scale = cohort_test(
        context, plan_cohorts(context, "variant_b"), context.metrics["purchased_7d"]
    ).absolute

    assert min_expected_events(scale) == pytest.approx(0.02 * 200)


def test_the_pooled_control_mean_weighs_each_cohort_by_its_players(raw_spec) -> None:
    control = {0: [2] * 60, 1: [4] * 100, 2: [6] * 80, 3: [10] * 90}
    control = {b: [v + (i % 2) for i, v in enumerate(vals)] for b, vals in control.items()}
    arm = cohort_draws(51, dict.fromkeys(range(4), 5))
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
    )

    everyone = [v for b in range(4) for v in control[b]]
    assert [c.n for c in baseline.cohorts] == [60, 100, 80, 90]
    assert baseline.pooled_mean == pytest.approx(np.mean(everyone), rel=1e-12)
    assert baseline.pooled_mean != pytest.approx(np.mean([c.mean for c in baseline.cohorts]))


def test_the_control_baseline_covers_the_cohorts_the_test_used_and_no_others(raw_spec) -> None:
    control = cohort_draws(52, dict.fromkeys(range(4), 10))
    arm = cohort_draws(53, dict.fromkeys(range(4), 10))
    arm[2] = arm[2][:20]  # block 2 cannot be used: the arm has 20 players there
    context = cohort_context(
        raw_spec, cohort_rows("control", control) + cohort_rows("variant_b", arm)
    )

    baseline = control_baseline(
        context, plan_cohorts(context, "variant_b"), context.metrics["sessions_7d"]
    )

    assert [c.block for c in baseline.cohorts] == [0, 1, 3]
    assert baseline.pooled_mean == pytest.approx(
        np.mean([v for b in (0, 1, 3) for v in control[b]]), rel=1e-12
    )
