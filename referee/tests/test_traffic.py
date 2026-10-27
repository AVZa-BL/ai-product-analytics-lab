"""The traffic a test that could not run would need (design section 21.6).

The answer is for the plan: the least multiple of the observed cohort sizes from which the plan's
own rules pass, with weekly blocks or else 14-day ones, and keep passing at every larger multiple.
The rules are those of `plan_cohorts`; these tests check the answer against them, by hand on small
cases, against the real plan on real contexts with every player present several times, and by
search on random cases.
"""

import math
import random
from fractions import Fraction

import pytest
from cohort_helpers import THREE_ARMS, sized_context
from results_helpers import at

from referee.cohorts import (
    Attempt,
    CohortPlan,
    Minimum,
    _attempt,
    _breakpoints,
    _first_pass,
    _least,
    _median_smaller,
    _price,
    _runs,
    plan_cohorts,
    traffic_needed,
)

FLAT = {b: 20 for b in range(5)}


def _flat(count: int, weeks: int) -> dict[int, int]:
    return dict.fromkeys(range(weeks), count)


def _traffic(raw_spec, arm, control, days, **more):
    context = sized_context(raw_spec, arm, control, days=days, **more)
    plan = plan_cohorts(context, "variant_b")
    return plan, traffic_needed(plan)


def _copies(factor: float) -> int:
    """The least whole number of copies that is at least `factor`, exactly (2.01 is not 2.0)."""
    return math.ceil(Fraction(str(factor)))


def _evaluated(raw_spec, arm, control, days, copies, **more):
    context = sized_context(raw_spec, arm, control, days=days, copies=copies, **more)
    return plan_cohorts(context, "variant_b")


def _made(
    sizes: dict[int, tuple[int, int]],
    *,
    window_blocks: int,
    block_days: int = 7,
    floor: int = 30,
    preferred: tuple[int, int] | None = None,
    incomplete: tuple[int, ...] = (),
    reason: str | None = "fewer_than_3_cohorts_reach_minimum",
) -> Attempt:
    """An attempt built from sizes alone, as (arm, control) players per block."""
    wanted = preferred or (floor, floor)
    return Attempt(
        block_days=block_days,
        window_blocks=window_blocks,
        sizes={block: {"a": found[0], "c": found[1]} for block, found in sizes.items()},
        usable=(),
        usable_at_floor=(),
        preferred_used=False,
        minimum_arm=Minimum(registered=None, achieved=0, preferred=wanted[0], used=floor),
        minimum_control=Minimum(registered=None, achieved=0, preferred=wanted[1], used=floor),
        median_smaller_arm=0.0,
        covers_window=False,
        incomplete=incomplete,
        reason=reason,
    )


def _plan_of(*attempts: Attempt, floor: int = 30, reason="fewer_than_3_cohorts_reach_minimum"):
    return CohortPlan(
        arm="a",
        control="c",
        block_days=None,
        usable=(),
        reason=reason,
        attempts=tuple(attempts),
        floor=floor,
    )


def _sides(binding):
    return sorted((b.block, b.side) for b in binding)


# --- By hand, on real contexts ----------------------------------------------------------------


def test_a_plan_that_runs_needs_no_traffic(raw_spec) -> None:
    plan, traffic = _traffic(raw_spec, _flat(80, 5), _flat(80, 5), 35)

    assert plan.evaluated and traffic is None


def test_flat_cohorts_of_20_need_three_times_the_traffic_for_the_weekly_median_of_60(
    raw_spec,
) -> None:
    """The floor of 30 asks for 1.5 times, the weekly median of 60 for 3 times: the median binds."""
    plan, traffic = _traffic(raw_spec, FLAT, FLAT, 35)

    assert plan.reason == "fewer_than_3_cohorts_reach_minimum"
    assert (traffic.now.factor, traffic.now.block_days, traffic.blocker) == (3.0, 7, None)
    (binding,) = traffic.now.binding
    assert (binding.kind, binding.block_days, binding.block, binding.side) == (
        "weekly_median",
        7,
        None,
        "smaller_arm",
    )
    assert (binding.have, binding.need) == (20, 60)
    assert traffic.after_windows_close is None and not traffic.waiting_suffices
    (weekly,) = traffic.attempts
    assert (weekly.block_days, weekly.now, weekly.left_out, weekly.after_windows_close) == (
        7,
        3.0,
        (),
        None,
    )


def test_the_plan_runs_at_the_traffic_needed_and_not_just_below_it(raw_spec) -> None:
    """Whole numbers of copies, which a factor of 3 is: 2 copies fail, 3 and 4 run."""
    assert not _evaluated(raw_spec, FLAT, FLAT, 35, 2).evaluated
    assert _evaluated(raw_spec, FLAT, FLAT, 35, 3).evaluated
    assert _evaluated(raw_spec, FLAT, FLAT, 35, 4).evaluated


