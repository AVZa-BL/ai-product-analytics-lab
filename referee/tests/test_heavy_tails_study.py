"""The claims RES-008's texts make about the pooled-effect study, checked against its file.

The rule's sentences say "every run showed a sign", "failed less often than the others in nearly
every case", "most of the failed intervals lay on the side of the larger group" and the like.
Each is a statement about `docs/simulations/pooled_effect_heavy.json`, and each is checked here,
so that the text cannot outlive the numbers. (The figures the rule prints come from the
generated table, which `test_pooled_rates.py` rebuilds from the same file.)
"""

import json
import math
from fractions import Fraction
from pathlib import Path

import pytest
from scipy.stats import spearmanr

from referee.pooled_rates import CASES, NOMINAL_RATE, UNIT

DATA = json.loads(
    (Path(__file__).parent.parent / "docs/simulations/pooled_effect_heavy.json").read_text(
        encoding="utf-8"
    )
)
REVENUE_LIKE = ("revenue_mild", "revenue", "revenue_heavy")
CELLS = [cell for cell in DATA["cells"] if cell["outcome"] in REVENUE_LIKE]
SMALL = (0.0, 0.2)
LARGE = (0.5, 1.0)


def _split(cell: dict) -> Fraction:
    return Fraction(max(cell["arm_n"], cell["control_n"]), min(cell["arm_n"], cell["control_n"]))


def _share_on_the_larger_looks_better_side(cell: dict) -> float:
    """Of the intervals that missed, the share lying on the side that makes the larger arm look
    better than it is: wholly above the truth if the arm is the larger, below it if control is."""
    above, below = cell["welch_above_n"], cell["welch_below_n"]
    good = above if cell["arm_n"] > cell["control_n"] else below
    return good / (above + below)


def test_the_study_has_the_revenue_like_cells_the_texts_are_about() -> None:
    assert len(CELLS) == 439
    assert {cell["effect"] for cell in CELLS} == {0.0, 0.2, 0.5, 1.0}


def test_every_simulated_run_of_a_revenue_like_metric_showed_a_sign() -> None:
    """The size rule or a kurtosis above 100 fired in every replication of every cell, so the
    rule's three signs together did too (the share can only add)."""
    assert all(cell["criteria"]["kohavi|kurtosis>100"][0] == cell["reps"] for cell in CELLS)


@pytest.mark.parametrize("criterion", ["kurtosis>100", "top_share>0.5"])
def test_runs_with_a_kurtosis_or_share_sign_failed_less_often_than_the_others(
    criterion: str,
) -> None:
    counted = []
    for cell in CELLS:
        fired, above_fired, below_fired, above_not, below_not = cell["criteria"][criterion]
        quiet = cell["reps"] - fired
        if fired >= 200 and quiet >= 200:
            counted.append((above_fired + below_fired) / fired < (above_not + below_not) / quiet)

    assert len(counted) >= 150
    assert sum(counted) / len(counted) >= 0.95  # "in nearly every case"


def test_the_percentile_bootstrap_failed_more_often_than_welch_in_most_of_its_cells() -> None:
    boot = [cell["boot"] for cell in DATA["cells"] if "boot" in cell]

    more = [
        b["boot_above_n"] + b["boot_below_n"] > b["welch_above_n"] + b["welch_below_n"]
        for b in boot
    ]

    assert len(boot) == 99 and sum(more) / len(more) >= 0.8


def test_with_unequal_groups_and_a_small_effect_most_failed_intervals_favour_the_larger_group() -> (
    None
):
    cells = [c for c in CELLS if c["arm_n"] != c["control_n"] and c["effect"] in SMALL]
    cells = [c for c in cells if c["welch_above_n"] + c["welch_below_n"] > 0]

    on_that_side = [_share_on_the_larger_looks_better_side(c) > 0.5 for c in cells]

    assert len(cells) >= 300 and sum(on_that_side) / len(cells) >= 0.95
    # and pooled over the cells, by the larger group and by how unequal they are
    for arm_larger in (True, False):
        for beyond in (False, True):
            group = [
                c
                for c in cells
                if (c["arm_n"] > c["control_n"]) == arm_larger and (_split(c) >= 3) == beyond
            ]
            pooled = sum(
                _share_on_the_larger_looks_better_side(c)
                * (c["welch_above_n"] + c["welch_below_n"])
                for c in group
            ) / sum(c["welch_above_n"] + c["welch_below_n"] for c in group)
            assert pooled > 0.7, (arm_larger, beyond, pooled)


