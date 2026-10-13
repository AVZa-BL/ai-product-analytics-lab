"""Why RES-008 reads unequal groups in both orders instead of by the sign of the difference seen.

In the simulated cases the arm is the group with the higher mean (only positive effects were
run), so a comparison could be put in those roles by the sign of the difference of the sample
means. That sign is unreliable when the smaller group has few players who spend, and Welch's 95%
interval excluding 0 does not repair it: with a heavy tail the interval that excludes 0 does so
mostly on the wrong side, because a sample with a low mean also has a low spread. This is a small
seeded check of that claim, with the study's family (13% of players spend a lognormal amount,
the arm's amounts multiplied by 1.2, the arm the smaller group at 3 to 1; a smaller group of
300 players has about 39 who spend), as design section
21.11 states it. The study of section 21.10 did not save the sign of its estimates.
"""

import numpy as np
from scipy import stats

PAYING = 0.13
RUNS = 1500
EFFECT = 0.2
FEW = 300  # players in the smaller group: about 39 of them spend
SD = 1.5  # the log standard deviation of what a player who spends spends


def _group(rng: np.random.Generator, n: int, multiplier: float, sd: float):
    """Mean and variance of `n` players in each of RUNS runs, drawn through their sufficient
    statistics (the players who spend are binomial, their amounts lognormal)."""
    spenders = rng.binomial(n, PAYING, size=RUNS)
    sums, squares = np.empty(RUNS), np.empty(RUNS)
    for i, count in enumerate(spenders):
        amounts = np.exp(rng.normal(0.0, sd, count)) * multiplier
        sums[i], squares[i] = amounts.sum(), np.square(amounts).sum()
    mean = sums / n
    return mean, (squares - n * mean**2) / (n - 1)


def _runs(smaller: int, sd: float, seed: int = 2026):
    """The arm (the higher mean in truth) is the smaller group, 3 to 1."""
    rng = np.random.default_rng(seed)
    arm_mean, arm_var = _group(rng, smaller, 1 + EFFECT, sd)
    control_mean, control_var = _group(rng, 3 * smaller, 1.0, sd)
    difference = arm_mean - control_mean
    error = np.sqrt(arm_var / smaller + control_var / (3 * smaller))
    freedom = error**4 / (
        (arm_var / smaller) ** 2 / (smaller - 1)
        + (control_var / (3 * smaller)) ** 2 / (3 * smaller - 1)
    )
    half = stats.t.ppf(0.975, freedom) * error
    excludes_zero = (difference - half > 0) | (difference + half < 0)
    wrong_sign = difference < 0  # the group with the higher mean seen is the one with the lower
    big = np.abs(difference) >= 0.35 * np.minimum(arm_mean, control_mean)
    return wrong_sign, excludes_zero, big


def test_with_few_players_who_spend_the_sign_of_the_difference_is_often_wrong() -> None:
    wrong_sign, _, big = _runs(smaller=FEW, sd=SD)

    assert wrong_sign.mean() > 0.3  # over all runs
    assert wrong_sign[big].mean() > 0.25  # and among those that show a large difference
    assert big.mean() > 0.4  # which is common, though the true effect is only +20%
    assert _runs(smaller=FEW, sd=2.0)[0].mean() > 0.4  # and more so with a heavier tail


def test_an_interval_that_excludes_zero_does_not_make_the_sign_trustworthy_there() -> None:
    for sd, wrong_over in ((1.5, 0.5), (2.0, 0.7)):
        wrong_sign, excludes_zero, _ = _runs(smaller=FEW, sd=sd)

        assert 20 < excludes_zero.sum() < RUNS / 4  # it is rare to exclude 0 ...
        assert wrong_sign[excludes_zero].mean() > wrong_over  # ... and mostly on the wrong side


def test_with_many_players_who_spend_the_sign_is_nearly_always_right_for_a_light_enough_tail() -> (
    None
):
    wrong_sign, excludes_zero, big = _runs(smaller=7700, sd=SD)  # about 1,000 of them spend

    assert wrong_sign.mean() < 0.1  # (with a log standard deviation of 2.0 it is still 21%)
    assert wrong_sign[excludes_zero].mean() < 0.01 and wrong_sign[big].mean() < 0.02
