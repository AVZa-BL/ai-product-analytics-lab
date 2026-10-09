"""Which cohorts of first exposure the cohort test may use (design sections 21.5 and 21.6)."""

import math
from datetime import timedelta

import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, results_spec

from referee.cohorts import (
    FLOOR,
    WEEKLY_MEDIAN_MINIMUM,
    Minimum,
    cohort_sizes,
    plan_cohorts,
)
from referee.results import ResultsContext

START = "2026-04-11T00:00:00Z"
THREE_ARMS = [
    {"name": "control", "allocation": 0.4, "is_control": True},
    {"name": "variant_b", "allocation": 0.3},
    {"name": "variant_c", "allocation": 0.3},
]


def _rows(arm: str, per_block: dict[int, int], *, block_days: int = 7, prefix: str | None = None):
    """`per_block[b]` players of `arm`, assigned and first exposed in block b of `block_days`."""
    rows: list[Row] = []
    for block, count in per_block.items():
        for i in range(count):
            name = f"{prefix or arm}_{block:02d}_{i:04d}"
            rows.append(
                Row(
                    name,
                    arm,
                    assigned_at=at(block_days * block),
                    exposed_at=at(block_days * block, 1),
                )
            )
    return rows


def _context(raw_spec, rows: list[Row], *, days: int = 28, arms=TWO_ARMS, **changes):
    spec = results_spec(
        raw_spec,
        arms=arms,
        design__planned_duration_days=days,
        design__min_duration_days=7,
        design__start_utc=START,
        **changes,
    )
    return ResultsContext.of(spec, build_data(rows))


def _both(raw_spec, per_block: dict[int, int], **kw):
    rows = _rows("control", per_block) + _rows("variant_b", per_block)
    return _context(raw_spec, rows, **kw)


# --- Blocks -----------------------------------------------------------------------------------


def test_a_block_of_any_length_is_counted_from_the_origin(raw_spec) -> None:
    context = _both(raw_spec, {0: 1})

    assert context.origin.isoformat() == "2026-04-11T00:00:00+00:00"
    moment = context.origin + timedelta(days=15, hours=23)
    assert [context.block_of(moment, days) for days in (1, 7, 14, 15, 16)] == [15, 2, 1, 1, 0]
    assert context.block_of(moment, 7) == context.week_of(moment)
    assert context.block_of(context.origin - timedelta(hours=1), 7) == -1


# --- Counting the players of each cohort ------------------------------------------------------


def test_cohorts_are_the_analysed_players_by_block_of_first_exposure_not_of_assignment(
    raw_spec,
) -> None:
    rows = [
        # assigned on day 6, first exposed on day 8: block 1, not block 0
        Row("a1", "control", assigned_at=at(6), exposed_at=at(8)),
        Row("a2", "control", assigned_at=at(0), exposed_at=at(0, 3), extra_exposures=((at(9), 1),)),
        Row("b1", "variant_b", assigned_at=at(13), exposed_at=at(13, 23)),
    ]

    sizes = cohort_sizes(_context(raw_spec, rows), 7)

    assert sizes == {0: {"control": 1, "variant_b": 0}, 1: {"control": 1, "variant_b": 1}}


def test_players_never_exposed_and_players_exposed_late_are_in_no_cohort(raw_spec) -> None:
    late = {"purchases": 1, "first_purchase_at": at(0, 1), "exposed_at": at(0, 5)}
    rows = [
        Row("c1", "control"),
        Row("c2", "control", exposed_at=None),
        Row("c3", "control", **late),
        Row("v1", "variant_b"),
    ]

    assert cohort_sizes(_context(raw_spec, rows), 7) == {0: {"control": 1, "variant_b": 1}}


def test_every_arm_is_listed_in_every_block_that_holds_anybody_and_blocks_come_in_order(
    raw_spec,
) -> None:
    rows = _rows("variant_c", {2: 2, 0: 1}, prefix="z") + _rows("control", {1: 3}, prefix="a")

    sizes = cohort_sizes(_context(raw_spec, rows, arms=THREE_ARMS), 7)

    assert list(sizes) == [0, 1, 2]
    assert sizes[1] == {"control": 3, "variant_b": 0, "variant_c": 0}
    assert sizes[2] == {"control": 0, "variant_b": 0, "variant_c": 2}