def test_a_plan_of_8_weeks_is_priced_on_its_fortnights_because_they_pass_first(raw_spec) -> None:
    """Weekly cohorts of 10 need 6 times (the median); fortnightly cohorts of 20 need 1.5 times."""
    weekly = _flat(10, 8)

    plan, traffic = _traffic(raw_spec, weekly, weekly, 56)

    assert [(a.block_days, a.now) for a in traffic.attempts] == [(7, 6.0), (14, 1.5)]
    assert (traffic.now.factor, traffic.now.block_days) == (1.5, 14)
    assert {(b.kind, b.block_days, b.have, b.need) for b in traffic.now.binding} == {
        ("floor", 14, 20, 30)
    }
    # Both arms have 20 where 30 are wanted, in each of the four fortnights: a tie, both named.
    assert _sides(traffic.now.binding) == [(b, s) for b in range(4) for s in ("arm", "control")]


def test_the_block_length_changes_as_the_traffic_grows_and_the_plan_follows_its_own_order(
    raw_spec,
) -> None:
    """From 1.5 to 5 times the plan runs on 14-day blocks; from 6 times the weekly ones pass."""
    weekly = _flat(10, 8)

    lengths = {k: _evaluated(raw_spec, weekly, weekly, 56, k) for k in (1, 2, 5, 6, 7)}

    assert [(k, p.evaluated) for k, p in lengths.items()] == [
        (1, False),
        (2, True),
        (5, True),
        (6, True),
        (7, True),
    ]
    assert [lengths[k].block_days for k in (2, 5, 6, 7)] == [14, 14, 7, 7]


def test_spiky_arrivals_are_priced_from_the_weeks_that_were_thin(raw_spec) -> None:
    """Three big weeks pass the minimum but leave the second half of the window empty-handed."""
    spiky = {0: 100, 1: 100, 2: 100, 3: 10, 4: 10}

    plan, traffic = _traffic(raw_spec, spiky, spiky, 35)

    assert plan.reason == "cohorts_do_not_cover_the_window"
    assert (traffic.now.factor, traffic.now.block_days) == (3.0, 7)
    assert {(b.kind, b.block_days, b.have, b.need) for b in traffic.now.binding} == {
        ("floor", 7, 10, 30)
    }
    assert _sides(traffic.now.binding) == [(b, s) for b in (3, 4) for s in ("arm", "control")]
    assert not _evaluated(raw_spec, spiky, spiky, 35, 2).evaluated
    assert _evaluated(raw_spec, spiky, spiky, 35, 3).evaluated


def test_the_smaller_arm_is_named_and_the_floor_is_the_raised_one(raw_spec) -> None:
    """Control has 20 a week against the arm's 80: 4 to 1, so the floor is 98 for both, and
    control, the smaller, has to grow: 98 / 20 = 4.9 times."""
    plan, traffic = _traffic(raw_spec, _flat(80, 5), FLAT, 35)

    assert plan.floor == 98
    assert (traffic.now.factor, traffic.now.block_days) == (4.9, 7)
    assert {(b.kind, b.side, b.have, b.need) for b in traffic.now.binding} == {
        ("floor", "control", 20, 98)
    }
    assert not _evaluated(raw_spec, _flat(80, 5), FLAT, 35, 4).evaluated
    assert _evaluated(raw_spec, _flat(80, 5), FLAT, 35, 5).evaluated


def test_the_median_is_the_smaller_arms_size_in_each_week(raw_spec) -> None:
    """80 against 40 a week: the median of the smaller is 40, so 60 / 40 = 1.5, not the larger's."""
    plan, traffic = _traffic(raw_spec, _flat(80, 5), _flat(40, 5), 35)

    assert plan.floor == 43
    assert (traffic.now.factor, traffic.now.block_days) == (1.5, 7)
    (binding,) = traffic.now.binding
    assert (binding.kind, binding.have, binding.need) == ("weekly_median", 40, 60)


def test_the_factor_is_rounded_up_so_that_it_always_suffices(raw_spec) -> None:
    """Weeks 3 and 4 hold 22 where 30 are needed: 30 / 22 = 1.3636, reported as 1.37, not 1.36."""
    sizes = {0: 70, 1: 70, 2: 70, 3: 22, 4: 22}

    plan, traffic = _traffic(raw_spec, sizes, sizes, 35)

    assert plan.reason == "cohorts_do_not_cover_the_window"
    assert traffic.now.factor == 1.37
    exact, _ = _least(list(plan.attempts), plan)
    assert exact == Fraction(15, 11) and 22 * Fraction(str(traffic.now.factor)) >= 30


def test_a_factor_that_is_exact_is_not_rounded_away_from_itself(raw_spec) -> None:
    """30 / 20 is 1.5 exactly, however the float arithmetic would have gone."""
    sizes = {0: 70, 1: 70, 2: 70, 3: 20, 4: 20}

    _, traffic = _traffic(raw_spec, sizes, sizes, 35)

    assert traffic.now.factor == 1.5


