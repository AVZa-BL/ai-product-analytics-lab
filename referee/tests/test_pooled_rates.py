"""The table RES-008 quotes, and the lookup that places a comparison in it (design 21.11)."""

import bisect
import json
import random
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pooled_rates_table as generator
import pytest

from referee import pooled_rates, pooled_rates_table
from referee.pooled_rates import (
    CASES,
    EXCESS_RATE,
    NOMINAL_RATE,
    RISE_MARGIN,
    UNIT,
    Case,
    SimulatedRange,
    hull,
    lookup,
    percent,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "docs/simulations/pooled_effect_heavy.json").read_text(encoding="utf-8"))
TABLE_PATH = ROOT / "src/referee/pooled_rates_table.py"


# --- The table is the study's ----------------------------------------------------------------


def test_the_committed_table_is_what_the_generator_makes_from_the_committed_study() -> None:
    assert TABLE_PATH.read_text(encoding="utf-8") == generator.render(DATA)


def test_the_command_that_the_table_names_makes_the_table() -> None:
    made = subprocess.run(
        [sys.executable, "tests/pooled_rates_table.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert made == TABLE_PATH.read_text(encoding="utf-8")
    assert "python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py" in made
    assert pooled_rates_table.SOURCE == generator.SOURCE
    assert pooled_rates_table.SEED == DATA["seed"] and pooled_rates_table.UNIT == generator.UNIT


def _oracle() -> dict[tuple, list[float]]:
    """The cases worked out again from the raw cells, one cell at a time."""
    found: dict[tuple, list[float]] = {}
    for cell in DATA["cells"]:
        if cell["outcome"] not in ("revenue_mild", "revenue", "revenue_heavy"):
            continue
        arm, control, effect = cell["arm_n"], cell["control_n"], cell["effect"]
        effects = "small" if effect in (0.0, 0.2) else "large"
        small = min(arm, control)
        split = Fraction(max(arm, control), small)
        share = cell.get("paying", 0.13)
        payers = int(share * small + 0.5)
        rate = Fraction(cell["welch_above_n"] + cell["welch_below_n"], cell["reps"])
        sides = []
        if arm == control:
            sides = ["equal"]
        elif arm > control:
            sides = ["arm"] + (["control"] if effect == 0.0 else [])
        else:
            assert effect != 0.0
            sides = ["control"]
        for side in sides:
            found.setdefault((effects, side, split, payers), []).append((rate, cell))
    return found


def test_every_case_of_the_table_is_the_lowest_and_highest_rate_of_its_cells() -> None:
    oracle = _oracle()

    assert len(CASES) == len(oracle) == 100
    for case in CASES:
        cells = oracle[case.effects, case.larger, case.split, case.payers]
        rates = [rate for rate, _ in cells]
        assert Fraction(case.low, UNIT) == min(rates), case
        assert Fraction(case.high, UNIT) == max(rates), case
        assert case.cells == len(cells)
        assert case.tails == len({cell["outcome"] for _, cell in cells})
        assert case.min_runs == min(cell["reps"] for _, cell in cells)
        assert case.shared == sum(
            1 for _, cell in cells if cell["effect"] == 0.0 and case.larger != "equal"
        )
    assert {c.tails for c in CASES} == {2, 3} and {c.min_runs for c in CASES} == {2000, 20000}


def test_the_cases_that_are_in_the_table_and_the_ones_that_are_not() -> None:
    small = {(c.larger, c.split) for c in CASES if c.effects == "small"}
    large = {(c.larger, c.split) for c in CASES if c.effects == "large"}
    grid = [Fraction(x) for x in (Fraction(3, 2), 2, Fraction(5, 2), 3, 4, 9)]

    assert small == {("equal", Fraction(1))} | {
        (side, s) for side in ("arm", "control") for s in grid
    }
    assert large == {("equal", Fraction(1))} | {
        (side, Fraction(s)) for side in ("arm", "control") for s in (3, 9)
    }
    assert {c.payers for c in CASES if c.effects == "large"} == {13, 130}  # 100 and 1,000 players
    assert all(c.low <= c.high and c.cells >= 1 for c in CASES)
    assert (UNIT, NOMINAL_RATE, EXCESS_RATE) == (100_000, 5_000, 7_500)


@pytest.mark.parametrize(
    ("effects", "larger", "floor"),
    [
        ("small", "arm", True),
        ("small", "control", True),
        ("large", "control", True),
        ("large", "arm", False),
    ],
)
def test_beyond_the_largest_split_the_range_is_a_floor_only_where_the_highest_rates_rose(
    effects: str, larger: str, floor: bool
) -> None:
    rows = [c for c in CASES if c.effects == effects and c.larger in (larger, "equal")]
    splits = sorted({c.split for c in rows})
    before, last = (max(c.high for c in rows if c.split == s) for s in splits[-2:])

    assert (last > before) == floor
    found = lookup(effects, larger, splits[-1] * 2, 130)  # type: ignore[arg-type]
    assert found.extrapolated == ("split_above_range",) and found.floor_only == floor


def test_a_floor_is_claimed_only_where_the_table_shows_rates_rising_that_way() -> None:
    assert lookup("small", "arm", Fraction(19), 130).floor_only  # a 5% holdout
    assert lookup("small", "control", Fraction(19), 130).floor_only
    assert lookup("large", "control", Fraction(20), 13).floor_only
    assert not lookup("large", "arm", Fraction(20), 13).floor_only  # 9 to 1 was below 3 to 1
    # fewer players who spend than any case: a floor where the rates fell with more of them
    assert lookup("small", "control", Fraction(3), 4).floor_only
    assert lookup("small", "arm", Fraction(3), 4).floor_only
    # ... and not at 1.5 to 1 with the arm the larger, where they did not
    assert (
        _case("small", "arm", Fraction(3, 2), 13).high
        < _case("small", "arm", Fraction(3, 2), 390).high
    )
    assert not lookup("small", "arm", Fraction(3, 2), 4).floor_only
    # inside the grid, or beyond it with more players who spend, there is no floor
    assert not lookup("small", "arm", Fraction(3), 130).floor_only
    assert not lookup("small", "arm", Fraction(3), 50_000).floor_only


def test_fewer_players_is_a_floor_only_if_the_rates_fell_with_more_at_every_split() -> None:
    mixed = lookup("small", "arm", Fraction(11, 4), 4)  # between 5 to 2, where they did not, and 3
    single = lookup("small", "arm", Fraction(3), 4)

    assert {c.split for c in mixed.cases} == {Fraction(5, 2), Fraction(3)}
    assert mixed.extrapolated == ("payers_below_range",) and mixed.rising == ()
    assert not mixed.floor_only
    assert single.extrapolated == ("payers_below_range",) and single.rising == single.extrapolated
    assert single.floor_only


def test_a_floor_needs_every_direction_beyond_the_grid_to_be_one_the_rates_rose_in() -> None:
    both = lookup("small", "control", Fraction(19), 4)  # the split and the players, both beyond

    assert both.extrapolated == ("split_above_range", "payers_below_range")
    assert both.rising == both.extrapolated and both.floor_only
    inside = lookup("small", "control", Fraction(3), 130)
    assert inside.extrapolated == () and inside.rising == () and not inside.floor_only


def test_a_direction_is_rising_only_if_the_highest_rate_rose_by_more_than_a_point(
    monkeypatch,
) -> None:
    assert RISE_MARGIN == UNIT // 100 == 1000

    def table(top: int) -> tuple[Case, ...]:
        return tuple(
            Case("small", "arm", Fraction(split), payers, 4000, high, 6, 3, 20000, 0)
            for split, payers, high in (
                (2, 13, 6000),
                (2, 39, 6000),
                (3, 13, 6000 + top),
                (3, 39, 6000),
            )
        )

    for rise, floor in ((RISE_MARGIN - 1, False), (RISE_MARGIN, False), (RISE_MARGIN + 1, True)):
        monkeypatch.setattr(pooled_rates, "CASES", table(rise))
        found = lookup("small", "arm", Fraction(5), 39)
        assert found.extrapolated == ("split_above_range",)
        assert found.floor_only is floor, rise
    # in the table itself: a rise of 0.18 and 0.69 points is not enough
    monkeypatch.undo()
    assert lookup("small", "arm", Fraction(2), 4).rising == ()
    assert lookup("small", "arm", Fraction(5, 2), 4).rising == ()
    assert lookup("small", "arm", Fraction(3), 4).rising == ("payers_below_range",)


# --- The rates print exactly ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "text"),
    [
        (0, "0.0%"),
        (5000, "5.0%"),
        (5149, "5.1%"),
        (5150, "5.2%"),  # half rounds up
        (5155, "5.2%"),
        (4949, "4.9%"),
        (12345, "12.3%"),
        (34200, "34.2%"),
        (100000, "100.0%"),
    ],
)
def test_a_rate_prints_to_one_decimal_rounded_half_up(rate: int, text: str) -> None:
    assert percent(rate) == text


# --- The lookup ------------------------------------------------------------------------------


def _case(effects: str, larger: str, split, payers: int):
    (found,) = [
        c
        for c in CASES
        if (c.effects, c.larger, c.split, c.payers) == (effects, larger, Fraction(split), payers)
    ]
    return found


def test_a_comparison_on_the_grid_gets_its_own_case() -> None:
    case = _case("small", "arm", 3, 39)

    found = lookup("small", "arm", Fraction(3), 39)

    assert found.cases == (case,) and (found.low, found.high) == (case.low, case.high)
    assert (case.low, case.high) == (3530, 6755)
    assert found.extrapolated == () and not found.floor_only
    assert found.cells == 6 and found.tails == (3, 3) and found.min_runs == 20000


def test_between_two_player_counts_the_range_is_the_hull_of_both() -> None:
    found = lookup("small", "arm", Fraction(3), 50)  # between 39 and 90 at 3 to 1

    assert {c.payers for c in found.cases} == {39, 90}
    assert found.low == min(3530, 4260) and found.high == max(6755, 6665)
    assert found.extrapolated == ()


def test_between_two_splits_the_range_is_the_hull_of_both_with_each_count_bracketed() -> None:
    found = lookup("small", "control", Fraction(11, 5), 100)  # 2.2: between 2 and 2.5

    assert {(c.split, c.payers) for c in found.cases} == {
        (Fraction(2), 39),
        (Fraction(2), 130),
        (Fraction(5, 2), 39),
        (Fraction(5, 2), 130),
    }
    assert found.low == min(c.low for c in found.cases)
    assert found.high == max(c.high for c in found.cases)


def test_a_split_just_above_one_is_bracketed_by_equal_arms_and_the_next_split() -> None:
    found = lookup("small", "arm", Fraction(21, 20), 130)

    assert {(c.larger, c.split) for c in found.cases} == {
        ("equal", Fraction(1)),
        ("arm", Fraction(3, 2)),
    }
    assert found.extrapolated == ()


def test_equal_arms_use_the_cases_of_equal_arms() -> None:
    found = lookup("small", "equal", Fraction(1), 100)  # between 90 and 130

    assert {c.larger for c in found.cases} == {"equal"}
    assert {c.payers for c in found.cases} == {90, 130}


def test_the_arm_and_the_control_the_larger_are_different_cases() -> None:
    arm = lookup("small", "arm", Fraction(3), 39)
    control = lookup("small", "control", Fraction(3), 39)

    assert control.high > arm.high and (control.low, control.high) == (6105, 10765)
    assert (arm.high, control.high) == (6755, 10765)  # 6.8% against 10.8%: either side of 7.5%
    assert arm.high <= EXCESS_RATE < control.high


def test_beyond_the_largest_split_the_edge_is_used_and_it_is_a_floor() -> None:
    found = lookup("small", "arm", Fraction(19), 130)  # a 5% holdout

    assert {c.split for c in found.cases} == {Fraction(9)}
    assert found.extrapolated == ("split_above_range",) and found.floor_only


def test_short_of_the_fewest_players_who_spend_the_edge_is_used_and_it_is_a_floor() -> None:
    found = lookup("small", "control", Fraction(3), 4)

    assert {c.payers for c in found.cases} == {9}
    assert found.extrapolated == ("payers_below_range",) and found.floor_only


def test_with_more_players_who_spend_than_simulated_the_edge_is_a_ceiling_not_a_floor() -> None:
    found = lookup("small", "arm", Fraction(3), 50_000)

    assert {c.payers for c in found.cases} == {13_000}
    assert found.extrapolated == ("payers_above_range",) and not found.floor_only


# --- The hull of two readings of one comparison ------------------------------------------------


def test_the_hull_of_two_ranges_holds_the_lowest_and_the_highest_of_both_with_every_case() -> None:
    as_arm = lookup("small", "arm", Fraction(3), 50)
    as_control = lookup("small", "control", Fraction(3), 50)

    both = hull(as_arm, as_control)

    assert both.larger == "either" and both.effects == "small"
    assert both.low == min(as_arm.low, as_control.low)
    assert both.high == max(as_arm.high, as_control.high)
    assert set(both.cases) == set(as_arm.cases) | set(as_control.cases)
    assert len(both.cases) == 4  # two player counts at one split, read two ways
    assert both.extrapolated == () and not both.floor_only
    assert both.cells == _distinct_cells(both) == 15  # not 20: the cells with no effect are shared
    assert both.overlap == 5 and as_arm.overlap == as_control.overlap == 0


def _distinct_cells(found: SimulatedRange) -> int:
    """The cells of the study, counted once each, behind the cases of a range."""
    oracle = _oracle()
    return len(
        {
            id(cell)
            for case in found.cases
            for _, cell in oracle[case.effects, case.larger, case.split, case.payers]
        }
    )


@pytest.mark.parametrize("effects", ["small", "large"])
@pytest.mark.parametrize(
    "split", [Fraction(3, 2), Fraction(5, 2), Fraction(3), Fraction(17, 2), 20]
)
@pytest.mark.parametrize("payers", [4, 13, 50, 130, 1000])
def test_a_range_read_both_ways_round_counts_each_cell_of_the_study_once(
    effects: str, split: Fraction, payers: int
) -> None:
    both = hull(
        lookup(effects, "arm", Fraction(split), payers),
        lookup(effects, "control", Fraction(split), payers),
    )

    assert both.cells == _distinct_cells(both)
    assert both.cells <= sum(case.cells for case in both.cases)


def _bare(extrapolated: tuple, rising: tuple) -> SimulatedRange:
    case = CASES[0]
    return SimulatedRange(
        effects=case.effects,
        larger="arm",
        low=case.low,
        high=case.high,
        cases=(case,),
        extrapolated=extrapolated,
        rising=rising,
    )


ABOVE, BELOW = "split_above_range", "payers_below_range"


@pytest.mark.parametrize(
    ("first", "second", "extrapolated", "rising", "floor"),
    [
        (((ABOVE,), (ABOVE,)), ((ABOVE,), (ABOVE,)), (ABOVE,), (ABOVE,), True),
        (((ABOVE,), (ABOVE,)), ((ABOVE,), ()), (ABOVE,), (), False),  # rose in one only
        (((ABOVE,), (ABOVE,)), ((), ()), (ABOVE,), (), False),  # the other lies inside the grid
        (((ABOVE,), (ABOVE,)), ((BELOW,), (BELOW,)), (ABOVE, BELOW), (), False),
        (((ABOVE, BELOW), (ABOVE, BELOW)), ((ABOVE,), (ABOVE,)), (ABOVE, BELOW), (ABOVE,), False),
        (
            ((ABOVE, BELOW), (ABOVE, BELOW)),
            ((ABOVE, BELOW), (ABOVE, BELOW)),
            (ABOVE, BELOW),
            (ABOVE, BELOW),
            True,
        ),
        (((), ()), ((), ()), (), (), False),
    ],
)
def test_the_hull_is_a_floor_only_where_the_rates_rose_in_both_readings(
    first: tuple, second: tuple, extrapolated: tuple, rising: tuple, floor: bool
) -> None:
    both = hull(_bare(*first), _bare(*second))

    assert both.extrapolated == extrapolated and both.rising == rising
    assert both.floor_only is floor


def test_every_direction_is_named_once_when_several_apply() -> None:
    found = lookup("small", "arm", Fraction(50), 1)

    assert found.extrapolated == ("split_above_range", "payers_below_range")
    assert lookup("small", "arm", Fraction(2), 1_000_000).extrapolated == ("payers_above_range",)


def test_the_cases_of_large_effects_are_a_smaller_grid() -> None:
    inside = lookup("large", "equal", Fraction(1), 130)
    outside = lookup("large", "equal", Fraction(1), 1_000)

    assert inside.cases == (_case("large", "equal", 1, 130),) and inside.extrapolated == ()
    assert outside.extrapolated == ("payers_above_range",)
    assert lookup("large", "control", Fraction(5), 50).extrapolated == ()
    assert {c.split for c in lookup("large", "control", Fraction(5), 50).cases} == {
        Fraction(3),
        Fraction(9),
    }


@pytest.mark.parametrize(
    ("effects", "larger", "split", "payers"),
    [(c.effects, c.larger, c.split, c.payers) for c in CASES],
    ids=lambda x: str(x),
)
def test_every_case_of_the_table_can_be_reached(effects, larger, split, payers) -> None:
    found = lookup(effects, larger, split, payers)

    assert [(c.effects, c.larger, c.split, c.payers) for c in found.cases] == [
        (effects, larger, split, payers)
    ]
    assert found.extrapolated == ()


def test_the_range_is_always_the_hull_of_the_cases_that_bracket_the_comparison() -> None:
    rng = random.Random(7)
    for _ in range(400):
        effects = rng.choice(["small", "large"])
        larger = rng.choice(["arm", "control"])
        split = Fraction(rng.randint(101, 900), 100)
        payers = rng.randint(1, 20_000)
        rows = [c for c in CASES if c.effects == effects and c.larger in (larger, "equal")]
        splits = sorted({c.split for c in rows})

        found = lookup(effects, larger, split, payers)

        # the same thing worked out with bisect instead of the lookup's own search
        at = bisect.bisect_left(splits, split)
        expected_splits = (
            [splits[-1]]
            if at == len(splits)
            else [splits[at]]
            if splits[at] == split
            else [splits[at - 1], splits[at]]
        )
        assert sorted({c.split for c in found.cases}) == expected_splits
        for s in expected_splits:
            counts = sorted(c.payers for c in rows if c.split == s)
            k = bisect.bisect_left(counts, payers)
            expected = (
                [counts[0]]
                if k == 0 and payers < counts[0]
                else [counts[-1]]
                if k == len(counts)
                else [counts[k]]
                if counts[k] == payers
                else [counts[k - 1], counts[k]]
            )
            assert sorted(c.payers for c in found.cases if c.split == s) == expected
        assert found.low == min(c.low for c in found.cases)
        assert found.high == max(c.high for c in found.cases)
        assert found.low <= found.high


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        (("small", "arm", Fraction(1, 2), 10), "at least 1"),
        (("small", "arm", 3, 10), "Fraction"),
        (("small", "equal", Fraction(2), 10), "does not go with"),
        (("small", "arm", Fraction(1), 10), "does not go with"),
        (("small", "both", Fraction(2), 10), "does not go with"),
        (("medium", "arm", Fraction(2), 10), "'small' or 'large'"),
        (("small", "arm", Fraction(2), -1), "whole number"),
        (("small", "arm", Fraction(2), True), "whole number"),
        (("small", "arm", Fraction(2), 2.5), "whole number"),
    ],
)
def test_a_comparison_that_cannot_be_placed_is_refused(arguments: tuple, fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        lookup(*arguments)


def test_the_module_says_what_its_rates_are_in() -> None:
    assert pooled_rates.UNIT == pooled_rates_table.UNIT == 100_000


def test_the_command_that_makes_the_table_is_the_same_in_every_place_that_names_it() -> None:
    command = "python tests/pooled_rates_table.py > src/referee/pooled_rates_table.py"
    design = (ROOT / "docs/design/2026-09-28-referee-experiment-review-design.md").read_text(
        encoding="utf-8"
    )

    for place in (
        (ROOT / "README.md").read_text(encoding="utf-8"),
        design.split("\n### 21.11 ")[1],
        generator.__doc__,
        pooled_rates_table.__doc__,
    ):
        assert command in " ".join(place.split())


def test_a_direction_beyond_the_grid_is_named_once_however_many_splits_are_used() -> None:
    for effects in ("small", "large"):
        found = lookup(effects, "arm", Fraction(11, 5), 50000)

        assert found.extrapolated.count("payers_above_range") == 1
        both = hull(found, lookup(effects, "control", Fraction(11, 5), 50000))
        assert both.extrapolated.count("payers_above_range") == 1


def test_the_hull_holds_the_cases_that_two_readings_share_once() -> None:
    arm = lookup("small", "arm", Fraction(21, 20), 117)
    control = lookup("small", "control", Fraction(21, 20), 117)

    both = hull(arm, control)

    assert len(set(both.cases)) == len(both.cases)
    assert (
        both.cells == sum(case.cells for case in set(arm.cases) | set(control.cases)) - both.overlap
    )


# --- After the third review ---------------------------------------------------------------------


def test_the_hull_is_the_same_whichever_reading_comes_first() -> None:
    arm = lookup("small", "arm", Fraction(3), 50)
    control = lookup("small", "control", Fraction(3), 50)

    one, other = hull(arm, control), hull(control, arm)

    assert one.cells == other.cells == _distinct_cells(one) == _distinct_cells(other)
    assert (one.low, one.high, one.overlap) == (other.low, other.high, other.overlap)
    assert set(one.cases) == set(other.cases)


def test_the_hull_takes_the_lowest_low_and_the_highest_high_whichever_reading_has_them() -> None:
    base = lookup("small", "arm", Fraction(3), 50)
    low_first = replace(base, low=base.low - 700, high=base.high - 300)
    high_second = replace(base, low=base.low + 500, high=base.high + 900)

    for first, second in ((low_first, high_second), (high_second, low_first)):
        both = hull(first, second)

        assert both.low == base.low - 700 and both.high == base.high + 900


def test_a_range_of_cases_with_different_runs_and_tail_weights_says_so() -> None:
    mixed = lookup("small", "equal", Fraction(1), 350)  # between 300 (2,000 runs) and 390

    assert {case.payers for case in mixed.cases} == {300, 390}
    assert mixed.tails == (2, 3) and mixed.min_runs == 2000
    both = hull(
        lookup("small", "arm", Fraction(3), 350), lookup("small", "control", Fraction(3), 350)
    )
    assert both.min_runs == min(c.min_runs for c in both.cases)
    assert both.tails == (min(c.tails for c in both.cases), max(c.tails for c in both.cases))


def test_a_direction_that_rose_in_one_order_only_is_kept_apart_from_a_floor() -> None:
    arm = lookup("small", "arm", Fraction(3, 2), 6)
    control = lookup("small", "control", Fraction(3, 2), 6)

    both = hull(arm, control)

    assert arm.rising == () and control.rising == ("payers_below_range",)
    assert both.extrapolated == ("payers_below_range",)
    assert both.rising == () and not both.floor_only
    assert both.rising_in_one == ("payers_below_range",)
    assert hull(arm, arm).rising_in_one == ()