def test_with_about_equal_groups_and_a_large_effect_most_failed_intervals_lie_below_the_truth() -> (
    None
):
    cells = [c for c in CELLS if c["arm_n"] == c["control_n"] and c["effect"] in LARGE]

    shares = [c["welch_below_n"] / (c["welch_above_n"] + c["welch_below_n"]) for c in cells]

    assert len(cells) == 8 and min(shares) > 0.8


def test_with_equal_groups_the_interval_is_mostly_near_or_under_its_level_when_small() -> None:
    small = [c for c in CASES if c.effects == "small" and c.larger == "equal"]
    large = [c for c in CASES if c.effects == "large" and c.larger == "equal"]

    close_or_under = [c.high <= NOMINAL_RATE * 6 // 5 for c in small]  # at most 6%

    assert sum(close_or_under) / len(small) >= 0.9
    assert all(c.low > NOMINAL_RATE for c in large)  # above its level for a large one


def test_with_unequal_groups_the_interval_is_often_above_its_level_and_worse_the_more_unequal() -> (
    None
):
    unequal = [c for c in CASES if c.larger != "equal"]

    assert sum(c.high > NOMINAL_RATE for c in unequal) / len(unequal) > 0.5
    for effects in ("small", "large"):
        for larger in ("arm", "control"):
            rows = [c for c in unequal if c.effects == effects and c.larger == larger]
            by_split: dict[Fraction, list[int]] = {}
            for case in rows:
                by_split.setdefault(case.split, []).append(case.high)
            means = [sum(v) / len(v) for _, v in sorted(by_split.items())]
            assert means == sorted(means), (effects, larger, means)  # rises with the split


def test_at_nine_to_one_with_no_effect_the_rate_falls_with_the_players_who_spend() -> None:
    for outcome in ("revenue", "revenue_heavy"):
        points = sorted(
            (
                round(c.get("paying", 0.13) * min(c["arm_n"], c["control_n"])),
                (c["welch_above_n"] + c["welch_below_n"]) / c["reps"],
            )
            for c in CELLS
            if c["effect"] == 0.0
            and _split(c) == 9
            and c["outcome"] == outcome
            and c["reps"] == 20_000
        )

        assert [payers for payers, _ in points] == [9, 13, 30, 39, 90, 130, 300, 390]
        assert spearmanr(*zip(*points, strict=True)).statistic < -0.8, outcome


def test_the_noise_of_a_rate_is_about_a_third_of_a_point_at_20000_runs_and_one_at_2000() -> None:
    def half_range(runs: int) -> float:
        return 1.96 * math.sqrt(0.05 * 0.95 / runs)

    assert round(100 * half_range(20_000), 1) == 0.3
    assert round(100 * half_range(2_000), 0) == 1
    assert {cell["reps"] for cell in DATA["cells"]} <= {20_000, 2_000}
    assert UNIT == 100_000


def test_the_control_the_larger_arm_was_the_worst_case_for_a_small_and_for_a_large_effect() -> None:
    for effects in ("small", "large"):
        highest = {
            larger: max(c.high for c in CASES if c.effects == effects and c.larger == larger)
            for larger in ("equal", "arm", "control")
        }

        assert highest["control"] > highest["arm"] and highest["control"] > highest["equal"], (
            effects,
            highest,
        )


def test_with_a_large_effect_and_the_control_the_larger_arm_nearly_all_failures_understate_it() -> (
    None
):
    cells = [c for c in CELLS if c["effect"] in LARGE and c["control_n"] > c["arm_n"]]

    shares = [c["welch_below_n"] / (c["welch_above_n"] + c["welch_below_n"]) for c in cells]

    assert len(cells) == 16 and min(shares) > 0.9


def test_with_a_large_effect_and_the_arm_the_larger_there_is_no_side_the_failures_favour() -> None:
    """Why the finding says nothing about direction for a large effect when the group with the
    higher mean is the larger: the cells are split, and the pooled share is near a half."""
    cells = [c for c in CELLS if c["effect"] in LARGE and c["arm_n"] > c["control_n"]]

    shares = [c["welch_above_n"] / (c["welch_above_n"] + c["welch_below_n"]) for c in cells]

    assert len(cells) == 16
    assert sum(share > 0.5 for share in shares) <= 12 and sum(share < 0.5 for share in shares) >= 4
