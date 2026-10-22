"""What the pooled-effect study found for a comparison like this one (design sections 21.10, 21.11).

The study simulated how often Welch's 95% interval for a difference of means missed the true
difference when the metric is a revenue that most players leave at zero. A comparison is placed
among its cases by three things the rule can see: which arm is the larger, the split between the
arms (the larger arm's analysed players over the smaller's) and the number of players who spend
in the smaller arm. It cannot see the weight of the tail or the effect, so a case is a range
over those: `small` effects are none and +20%, `large` effects are +50% and +100%.

`lookup` returns the lowest and highest rate of the cases around the comparison. The cases lie
on a grid, so the two splits that bracket the comparison, and at each the two player counts that
bracket it, are used and the range is the hull of them; a comparison on the grid uses its own
case. Beyond the grid the nearest edge is used and the answer says in which direction. Where
the table shows the rates rising towards that side (a larger split, or fewer players who spend)
the range is a floor: the true rate is probably higher. Where it does not show that, the answer
only says that the comparison is beyond the cases simulated.

The rows are in `referee.pooled_rates_table`, generated from the committed study. Rates are
whole numbers of 1/`UNIT`, so they print exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, NamedTuple

from referee.pooled_rates_table import ROWS, UNIT

Effects = Literal["small", "large"]
Larger = Literal["equal", "arm", "control"]
Extrapolation = Literal["split_above_range", "payers_below_range", "payers_above_range"]

NOMINAL_RATE = UNIT // 20  # 5%: how often a 95% interval should miss
# The rate above which a simulated range counts as a clear excess over the nominal one:
# 1.5 times as often (judgement, design section 21.11).
EXCESS_RATE = NOMINAL_RATE * 3 // 2
# The table's highest rate has to rise by more than this (a point: a few times the noise of a
# cell) towards a comparison beyond the grid before the range there is called a floor.
RISE_MARGIN = UNIT // 100


class Case(NamedTuple):
    """One row of the study's table."""

    effects: Effects
    larger: Larger
    split: Fraction
    payers: int
    low: int
    high: int
    cells: int
    tails: int
    min_runs: int
    shared: int  # cells with no effect and unequal arms: also cells of the other larger arm


CASES: tuple[Case, ...] = tuple(
    Case(effects, larger, Fraction(num, den), payers, low, high, cells, tails, runs, shared)
    for effects, larger, num, den, payers, low, high, cells, tails, runs, shared in ROWS
)


@dataclass(frozen=True, kw_only=True)
class SimulatedRange:
    """The lowest and highest rate over the cases around a comparison.

    `cases` are the rows used. `extrapolated` is empty when the comparison lies inside the grid
    in both directions, and otherwise names where it does not. `rising` are those of them in
    which the table's highest rates rose by more than `RISE_MARGIN` towards the comparison (a
    larger split, or fewer players who spend, at every split used), so that the true rate there
    is probably above the range.
    """

    effects: Effects
    larger: Larger | Literal["either"]
    low: int
    high: int
    cases: tuple[Case, ...]
    extrapolated: tuple[Extrapolation, ...]
    rising: tuple[Extrapolation, ...]
    overlap: int = 0  # cells that two of the cases share (see `hull`)
    # for a hull: the directions in which the rates rose in one order of the groups only
    rising_in_one: tuple[Extrapolation, ...] = ()

    @property
    def floor_only(self) -> bool:
        """Whether every direction beyond the grid is one in which the rates rose: the range
        is then a floor. A direction in which they did not (or are not known to) rise is not."""
        return bool(self.extrapolated) and set(self.rising) == set(self.extrapolated)

    @property
    def cells(self) -> int:
        """The distinct cells of the study the cases are made of."""
        return sum(case.cells for case in self.cases) - self.overlap

    @property
    def tails(self) -> tuple[int, int]:
        """The fewest and the most tail weights any case has (two or three)."""
        weights = [case.tails for case in self.cases]
        return min(weights), max(weights)

    @property
    def min_runs(self) -> int:
        return min(case.min_runs for case in self.cases)


