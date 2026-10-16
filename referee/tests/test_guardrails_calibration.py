"""Why the registered-baseline reading of a revenue-like guardrail is held to `possible`.

A revenue-like guardrail (most players at 0, a few large) has a right-skewed distribution, and the
t interval for the mean of such data lies wholly below the true mean far more often than the
2.5% a two-sided 95% interval allows on that side. Against a registered baseline that is true to
the population, a fall guardrail therefore reads a "shown" breach in a harmless arm too often.
This is a seeded simulation of that (13% of players spend, lognormal spend with a log standard
deviation of 1.5, 1,000 players an arm, the registered baseline the true mean) with the real
readings of `referee.guardrails`; its thresholds are loose enough to survive another stream of
the generator, and tight enough to fail if the hold were taken off.

It measures the two readings of this one family at this one size. It is not a study of
intervals in general (RES-008 has measured rates for Welch's interval for a difference of means,
which is a different interval).
"""

import functools
import math

import numpy as np

from referee.guardrails import baseline_reference, control_reference

SPEND, LOG_SD, PLAYERS, DRAWS, TOLERANCE = 0.13, 1.5, 1000, 1500, 0.10
TRUE_MEAN = SPEND * math.exp(LOG_SD**2 / 2)


def _revenue(rng: np.random.Generator, spend: float) -> list[float]:
    paying = rng.random(PLAYERS) < spend
    return np.where(paying, rng.lognormal(0.0, LOG_SD, PLAYERS), 0.0).tolist()


@functools.cache
def _rates(harm: float, direction: str = "decrease") -> dict[str, float]:
    """The share of draws in which a breach is shown, for an arm whose mean is `harm` worse than
    the registered baseline (a fall for "decrease", a rise for "increase"): by the reading against
    the baseline alone with and without the hold (`baseline_held`, `baseline_unheld`), by the
    reading against control (`control`), and by the rule with the hold (`rule`) and without it
    (`unheld`)."""
    rng = np.random.default_rng(20261013)
    counts = dict.fromkeys(("baseline_unheld", "baseline_held", "control", "rule", "unheld"), 0)
    options = {
        "baseline": TRUE_MEAN,
        "kind": "continuous",
        "direction": direction,
        "tolerance": TOLERANCE,
    }
    factor = 1 - harm if direction == "decrease" else 1 + harm
    for _ in range(DRAWS):
        arm, control = _revenue(rng, SPEND * factor), _revenue(rng, SPEND)
        unheld = baseline_reference(arm, **options).harm
        held = baseline_reference(arm, right_skewed=True, **options).harm
        versus = control_reference(arm, control, direction=direction, tolerance=TOLERANCE).harm
        assert unheld is not None and held is not None and versus is not None
        counts["baseline_unheld"] += unheld.tier == "shown"
        counts["baseline_held"] += held.tier == "shown"
        counts["control"] += versus.tier == "shown"
        counts["rule"] += "shown" in (held.tier, versus.tier)
        counts["unheld"] += "shown" in (unheld.tier, versus.tier)
    return {name: count / DRAWS for name, count in counts.items()}


# --- A fall, the case the hold is for ---------------------------------------------------------


def test_the_baseline_reading_alone_over_shows_a_fall_in_a_harmless_arm() -> None:
    rates = _rates(0.0)

    assert rates["baseline_unheld"] > 0.035  # a calibrated limit on that side would be 0.025
    assert rates["unheld"] > 0.04


def test_with_the_hold_a_harmless_arm_is_a_blocker_no_more_often_than_chance_allows() -> None:
    rates = _rates(0.0)

    assert rates["baseline_held"] == 0.0
    assert rates["rule"] < 0.035  # and only the reading against control can show it


def test_at_the_tolerance_the_hold_removes_most_of_the_false_blockers_but_not_all() -> None:
    rates = _rates(TOLERANCE)

    assert rates["unheld"] > 0.10
    assert rates["rule"] < 0.08
    assert rates["rule"] > 0.025  # a calibrated interval would show 0.025: some excess remains


def test_the_reading_against_control_is_the_better_calibrated_of_the_two() -> None:
    """Why it is not held: at the tolerance it is nearer to what a calibrated limit would show
    than the baseline reading is, by a good margin."""
    rates = _rates(TOLERANCE)

    assert rates["control"] < rates["baseline_unheld"] / 2
    assert rates["control"] < 0.06


def test_the_hold_costs_power_at_a_fall_of_three_times_the_tolerance() -> None:
    """The price of the hold, stated: at a fall of 30% of the mean a blocker is much less likely
    than on the baseline reading alone (the rest of those draws are warnings), at under half the
    rate, and still shown in about one draw in six."""
    rates = _rates(0.30)

    assert rates["unheld"] > 0.35
    assert 0.10 < rates["rule"] < 0.30
    assert rates["rule"] < rates["unheld"] / 1.8


# --- A rise, which is not held -----------------------------------------------------------------


def test_a_rise_is_hardly_ever_shown_by_the_baseline_reading_so_it_is_not_over_shown() -> None:
    """The same interval almost never lies wholly above the true mean for such data, so there is
    nothing to hold in a rise; the cost is the other way, a rise that the baseline reading
    misses, which the reading against control carries."""
    harmless, rising = _rates(0.0, "increase"), _rates(0.30, "increase")

    assert harmless["baseline_held"] < 0.005 and harmless["baseline_unheld"] < 0.005
    assert harmless["rule"] < 0.035
    assert rising["baseline_held"] < 0.05  # barely sees a rise of 30%
    assert rising["control"] > 0.08 and rising["control"] > 2 * rising["baseline_held"]