def test_cohorts_that_are_empty_cannot_be_filled_by_more_of_the_same_traffic(raw_spec) -> None:
    """Players in the first three weeks only: the second half of the window has nobody."""
    early = _flat(80, 3)

    plan, traffic = _traffic(raw_spec, early, early, 35)

    assert plan.reason == "cohorts_do_not_cover_the_window"
    assert (traffic.now, traffic.after_windows_close, traffic.blocker) == (
        None,
        None,
        "empty_cohorts",
    )
    assert [(a.block_days, a.now, a.after_windows_close) for a in traffic.attempts] == [
        (7, None, None)
    ]
    assert not _evaluated(raw_spec, early, early, 35, 40).evaluated


def test_a_plan_with_too_few_weeks_is_a_matter_of_the_plan_and_not_of_traffic(raw_spec) -> None:
    plan, traffic = _traffic(raw_spec, _flat(80, 2), _flat(80, 2), 14)

    assert plan.reason == "window_holds_fewer_than_3_blocks"
    assert (traffic.now, traffic.blocker, traffic.attempts) == (None, "plan_too_short", ())


def test_arms_more_than_nine_to_one_apart_are_a_matter_of_allocation(raw_spec) -> None:
    plan, traffic = _traffic(raw_spec, _flat(100, 5), _flat(10, 5), 35)

    assert plan.reason == "allocation_too_unequal"
    assert (traffic.now, traffic.blocker, traffic.attempts) == (None, "arms_too_unequal", ())
    assert plan_cohorts(
        sized_context(raw_spec, _flat(100, 5), _flat(60, 5), days=35), "variant_b"
    ).evaluated


# --- Outcome windows that are still open ------------------------------------------------------


def test_when_only_the_open_windows_stand_in_the_way_waiting_is_the_remedy(raw_spec) -> None:
    """An export on day 19 cannot hold week 2's outcomes: with weeks 0 and 1 no multiple helps,
    and once week 2 is counted the plan runs at the traffic observed."""
    plan, traffic = _traffic(raw_spec, _flat(80, 3), _flat(80, 3), 21, exported_at=at(19))

    assert plan.reason == "outcome_window_incomplete"
    assert traffic.now is None and traffic.blocker is None
    assert (traffic.after_windows_close.factor, traffic.after_windows_close.block_days) == (1.0, 7)
    assert traffic.waiting_suffices
    (weekly,) = traffic.attempts
    assert (weekly.reason, weekly.left_out, weekly.now, weekly.after_windows_close) == (
        "outcome_window_incomplete",
        (2,),
        None,
        1.0,
    )


def test_cohorts_left_out_for_an_open_window_are_not_called_empty_and_the_price_comes_after(
    raw_spec,
) -> None:
    """Weeks 3 and 4 are thin and left out: with them out no multiple helps, and once they are
    counted it is 3 times. The same data exported later is priced the same, 3 times."""
    spiky = {0: 100, 1: 100, 2: 100, 3: 10, 4: 10}

    plan, traffic = _traffic(raw_spec, spiky, spiky, 35, exported_at=at(27))
    later_plan, later = _traffic(raw_spec, spiky, spiky, 35, exported_at=at(40))

    assert plan.attempts[0].incomplete == (3, 4)
    assert (traffic.now, traffic.blocker) == (None, None)
    assert (traffic.after_windows_close.factor, traffic.after_windows_close.block_days) == (3.0, 7)
    assert not traffic.waiting_suffices
    assert (later.now.factor, later.after_windows_close) == (3.0, None)


def test_a_block_length_that_only_waits_is_not_priced_as_if_nothing_helped(raw_spec) -> None:
    """Six weeks of 40, exported on day 40 so week 5's windows are open: weekly blocks need 1.5
    times for their median, 14-day blocks need no traffic once week 5 is counted."""
    sizes = _flat(40, 6)

    plan, traffic = _traffic(raw_spec, sizes, sizes, 42, exported_at=at(40))

    assert plan.reason == "cohorts_too_small_for_weekly_blocks"
    assert traffic.now.factor == 1.5 and traffic.now.block_days == 7
    assert traffic.waiting_suffices and traffic.after_windows_close.block_days == 14
    assert [
        (a.block_days, a.reason, a.left_out, a.now, a.after_windows_close) for a in traffic.attempts
    ] == [
        (7, "cohorts_too_small_for_weekly_blocks", (5,), 1.5, 1.5),
        (14, "outcome_window_incomplete", (2,), None, 1.0),
    ]
    assert (
        plan_cohorts(
            sized_context(raw_spec, sizes, sizes, days=42, exported_at=at(50)), "variant_b"
        ).block_days
        == 14
    )


