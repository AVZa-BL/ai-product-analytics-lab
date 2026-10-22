"""Small helpers that the texts of the rules share."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal


def join_and(items: Sequence[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def sig(value: float, digits: int = 3) -> str:
    """`value` to `digits` significant figures, with thousands separators.

    From 1e-6 up to 1e15 in size the number is written out in full; beyond them it is written
    with an exponent ("1.00e-300"), because written out it would run to hundreds of digits, most
    of them float noise. A value is never shown as 0 or as a negative zero unless it is 0:
    -0.00005 is "-0.0000500". A value that is not a finite number cannot be shown and raises
    `ValueError`.
    """
    if not math.isfinite(value):
        raise ValueError(f"{value!r} is not a finite number, so it cannot be shown")
    if value == 0:
        return "0"
    if abs(value) >= _LARGEST_WRITTEN_OUT or abs(value) < _SMALLEST_WRITTEN_OUT:
        return f"{value:.{max(0, digits - 1)}e}"
    exponent = math.floor(math.log10(abs(value)))
    if abs(round(value, digits - 1 - exponent)) >= 10 ** (exponent + 1):  # 9.996 rounds to 10
        exponent += 1
    places = digits - 1 - exponent
    return f"{round(value, places):,.{max(0, places)}f}"


_LARGEST_WRITTEN_OUT = 1e15
_SMALLEST_WRITTEN_OUT = 1e-6
_LARGEST_SHARE = 1e10  # a share of a million million percent is shown with an exponent
_SMALLEST_SHARE = Decimal("1e-6")  # as a percentage, as for `sig`
_LARGEST_PERCENT = Decimal("1e15")


def sig_up(value: float, digits: int = 3) -> str:
    """Like `sig`, but rounded up, for a limit that is stated as "below this": the figure shown
    is never under the true limit. `value` must be above 0 and finite."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{value!r} is not a finite number above 0")
    exponent = math.floor(math.log10(value))
    scale = 10 ** (digits - 1 - exponent)
    return sig(math.ceil(value * scale - 1e-9) / scale, digits)


def _percent(share: float) -> Decimal:
    """The share as the decimal that its shortest repr spells, times 100: 0.072 is 7.2 exactly,
    where the float product 100 * 0.072 is 7.199999999999999."""
    return Decimal(repr(float(share))) * 100


def percent_exact(share: float) -> str:
    """A share as the percentage it was written as, not rounded: with at least one decimal (0.1 is
    "10.0%", 0.29 is "29.0%") and no more than it has (0.0125 is "1.25%"). A share beyond the
    sizes that `sig` writes out is written with an exponent."""
    exact = _percent(share).normalize()
    if exact != 0 and not _SMALLEST_SHARE <= abs(exact) < _LARGEST_PERCENT:
        return f"{exact:e}%"
    text = f"{exact:f}"
    return f"{text if '.' in text else text + '.0'}%"


def percent_near(share: float, level: float, *, places: int = 1) -> str:
    """A share as a percentage to `places` decimals, with more where that is needed so that it
    is not shown as beyond `level` when it is not, or as not beyond it when it is (10.04% is not
    shown as 10.0% beside a tolerance of 10%, which would read as at the tolerance, not past it;
    9.96% may be, because at the tolerance is not past it). A share that is exactly the level is
    shown as the level is written. The comparison is made on the decimals the floats spell, so a
    level such as 0.072 is not nudged by the float product 100 * 0.072.
    """
    if abs(share) >= _LARGEST_SHARE:
        return f"{_percent(share):.3e}%"  # a Decimal does not overflow where 100 * share does
    exact, bound = _percent(share), _percent(level)
    if exact == bound:
        return percent_exact(level)
    for shown_places in range(places, places + 4):
        shown = exact.quantize(Decimal(1).scaleb(-shown_places), rounding=ROUND_HALF_EVEN)
        if (shown > bound) == (exact > bound):
            break
    text = f"{shown:f}"
    if shown == 0:
        text = text.lstrip("-")
    return f"{text}%"