def percent(rate: int) -> str:
    """A rate (whole units of 1/`UNIT`) as a percentage to one decimal, rounded half up."""
    tenths = (rate * 1000 + UNIT // 2) // UNIT
    return f"{tenths // 10}.{tenths % 10}%"


def _bracket(values: list, wanted) -> tuple[list, bool, bool]:
    """The grid values that bracket `wanted`, and whether it is below / above the grid."""
    if wanted < values[0]:
        return [values[0]], True, False
    if wanted > values[-1]:
        return [values[-1]], False, True
    below = max(v for v in values if v <= wanted)
    above = min(v for v in values if v >= wanted)
    return sorted({below, above}), False, False


def _highest(cases: list[Case], split: Fraction, payers: int | None = None) -> int:
    """The highest rate of the cases at a split (and a number of players who spend)."""
    return max(c.high for c in cases if c.split == split and payers in (None, c.payers))


def hull(first: SimulatedRange, second: SimulatedRange) -> SimulatedRange:
    """The range that covers two, for a comparison that could be read either way round.

    It is the lowest and the highest rate of both, over all their cases. A direction beyond the
    grid is a floor only if the rates rose in it in both. A cell with no effect and unequal arms
    is a cell of the `arm` case and of the `control` case at the same split and players who
    spend, so it is counted once.
    """
    extrapolated = tuple(dict.fromkeys((*first.extrapolated, *second.extrapolated)))
    cases = tuple(dict.fromkeys((*first.cases, *second.cases)))
    twins = {(case.split, case.payers) for case in cases if case.larger == "control"}
    overlap = sum(
        case.shared for case in cases if case.larger == "arm" and (case.split, case.payers) in twins
    )
    return SimulatedRange(
        effects=first.effects,
        larger="either",
        low=min(first.low, second.low),
        high=max(first.high, second.high),
        cases=cases,
        extrapolated=extrapolated,
        rising=tuple(f for f in extrapolated if f in first.rising and f in second.rising),
        rising_in_one=tuple(f for f in extrapolated if (f in first.rising) != (f in second.rising)),
        overlap=overlap,
    )


def lookup(effects: Effects, larger: Larger, split: Fraction, payers: int) -> SimulatedRange:
    """The range of the cases around a comparison.

    `split` is at least 1 and `larger` is `equal` exactly when it is 1. `payers` is the number
    of players who spend in the smaller arm.
    """
    if not isinstance(split, Fraction) or split < 1:
        raise ValueError(f"the split must be a Fraction of at least 1, got {split!r}")
    if (larger == "equal") != (split == 1) or larger not in ("equal", "arm", "control"):
        raise ValueError(f"larger={larger!r} does not go with a split of {split}")
    if effects not in ("small", "large"):
        raise ValueError(f"effects must be 'small' or 'large', got {effects!r}")
    if isinstance(payers, bool) or not isinstance(payers, int) or payers < 0:
        raise ValueError(f"payers must be a whole number of at least 0, got {payers!r}")
    cases = [c for c in CASES if c.effects == effects and c.larger in (larger, "equal")]
    grid = sorted({c.split for c in cases})
    used: list[Case] = []
    flags: list[Extrapolation] = []
    rising: list[Extrapolation] = []  # the directions in which the table's highest rates rose
    splits, _, above = _bracket(grid, split)
    if above:
        flags.append("split_above_range")
        # judged on the highest rate over all player counts at each of the last two splits
        if _highest(cases, grid[-1]) > _highest(cases, grid[-2]) + RISE_MARGIN:
            rising.append("split_above_range")
    fewer: list[bool] = []  # at each split short of its players: did the rates fall with more?
    for grid_split in splits:
        counts = sorted(c.payers for c in cases if c.split == grid_split)
        chosen, short, beyond = _bracket(counts, payers)
        if short:
            fewer.append(
                _highest(cases, grid_split, counts[0])
                > _highest(cases, grid_split, counts[-1]) + RISE_MARGIN
            )
        if beyond and "payers_above_range" not in flags:
            flags.append("payers_above_range")
        used += [c for c in cases if c.split == grid_split and c.payers in chosen]
    if fewer:
        flags.append("payers_below_range")
        if all(fewer):
            rising.append("payers_below_range")
    return SimulatedRange(
        effects=effects,
        larger=larger,
        low=min(c.low for c in used),
        high=max(c.high for c in used),
        cases=tuple(used),
        extrapolated=tuple(flags),
        rising=tuple(rising),
    )