def test_every_week_left_out_for_one_block_length_does_not_make_the_plan_unfillable(
    raw_spec,
) -> None:
    """Eight weeks of 20, exported on day 30: no week is counted in the second half, so with
    them out nothing helps; once counted, 14-day blocks run at the traffic observed."""
    sizes = _flat(20, 8)

    plan, traffic = _traffic(raw_spec, sizes, sizes, 56, exported_at=at(30))

    assert (traffic.now, traffic.blocker) == (None, None)
    assert traffic.waiting_suffices and traffic.after_windows_close.block_days == 14
    assert traffic.attempts[0].left_out == (4, 5, 6, 7) and traffic.attempts[1].left_out == (2, 3)


def test_a_cohort_left_out_is_never_named_as_what_sets_the_traffic(raw_spec) -> None:
    """Week 4 is left out; weeks 3 and 4 hold 20 each and week 3 is needed: only it is named."""
    sizes = {0: 100, 1: 100, 2: 100, 3: 20, 4: 20}

    plan, traffic = _traffic(raw_spec, sizes, sizes, 35, exported_at=at(33))

    assert plan.attempts[0].incomplete == (4,)
    assert traffic.now.factor == 1.5
    assert _sides(traffic.now.binding) == [(3, "arm"), (3, "control")]
    assert traffic.after_windows_close.factor == 1.5


# --- The price is the plan's, not the cheaper block length's -----------------------------------