def test_fortnightly_blocks_hold_two_weeks_each(raw_spec) -> None:
    sizes = cohort_sizes(_both(raw_spec, {0: 2, 1: 3, 2: 4, 3: 5}, days=56), 14)

    assert sizes == {
        0: {"control": 5, "variant_b": 5},
        1: {"control": 9, "variant_b": 9},
    }


# --- Weekly blocks ----------------------------------------------------------------------------


def test_weekly_blocks_are_chosen_when_three_cohorts_cover_the_window_and_are_big_enough(
    raw_spec,
) -> None:
    context = _both(raw_spec, {0: 70, 1: 70, 2: 70, 3: 70}, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.evaluated and plan.reason is None
    assert (plan.arm, plan.control, plan.block_days) == ("variant_b", "control", 7)
    assert plan.usable == (0, 1, 2, 3) and len(plan.attempts) == 1


@pytest.mark.parametrize(("smaller_arm", "weekly"), [(59, False), (60, True)])
def test_the_median_of_the_smaller_arm_must_be_at_least_60_to_keep_weekly_blocks(
    raw_spec, smaller_arm: int, weekly: bool
) -> None:
    rows = _rows("control", dict.fromkeys(range(4), 90)) + _rows(
        "variant_b", dict.fromkeys(range(4), smaller_arm)
    )
    context = _context(raw_spec, rows, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert WEEKLY_MEDIAN_MINIMUM == 60
    assert plan.attempts[0].median_smaller_arm == smaller_arm
    assert plan.evaluated is weekly
    assert plan.reason == (None if weekly else "cohorts_too_small_for_weekly_blocks")


def test_the_median_counts_empty_blocks_of_the_window_as_zero(raw_spec) -> None:
    # Four blocks in the window; only two hold players, so the median of 80, 80, 0, 0 is 40.
    context = _both(raw_spec, {0: 80, 1: 80, 4: 80}, design__mde_relative=2.0)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.median_smaller_arm == 40.0 and attempt.window_blocks == 4


def test_the_median_is_over_the_smaller_arm_of_each_block_not_of_the_two_arms_together(
    raw_spec,
) -> None:
    rows = _rows("control", {0: 200, 1: 10, 2: 200, 3: 10}) + _rows(
        "variant_b", {0: 10, 1: 200, 2: 10, 3: 200}
    )

    attempt = plan_cohorts(
        _context(raw_spec, rows, design__mde_relative=2.0), "variant_b"
    ).attempts[0]

    assert attempt.median_smaller_arm == 10.0


@pytest.mark.parametrize(("days", "enough"), [(14, False), (20, False), (21, True)])
def test_a_plan_must_hold_three_whole_weekly_blocks(raw_spec, days: int, enough: bool) -> None:
    context = _both(raw_spec, {0: 80, 1: 80, 2: 80}, days=days, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.evaluated is enough
    assert plan.reason == (None if enough else "window_holds_fewer_than_3_blocks")
    assert plan.attempts[0].window_blocks == days // 7


@pytest.mark.parametrize(
    ("sizes", "evaluated"),
    [
        ({0: 80, 1: 80, 2: 30, 3: 80}, True),
        ({0: 80, 1: 80, 2: 29, 3: 80}, True),  # three cohorts still reach the floor
        ({0: 80, 1: 80, 2: 29, 3: 29}, False),
    ],
)
def test_three_cohorts_must_reach_the_floor(
    raw_spec, sizes: dict[int, int], evaluated: bool
) -> None:
    context = _both(raw_spec, sizes, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.evaluated is evaluated
    if not evaluated:
        assert plan.usable == () and plan.block_days is None
        assert plan.reason == "fewer_than_3_cohorts_reach_minimum"
        assert plan.attempts[0].usable == (0, 1)


def test_a_cohort_needs_the_floor_in_both_the_arm_and_control(raw_spec) -> None:
    rows = _rows("control", {0: 80, 1: 29, 2: 80, 3: 80}) + _rows(
        "variant_b", {0: 80, 1: 80, 2: 80, 3: 29}
    )

    attempt = plan_cohorts(
        _context(raw_spec, rows, design__mde_relative=2.0), "variant_b"
    ).attempts[0]

    assert FLOOR == 30
    assert attempt.usable == (0, 2) and attempt.reason == "fewer_than_3_cohorts_reach_minimum"


def test_usable_cohorts_must_reach_into_both_halves_of_the_window(raw_spec) -> None:
    # Five blocks in a 35-day window: blocks 0, 1 and 2 are the first half, 3 and 4 the second.
    context = _both(raw_spec, {0: 80, 1: 80, 2: 80, 3: 5, 4: 5}, days=35, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.attempts[0].usable == (0, 1, 2) and plan.attempts[0].covers_window is False
    assert plan.reason == "cohorts_do_not_cover_the_window"


def test_a_cohort_after_the_end_of_the_window_counts_as_the_second_half(raw_spec) -> None:
    context = _both(
        raw_spec, {0: 80, 1: 80, 2: 80, 3: 5, 4: 5, 6: 80}, days=35, design__mde_relative=2.0
    )

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.usable == (0, 1, 2, 6) and attempt.covers_window is True


# --- The fortnightly fall-back ----------------------------------------------------------------


def test_small_weekly_cohorts_in_a_long_plan_fall_back_to_fortnightly_blocks(raw_spec) -> None:
    context = _both(raw_spec, dict.fromkeys(range(8), 40), days=56, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.evaluated and plan.block_days == 14 and plan.usable == (0, 1, 2, 3)
    assert [a.block_days for a in plan.attempts] == [7, 14]
    assert plan.attempts[0].reason == "cohorts_too_small_for_weekly_blocks"
    assert plan.attempts[1].median_smaller_arm == 80.0


def test_a_plan_shorter_than_42_days_does_not_fall_back(raw_spec) -> None:
    context = _both(raw_spec, dict.fromkeys(range(5), 40), days=41, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert not plan.evaluated and plan.reason == "cohorts_too_small_for_weekly_blocks"
    assert [a.block_days for a in plan.attempts] == [7]


def test_when_the_fall_back_fails_too_the_reason_is_the_weekly_attempts(raw_spec) -> None:
    context = _both(raw_spec, {0: 40, 1: 40, 6: 40}, days=56, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert not plan.evaluated and plan.block_days is None and plan.usable == ()
    assert plan.reason == "cohorts_too_small_for_weekly_blocks"  # the weekly attempt's
    assert [a.block_days for a in plan.attempts] == [7, 14]
    assert plan.attempts[1].reason == "fewer_than_3_cohorts_reach_minimum"


# --- The registered size as a preference ------------------------------------------------------


def test_the_preferred_minimum_is_a_quarter_of_the_planned_share_of_a_block(raw_spec) -> None:
    context = _both(raw_spec, dict.fromkeys(range(4), 100), design__mde_relative=0.3)
    required = context.required_n("variant_b")

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert required == 3780
    assert attempt.minimum_arm == Minimum(
        registered=3780,
        achieved=400,
        preferred=math.ceil(7 * 3780 / (4 * 28)),
        used=FLOOR,
    )
    assert attempt.minimum_arm.preferred == 237
    assert attempt.minimum_control.registered == 3780


def test_the_preferred_minimum_is_not_used_when_it_would_leave_fewer_than_three_cohorts(
    raw_spec,
) -> None:
    context = _both(raw_spec, dict.fromkeys(range(4), 100), design__mde_relative=0.3)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.preferred_used is False and attempt.minimum_arm.used == FLOOR
    assert attempt.usable == attempt.usable_at_floor == (0, 1, 2, 3)


def test_the_preferred_minimum_is_used_when_it_keeps_at_least_90_percent_of_the_cohorts(
    raw_spec,
) -> None:
    # 70-day plan: preferred = ceil(7 * 3780 / (4 * 70)) = 95. Nine of ten cohorts reach it.
    sizes = {**dict.fromkeys(range(9), 100), 9: 50}
    context = _both(raw_spec, sizes, days=70, design__mde_relative=0.3)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.minimum_arm.preferred == 95
    assert attempt.preferred_used is True
    assert attempt.usable == tuple(range(9)) and attempt.usable_at_floor == tuple(range(10))
    assert attempt.minimum_arm.used == attempt.minimum_control.used == 95


def test_the_preferred_minimum_is_not_used_when_it_would_drop_more_than_10_percent(
    raw_spec,
) -> None:
    sizes = {**dict.fromkeys(range(8), 100), 8: 50, 9: 50}
    context = _both(raw_spec, sizes, days=70, design__mde_relative=0.3)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.preferred_used is False and attempt.minimum_arm.used == FLOOR
    assert attempt.usable == tuple(range(10))


def test_the_preference_never_goes_below_the_floor(raw_spec) -> None:
    context = _both(raw_spec, dict.fromkeys(range(4), 80), design__mde_relative=2.0)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.minimum_arm.registered == 141
    assert attempt.minimum_arm.preferred == FLOOR  # ceil(7 * 141 / 112) = 9, below the floor
    assert attempt.preferred_used is False


def test_each_arm_has_the_minimum_of_its_own_registered_size(raw_spec) -> None:
    rows = (
        _rows("control", dict.fromkeys(range(4), 100))
        + _rows("variant_b", dict.fromkeys(range(4), 100))
        + _rows("variant_c", dict.fromkeys(range(4), 100))
    )
    context = _context(raw_spec, rows, arms=THREE_ARMS, design__mde_relative=1.0)

    b, c = plan_cohorts(context, "variant_b"), plan_cohorts(context, "variant_c")

    assert b.attempts[0].minimum_arm.registered == context.required_n("variant_b")
    assert c.attempts[0].minimum_arm.registered == context.required_n("variant_c")
    assert c.attempts[0].minimum_control.registered == context.required_n("control")
    assert (b.arm, c.arm, b.control, c.control) == ("variant_b", "variant_c", "control", "control")


def test_a_design_that_cannot_be_sized_has_no_registered_size_and_uses_the_floor(raw_spec) -> None:
    context = _both(
        raw_spec,
        dict.fromkeys(range(4), 80),
        primary_metric__baseline=0.9,
        design__mde_relative=0.3,
    )

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert context.plan is None
    assert attempt.minimum_arm.registered is None and attempt.minimum_arm.preferred == FLOOR


def test_fortnightly_blocks_scale_the_preferred_minimum_by_their_length(raw_spec) -> None:
    context = _both(raw_spec, dict.fromkeys(range(8), 40), days=56, design__mde_relative=0.3)

    weekly, fortnightly = plan_cohorts(context, "variant_b").attempts

    assert weekly.minimum_arm.preferred == math.ceil(7 * 3780 / (4 * 56))
    assert fortnightly.minimum_arm.preferred == math.ceil(14 * 3780 / (4 * 56))


# --- It never looks at an outcome -------------------------------------------------------------


def test_the_plan_does_not_depend_on_any_outcome(raw_spec) -> None:
    def rows(sessions: int, purchases: int):
        out = []
        for row in _rows("control", dict.fromkeys(range(4), 70)) + _rows(
            "variant_b", dict.fromkeys(range(4), 70)
        ):
            row.sessions = sessions
            row.purchases = purchases
            row.first_purchase_at = None if purchases == 0 else row.exposed_at + timedelta(hours=2)
            out.append(row)
        return out

    first = plan_cohorts(_context(raw_spec, rows(1, 0), design__mde_relative=2.0), "variant_b")
    second = plan_cohorts(_context(raw_spec, rows(99, 3), design__mde_relative=2.0), "variant_b")

    assert first == second


# --- The edges of every rule --------------------------------------------------------------------


def test_a_cohort_of_exactly_the_floor_is_usable_in_the_arm_and_in_control(raw_spec) -> None:
    both = plan_cohorts(
        _both(raw_spec, dict.fromkeys(range(4), 30), design__mde_relative=2.0), "variant_b"
    )
    arm_short = plan_cohorts(
        _context(
            raw_spec,
            _rows("control", dict.fromkeys(range(4), 30))
            + _rows("variant_b", dict.fromkeys(range(4), 29)),
            design__mde_relative=2.0,
        ),
        "variant_b",
    )

    assert both.attempts[0].usable == (0, 1, 2, 3)
    assert arm_short.attempts[0].usable == ()


def test_exactly_three_cohorts_at_the_preferred_minimum_are_enough_to_use_it(raw_spec) -> None:
    # 21-day plan, required 435 per arm: the preferred minimum is ceil(7 * 435 / 84) = 37.
    context = _both(raw_spec, dict.fromkeys(range(3), 40), days=21, design__mde_relative=1.0)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.minimum_arm.preferred == 37
    assert attempt.preferred_used is True and attempt.minimum_arm.used == 37


def test_two_cohorts_at_the_preferred_minimum_are_not_enough_to_use_it(raw_spec) -> None:
    context = _both(raw_spec, {0: 40, 1: 40, 2: 33}, days=21, design__mde_relative=1.0)

    attempt = plan_cohorts(context, "variant_b").attempts[0]

    assert attempt.usable_at_floor == (0, 1, 2) and attempt.preferred_used is False
    assert attempt.usable == (0, 1, 2)


def test_the_median_rule_is_for_weekly_blocks_only(raw_spec) -> None:
    # 80 players a fortnight is 40 a week: too few for weekly blocks, but fortnightly blocks
    # are chosen on their floor alone, so a median of 40 does not stop them.
    context = _both(raw_spec, dict.fromkeys(range(8), 40), days=56, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert plan.evaluated and plan.block_days == 14
    assert plan.attempts[1].median_smaller_arm == 80.0
    context_small = _both(raw_spec, dict.fromkeys(range(8), 20), days=56, design__mde_relative=2.0)
    small = plan_cohorts(context_small, "variant_b")
    assert small.evaluated and small.block_days == 14
    assert small.attempts[1].median_smaller_arm == 40.0 < WEEKLY_MEDIAN_MINIMUM


@pytest.mark.parametrize(("days", "falls_back"), [(41, False), (42, True)])
def test_the_fall_back_needs_a_plan_of_42_days(raw_spec, days: int, falls_back: bool) -> None:
    context = _both(raw_spec, dict.fromkeys(range(6), 40), days=days, design__mde_relative=2.0)

    plan = plan_cohorts(context, "variant_b")

    assert (len(plan.attempts) == 2) is falls_back
    assert plan.evaluated is falls_back


def test_the_first_half_of_four_blocks_is_blocks_0_and_1_and_the_second_is_2_and_3(
    raw_spec,
) -> None:
    covering = plan_cohorts(
        _both(raw_spec, {0: 80, 1: 80, 2: 80}, days=28, design__mde_relative=2.0), "variant_b"
    )
    late_only = plan_cohorts(
        _both(raw_spec, {2: 80, 3: 80, 5: 80}, days=28, design__mde_relative=2.0), "variant_b"
    )
    early_only = plan_cohorts(
        _both(raw_spec, {0: 80, 1: 80}, days=28, design__mde_relative=2.0), "variant_b"
    )

    assert covering.attempts[0].covers_window is True  # block 2 is the second half
    assert late_only.attempts[0].usable == (2, 3, 5)
    assert late_only.attempts[0].covers_window is False  # nothing in the first half
    assert early_only.attempts[0].covers_window is False


def test_the_median_is_over_the_blocks_of_the_window_not_over_the_blocks_that_hold_players(
    raw_spec,
) -> None:
    # Blocks 0 and 1 hold 80; blocks 2 and 3 are empty; block 7 is outside the window.
    attempt = plan_cohorts(
        _both(raw_spec, {0: 80, 1: 80, 7: 200}, design__mde_relative=2.0), "variant_b"
    ).attempts[0]

    assert attempt.median_smaller_arm == 40.0


def test_the_median_is_over_the_smaller_arm_even_when_the_arm_is_the_larger(raw_spec) -> None:
    rows = _rows("control", dict.fromkeys(range(4), 70)) + _rows(
        "variant_b", dict.fromkeys(range(4), 300)
    )

    attempt = plan_cohorts(
        _context(raw_spec, rows, design__mde_relative=2.0), "variant_b"
    ).attempts[0]

    assert attempt.median_smaller_arm == 70.0