def _union_case():
    """22 weekly blocks and the 11 fortnights they make, preferred minima 100 and 200: the
    weekly attempt passes from 15/14, fails from 20/17 (the 90% guard) and passes from 15/7;
    the 14-day attempt passes from 10/9. The plan passes from 15/14 on, with weekly blocks."""
    weekly = {b: (150, 150) for b in range(9)}
    weekly |= {9: (85, 85), 10: (85, 85), 11: (28, 28), 12: (14, 14), 13: (13, 13)}
    fortnights: dict[int, tuple[int, int]] = {}
    for block, (arm, control) in weekly.items():
        had = fortnights.get(block // 2, (0, 0))
        fortnights[block // 2] = (had[0] + arm, had[1] + control)
    a7 = _made(weekly, window_blocks=22, preferred=(100, 100))
    a14 = _made(fortnights, window_blocks=11, block_days=14, preferred=(200, 200))
    return a7, a14, _plan_of(a7, a14)


def test_the_plan_passes_when_either_block_length_does_and_is_priced_that_way() -> None:
    a7, a14, plan = _union_case()

    weekly = _least([a7], plan)
    fortnight = _least([a14], plan)
    both = _least([a7, a14], plan)

    assert (weekly[0], fortnight[0], both[0]) == (
        Fraction(15, 7),
        Fraction(10, 9),
        Fraction(15, 14),
    )
    traffic = traffic_needed(plan)
    assert (traffic.now.factor, traffic.now.block_days) == (1.08, 7)
    assert [(a.block_days, a.now) for a in traffic.attempts] == [(7, 2.15), (14, 1.12)]
    assert {(b.block_days, b.block, b.have, b.need) for b in traffic.now.binding} == {
        (7, 11, 28, 30)
    }
    assert [_runs(a7, plan, Fraction(f)) for f in ("1", "15/14", "20/17", "15/7")] == [
        False,
        True,
        False,
        True,
    ]


def test_the_block_length_named_is_the_one_the_plan_uses_at_the_multiple_priced() -> None:
    """Weekly and 14-day blocks both reach 3 times together: the plan tries weekly first."""
    weekly = _made({b: (20, 20) for b in range(5)}, window_blocks=8)
    fortnight = _made({b: (10, 10) for b in range(4)}, window_blocks=4, block_days=14)
    plan = _plan_of(weekly, fortnight)

    traffic = traffic_needed(plan)

    assert (traffic.now.factor, traffic.now.block_days) == (3.0, 7)
    assert [(a.block_days, a.now) for a in traffic.attempts] == [(7, 3.0), (14, 3.0)]
    swapped = traffic_needed(_plan_of(fortnight, weekly))
    assert (swapped.now.factor, swapped.now.block_days) == (3.0, 14)


def test_the_sizes_named_are_those_of_the_block_length_that_passes() -> None:
    """The 14-day attempt has a breakpoint at 3 as well (its first cohort reaches 30 then) but
    does not pass there, with 5 players in the others: only the weekly median is named."""
    weekly = _made({b: (20, 20) for b in range(5)}, window_blocks=8)
    thin = _made({0: (10, 10), 1: (5, 5), 2: (5, 5), 3: (5, 5)}, window_blocks=4, block_days=14)
    plan = _plan_of(weekly, thin)

    least, binding = _least([weekly, thin], plan)

    assert least == 3
    assert any(at == 3 for at, _ in _breakpoints(thin, plan))
    assert [(b.kind, b.block_days) for b in binding] == [("weekly_median", 7)]


# --- Where more traffic first helps and then does not -----------------------------------------


def _island():
    """Eleven usable weeks in a 20-week plan; eight reach the preferred 100, two do at 1.12 times,
    and the last, in the second half, has 28 and reaches the floor at 1.08 but 100 only at 3.58."""
    sizes = {b: (150, 150) for b in range(8)} | {8: (90, 90), 9: (90, 90), 10: (28, 28)}
    attempt = _made(sizes, window_blocks=20, preferred=(100, 100))
    return attempt, _plan_of(attempt)


def _island_of_a_short_plan():
    """A 28-day plan (4 weekly blocks) whose arrivals run for 14 weeks: blocks after the window
    count as its second half. Block 0, the only one in the first half to reach the floor, reaches
    the preferred 100 only at 20/3 times; from 100/34 to there the 90% guard drops it from
    the plan, and before 100/34 the floor is used and it is in."""
    sizes = {0: (15, 15), **{b: (50, 50) for b in range(2, 12)}, 12: (34, 34), 13: (34, 34)}
    attempt = _made(sizes, window_blocks=4, preferred=(100, 100))
    return attempt, _plan_of(attempt)


def test_a_plan_can_pass_at_one_traffic_and_fail_at_a_larger_one() -> None:
    attempt, plan = _island()

    runs = {f: _runs(attempt, plan, Fraction(f)) for f in ("1", "1.08", "1.2", "3.6")}

    assert runs == {"1": False, "1.08": True, "1.2": False, "3.6": True}


def test_it_does_not_take_a_long_plan_for_it_a_short_one_with_a_long_run_does_it_too() -> None:
    attempt, plan = _island_of_a_short_plan()

    runs = {k: _runs(attempt, plan, Fraction(k)) for k in range(1, 9)}

    assert list(runs.values()) == [False, True, False, False, False, False, True, True]


@pytest.mark.parametrize("which", [_island, _island_of_a_short_plan])
def test_the_traffic_needed_is_the_least_from_which_the_plan_keeps_running(which) -> None:
    """Not where it first passes, but after the last factor at which it fails."""
    attempt, plan = which()

    least, binding = _least([attempt], plan)

    assert least in (Fraction(100, 28), Fraction(20, 3))
    assert {(b.kind, b.have, b.need) for b in binding} <= {
        ("preferred", 28, 100),
        ("preferred", 15, 100),
    }
    for factor in (least, least + Fraction(1, 7), 2 * least, 50 * least):
        assert _runs(attempt, plan, factor)
    assert not _runs(attempt, plan, least - Fraction(1, 10**6))


def test_a_plan_that_passes_as_observed_is_priced_at_one_even_if_more_would_fail() -> None:
    """The island, but with week 10 already at the floor: the plan passes as observed, fails at
    1.2 times and passes again from 3.58. A price of 1 says only the first of these."""
    sizes = {b: (150, 150) for b in range(8)} | {8: (90, 90), 9: (90, 90), 10: (30, 30)}
    attempt = _made(sizes, window_blocks=20, preferred=(100, 100))
    plan = _plan_of(attempt)

    assert _runs(attempt, plan, Fraction(1)) and not _runs(attempt, plan, Fraction(6, 5))
    assert _least([attempt], plan) == (1, ())


def test_the_first_pass_is_given_beside_the_multiple_it_keeps_passing_from() -> None:
    attempt, plan = _island()

    traffic = traffic_needed(plan)

    assert (traffic.now.factor, traffic.now.first_pass) == (3.58, 1.08)
    assert _runs(attempt, plan, Fraction("1.08")) and not _runs(attempt, plan, Fraction("1.2"))


def test_a_plan_that_keeps_passing_from_its_first_pass_names_no_earlier_one(raw_spec) -> None:
    _, traffic = _traffic(raw_spec, FLAT, FLAT, 35)

    assert traffic.now.first_pass is None


def test_a_preferred_minimum_equal_to_the_floor_is_named_once() -> None:
    """The arm's preferred minimum is the floor 30 and control's is 100: the arm's 10 where 30 are
    wanted is one size, named as the floor's, not again as the preferred minimum's."""
    attempt = _made(
        {b: (10, 40) for b in range(3)}, window_blocks=3, block_days=14, preferred=(30, 100)
    )
    plan = _plan_of(attempt)

    least, binding = _least([attempt], plan)

    assert least == 3
    assert {(b.kind, b.side, b.have, b.need) for b in binding} == {("floor", "arm", 10, 30)}


def test_a_first_pass_that_rounds_to_the_price_is_not_named_beside_it() -> None:
    """The first pass, 15/14, and a price of 1.075 both round up to 1.08: one figure, once."""
    attempt, plan = _island()

    price = _price([attempt], plan, (Fraction(1075, 1000), ()))

    assert _first_pass([attempt], plan) == Fraction(15, 14)
    assert (price.factor, price.first_pass) == (1.08, None)


def test_a_first_pass_is_only_named_if_the_plan_passes_at_the_figure_printed() -> None:
    """The plan passes from 15/14 but only until 1.0753, where weeks 8 and 9 reach the preferred
    100: rounded up, 1.08 is already a failure, so it is not named."""
    sizes = {b: (150, 150) for b in range(8)} | {8: (93, 93), 9: (93, 93), 10: (28, 28)}
    attempt = _made(sizes, window_blocks=20, preferred=(100, 100))
    plan = _plan_of(attempt)

    traffic = traffic_needed(plan)

    assert _first_pass([attempt], plan) == Fraction(15, 14)
    assert _runs(attempt, plan, Fraction(15, 14)) and not _runs(attempt, plan, Fraction("1.08"))
    assert (traffic.now.factor, traffic.now.first_pass) == (3.58, None)


def test_a_size_that_only_one_arm_has_reached_is_not_named_at_the_price() -> None:
    """In block 4 the arm reaches 30 at 1.5 times but control, with 15, only at 2: not usable at
    the price of 1.5, which block 5 sets, so only block 5 is named."""
    attempt = _made(
        {0: (100, 100), 1: (100, 100), 2: (100, 100), 4: (20, 15), 5: (20, 20)},
        window_blocks=8,
        block_days=14,
    )

    least, binding = _least([attempt], _plan_of(attempt))

    assert least == Fraction(3, 2)
    assert _sides(binding) == [(5, "arm"), (5, "control")]


def test_the_floor_is_priced_when_the_preferred_minimum_was_in_use_and_the_window_is_not_covered(
    raw_spec,
) -> None:
    """A registered size of about 1,100 asks for 55 players a cohort; weeks 0 to 2 have 100, so
    the preferred minimum is kept and weeks 3 and 4, with 10, are not covered. They need the
    floor of 30, 3 times, and not the 55 that was in use, 5.5 times."""
    spiky = {0: 100, 1: 100, 2: 100, 3: 10, 4: 10}

    plan, traffic = _traffic(raw_spec, spiky, spiky, 35, design__mde_relative=0.06)

    (attempt,) = plan.attempts
    assert attempt.preferred_used and attempt.minimum_arm.used == 55
    assert traffic.now.factor == 3.0
    assert {(b.kind, b.need) for b in traffic.now.binding} == {("floor", 30)}


def test_the_first_pass_may_belong_to_the_second_block_length() -> None:
    """Weekly blocks never pass; 14-day blocks pass from 15/14 and keep passing from 3.58."""
    nothing = _made({}, window_blocks=8)
    sizes = {b: (150, 150) for b in range(8)} | {8: (90, 90), 9: (90, 90), 10: (28, 28)}
    fortnights = _made(sizes, window_blocks=20, block_days=14, preferred=(100, 100))
    plan = _plan_of(nothing, fortnights)

    traffic = traffic_needed(plan)

    assert _first_pass([nothing, fortnights], plan) == Fraction(15, 14)
    assert (traffic.now.factor, traffic.now.block_days, traffic.now.first_pass) == (3.58, 14, 1.08)
    assert [(a.block_days, a.now) for a in traffic.attempts] == [(7, None), (14, 3.58)]


def test_the_block_length_named_is_the_one_the_plan_uses_at_the_price_printed() -> None:
    """Fortnights of 996 where 1,000 are wanted pass from 250/249 (1.0040); weekly blocks of 995
    only from 200/199 (1.0050). Both round up to 1.01, where the plan tries weekly blocks first
    and they pass: the price says weekly, though at 250/249 only the fortnights pass."""
    weekly = _made({b: (995, 995) for b in range(5)}, window_blocks=5, floor=1000)
    fortnights = _made(
        {b: (996, 996) for b in range(4)}, window_blocks=4, block_days=14, floor=1000
    )
    plan = _plan_of(weekly, fortnights, floor=1000)

    traffic = traffic_needed(plan)

    assert _least([weekly, fortnights], plan)[0] == Fraction(250, 249)
    assert not _runs(weekly, plan, Fraction(250, 249)) and _runs(
        fortnights, plan, Fraction(250, 249)
    )
    assert (traffic.now.factor, traffic.now.block_days) == (1.01, 7)


# --- Asymmetric minimums, and what the breakpoints must not forget ----------------------------


def test_a_preferred_minimum_that_only_control_misses_sets_the_traffic() -> None:
    """Control has 10 where 100 are preferred in the one block that reaches the floor in the
    first half of the window: the answer is 10, naming control."""
    attempt = _made(
        {0: (100, 10)} | {b: (100, 40) for b in range(2, 11)},
        window_blocks=3,
        block_days=14,
        preferred=(30, 100),
    )
    plan = _plan_of(attempt)

    least, binding = _least([attempt], plan)

    assert least == 10
    assert [(b.kind, b.block, b.side, b.have, b.need) for b in binding] == [
        ("preferred", 0, "control", 10, 100)
    ]


def test_each_arm_is_judged_against_its_own_preferred_minimum() -> None:
    """The arm prefers 100 and has 90, control prefers 30 and has 40: only the arm is short."""
    attempt = _made(
        {0: (90, 40)} | {b: (120, 40) for b in range(2, 11)},
        window_blocks=3,
        block_days=14,
        preferred=(100, 30),
    )
    plan = _plan_of(attempt)

    assert not _runs(attempt, plan, Fraction(1))
    assert _runs(attempt, plan, Fraction(10, 9))
    least, binding = _least([attempt], plan)
    assert least == Fraction(10, 9)
    assert [(b.side, b.have, b.need) for b in binding] == [("arm", 90, 100)]


def test_a_cohort_left_out_has_no_breakpoint_of_its_own() -> None:
    attempt = _made(
        {b: (20, 20) for b in range(5)}, window_blocks=5, block_days=14, incomplete=(4,)
    )
    plan = _plan_of(attempt)

    named = {binding.block for _, binding in _breakpoints(attempt, plan)}

    assert named == {0, 1, 2, 3}


def test_a_cohort_with_nobody_in_an_arm_has_no_breakpoint() -> None:
    attempt = _made({0: (20, 0), 1: (0, 20), 2: (20, 20)}, window_blocks=3, block_days=14)

    named = {binding.block for _, binding in _breakpoints(attempt, _plan_of(attempt))}

    assert named == {2}


def test_the_median_is_exact_for_whatever_numbers_it_is_given() -> None:
    sizes = {
        0: {"a": 10, "c": 12},
        1: {"a": 21, "c": 30},
        2: {"a": 30, "c": 31},
        3: {"a": 50, "c": 40},
    }

    assert _median_smaller(sizes, "a", "c", 4) == 25.5
    assert _median_smaller(sizes, "a", "c", 6) == 15.5
    scaled = {b: {k: Fraction(1, 3) * v for k, v in found.items()} for b, found in sizes.items()}
    assert _median_smaller(scaled, "a", "c", 4) == Fraction(51, 6)
    assert _median_smaller({}, "a", "c", 0) == 0


# --- Against the plan's own rules, on random cases --------------------------------------------


def _random_attempt(
    rng: random.Random, *, floor: int, block_days: int, overshoot: bool = False
) -> Attempt:
    """A random attempt. With `overshoot`, sizes cluster around the floor and the preferred
    minimum and arrivals run past the end of the window, which is what lets the preferred
    minimum be judged again as cohorts grow."""
    window = rng.randint(3, 8) if overshoot else rng.randint(3, 14)
    preferred = floor + rng.choice([0, 20, 40, 70])
    preferred_control = rng.choice([preferred, floor + rng.randint(0, 80)])
    if overshoot:
        count = window + rng.randint(0, 14)

        def size() -> int:
            return rng.choice(
                [
                    0,
                    rng.randint(1, floor - 1),
                    rng.randint(floor, preferred),
                    rng.randint(preferred, 160),
                ]
            )

    else:
        count = window + rng.randint(0, 2)

        def size() -> int:
            return rng.choice([0, rng.randint(1, 160)])

    sizes = {block: (size(), size()) for block in range(count) if rng.random() < 0.9}
    incomplete = tuple(block for block in sizes if rng.random() < 0.1)
    return _made(
        sizes,
        window_blocks=window,
        block_days=block_days,
        floor=floor,
        preferred=(preferred, preferred_control),
        incomplete=incomplete,
    )


def _random_plan(rng: random.Random, **kw) -> tuple[list[Attempt], CohortPlan]:
    """A plan with a weekly attempt and, half the time, a 14-day one, each from its own sizes."""
    floor = rng.choice([30, 30, 43, 69])
    attempts = [_random_attempt(rng, floor=floor, block_days=7, **kw)]
    if rng.random() < 0.5:
        attempts.append(_random_attempt(rng, floor=floor, block_days=14, **kw))
    return attempts, _plan_of(*attempts, floor=floor)


def _passes(attempts, plan, factor):
    return any(_runs(a, plan, factor) for a in attempts)


@pytest.mark.parametrize("overshoot", [False, True])
def test_the_least_factor_is_where_the_plan_starts_to_pass_and_keeps_passing(overshoot) -> None:
    rng = random.Random(20261012 + overshoot)
    feasible = infeasible = islands = 0
    for _ in range(1500):  # the 3,000 drawn before found no island that these do not
        attempts, plan = _random_plan(rng, overshoot=overshoot)
        found = _least(attempts, plan)
        points = sorted({at for a in attempts for at, _ in _breakpoints(a, plan)} | {Fraction(1)})
        top = max(points)
        if found is None:
            infeasible += 1
            assert not _passes(attempts, plan, top) and not _passes(attempts, plan, 1000 * top)
            continue
        feasible += 1
        least, binding = found
        assert least >= 1 and _passes(attempts, plan, least)
        if least == 1:
            # Passing at the observed sizes is all that a price of 1 says (see `_least`).
            continue
        if least > 1:
            assert not _passes(attempts, plan, least - Fraction(1, 10**6))
            assert binding
            for b in binding:
                wanted = Fraction(b.need) / Fraction(b.have)
                assert wanted == least, (b, least)
        for factor in points + [top + 1, 1000 * top]:
            if factor >= least:
                assert _passes(attempts, plan, factor), (factor, least)
        if overshoot:  # only the overshoot plans are judged for islands, so only they pay for it
            first_pass = next(v for v in points if _passes(attempts, plan, v))
            islands += first_pass < least
    assert feasible > 150 and infeasible > 50
    # The generator built for them reaches plans that pass and then fail, so the property above
    # is judged on those too.
    assert islands > 0 or not overshoot


def test_every_decision_of_the_plan_flips_only_at_a_breakpoint() -> None:
    """Between two neighbouring breakpoints the outcome does not change, which is what lets
    the search judge the breakpoints alone: checked on a grid of fractions."""
    rng = random.Random(99)
    for overshoot in (False, True):
        for _ in range(200):
            attempts, plan = _random_plan(rng, overshoot=overshoot)
            points = sorted(
                {at for a in attempts for at, _ in _breakpoints(a, plan) if at >= 1} | {Fraction(1)}
            )
            for low, high in zip(points, points[1:], strict=False):
                inside = [low + (high - low) * Fraction(k, 5) for k in range(5)]
                assert len({_passes(attempts, plan, factor) for factor in inside}) == 1


def test_the_rules_applied_to_scaled_sizes_are_those_of_the_real_plan(raw_spec) -> None:
    """`_runs` at a whole number of copies agrees with the real attempt on a real context of
    that many copies of every player, with unequal registered sizes, a preferred minimum that
    matters, and an export that leaves cohorts out."""
    rng = random.Random(5)
    cases = checked = 0
    while cases < 30:
        weeks = rng.choice([5, 6, 8, 9])
        days = rng.choice([35, 42, 56, 63])
        arm = {b: rng.choice([0, rng.randint(3, 45)]) for b in range(weeks)}
        control = {b: rng.choice([0, rng.randint(3, 45)]) for b in range(weeks)}
        if not any(arm.values()) or not any(control.values()):
            continue
        cases += 1
        more = {
            "arms": THREE_ARMS,
            "design__mde_relative": rng.choice([2.0, 0.1, 0.05]),
            "exported_at": rng.choice([None, at(days * 0.6), at(days * 0.85)]),
        }
        base = sized_context(raw_spec, arm, control, days=days, **more)
        plan = plan_cohorts(base, "variant_b")
        for block_days in (7, 14):
            seen = _attempt(base, "variant_b", block_days, plan.floor, plan.as_of)
            for copies in (1, 2, 3, 5):
                real = sized_context(raw_spec, arm, control, days=days, copies=copies, **more)
                scaled = _attempt(real, "variant_b", block_days, plan.floor, plan.as_of)
                assert _runs(seen, plan, Fraction(copies)) == (scaled.reason is None), (
                    arm,
                    control,
                    days,
                    block_days,
                    copies,
                    more,
                )
                checked += 1
    assert checked == 30 * 2 * 4


def test_a_plan_with_the_traffic_multiplied_runs_from_the_factor_on(raw_spec) -> None:
    """The same players, each present `k` times, are a plan whose cohorts are exactly `k` times
    as large; it runs from the factor on, and a plan with no factor does not run at 12 times."""
    rng = random.Random(7)
    checked = {"runs": 0, "blocked": 0}
    for _ in range(60):
        weeks = rng.choice([5, 6, 8, 9])
        days = rng.choice([35, 42, 56, 63])
        arm = {b: rng.choice([0, rng.randint(3, 40)]) for b in range(weeks)}
        control = {b: rng.choice([0, rng.randint(3, 40)]) for b in range(weeks)}
        if not any(arm.values()) or not any(control.values()):
            continue
        plan, traffic = _traffic(raw_spec, arm, control, days)
        if traffic is None or traffic.blocker in ("plan_too_short", "arms_too_unequal"):
            continue
        if traffic.now is None:
            assert not _evaluated(raw_spec, arm, control, days, 12).evaluated
            checked["blocked"] += 1
            continue
        for copies in range(_copies(traffic.now.factor), _copies(traffic.now.factor) + 3):
            assert _evaluated(raw_spec, arm, control, days, copies).evaluated, (
                arm,
                control,
                days,
                traffic.now.factor,
                copies,
            )
        checked["runs"] += 1
    assert checked["runs"] > 10 and checked["blocked"] > 3


def test_the_number_of_copies_is_counted_exactly() -> None:
    assert [_copies(f) for f in (1.0, 1.01, 2.0, 2.01, 3.0, 4.9)] == [1, 2, 2, 3, 3, 5]
