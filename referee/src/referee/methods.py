"""The statistics the results review uses. Pure functions on numbers: no files, no clock.

Each function says what it computes and where the formula comes from, and the tests check it
against an independent implementation (`scipy`, `statsmodels`) or a known answer. A function
that cannot give a meaningful answer for its input raises `StatsError` instead of returning NaN
or a confident-looking number: a confidence interval of zero width from data with no variation
would claim certainty the data cannot give.

Sums use `math.fsum`, which is exactly rounded and so does not depend on the order of the values
or on the platform. The distribution functions come from `scipy.stats`; their last digits can
differ between scipy versions, so reports round what they print.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from scipy import stats

SRM_ALPHA = 0.001  # section 9: the threshold used in the Kohavi, Tang and Xu treatment of SRM


class StatsError(ValueError):
    """The input does not allow a meaningful answer; the message says why."""


def _check_alpha(alpha: float) -> None:
    if not 0 < alpha < 1:
        raise StatsError(f"alpha must be between 0 and 1, got {alpha!r}")


def _finite(values: Sequence[float], name: str) -> list[float]:
    numbers = [float(value) for value in values]
    if not all(math.isfinite(number) for number in numbers):
        raise StatsError(f"{name} must hold only finite numbers")
    return numbers


# --- Sample ratio mismatch -----------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SrmResult:
    observed: tuple[int, ...]
    expected: tuple[float, ...]
    chi_square: float
    degrees_of_freedom: int
    p_value: float
    flagged: bool


def srm_test(
    observed: Sequence[int], allocation: Sequence[float], *, alpha: float = SRM_ALPHA
) -> SrmResult:
    """Chi-square goodness of fit of observed arm counts against the registered allocation.

    The expected count of an arm is the total times its allocated share; the statistic is
    sum((observed - expected)^2 / expected) on (arms - 1) degrees of freedom, and the mismatch
    is flagged when p < alpha. An arm with no assignments counts as 0 rather than being left
    out, so a vanished arm is the strongest possible mismatch. Reference: Fabijan et al.,
    "Diagnosing Sample Ratio Mismatch in Online Controlled Experiments" (KDD 2019).
    """
    _check_alpha(alpha)
    if len(observed) != len(allocation) or len(observed) < 2:
        raise StatsError("need one count per arm for at least two arms, and one share per count")
    if any(isinstance(n, bool) or int(n) != n or n < 0 for n in observed):
        raise StatsError(f"counts must be whole numbers of at least 0, got {list(observed)!r}")
    shares = _finite(allocation, "allocation")
    if any(share <= 0 for share in shares) or abs(math.fsum(shares) - 1.0) > 1e-9:
        raise StatsError(f"allocation shares must be positive and sum to 1, got {shares!r}")
    total = sum(int(n) for n in observed)
    if total == 0:
        raise StatsError("no units were assigned, so there is nothing to test")

    expected = tuple(total * share for share in shares)
    chi_square = math.fsum((n - e) ** 2 / e for n, e in zip(observed, expected, strict=True))
    degrees = len(observed) - 1
    p_value = float(stats.chi2.sf(chi_square, degrees))
    return SrmResult(
        observed=tuple(int(n) for n in observed),
        expected=expected,
        chi_square=chi_square,
        degrees_of_freedom=degrees,
        p_value=p_value,
        flagged=p_value < alpha,
    )


# --- A difference in means (continuous metrics) --------------------------------------------


@dataclass(frozen=True, kw_only=True)
class MeanDifference:
    """Treatment minus control, from Welch's unequal-variance t test."""

    n_treatment: int
    n_control: int
    mean_treatment: float
    mean_control: float
    difference: float
    std_error: float
    degrees_of_freedom: float
    t_statistic: float
    p_value: float
    ci_low: float
    ci_high: float
    confidence: float


def _mean_and_variance(values: list[float], name: str) -> tuple[float, float]:
    if len(values) < 2:
        raise StatsError(f"{name} needs at least 2 values, got {len(values)}")
    mean = math.fsum(values) / len(values)
    variance = math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, variance


def welch_difference(
    treatment: Sequence[float], control: Sequence[float], *, alpha: float = 0.05
) -> MeanDifference:
    """Welch's t test and (1 - alpha) confidence interval for mean(treatment) - mean(control).

    The standard error is sqrt(s1^2/n1 + s2^2/n2) and the degrees of freedom are the
    Welch-Satterthwaite approximation, so the groups need not have equal variances. Raises
    `StatsError` when either group has fewer than 2 values or when neither varies, because the
    standard error is then 0 and the test says nothing.
    """
    _check_alpha(alpha)
    a, b = _finite(treatment, "treatment"), _finite(control, "control")
    mean_a, var_a = _mean_and_variance(a, "treatment")
    mean_b, var_b = _mean_and_variance(b, "control")
    part_a, part_b = var_a / len(a), var_b / len(b)
    if part_a + part_b == 0:
        raise StatsError(
            "neither group varies, so the standard error is 0 and nothing can be tested"
        )
    std_error = math.sqrt(part_a + part_b)
    degrees = (part_a + part_b) ** 2 / (part_a**2 / (len(a) - 1) + part_b**2 / (len(b) - 1))
    difference = mean_a - mean_b
    t_statistic = difference / std_error
    margin = float(stats.t.ppf(1 - alpha / 2, degrees)) * std_error
    return MeanDifference(
        n_treatment=len(a),
        n_control=len(b),
        mean_treatment=mean_a,
        mean_control=mean_b,
        difference=difference,
        std_error=std_error,
        degrees_of_freedom=degrees,
        t_statistic=t_statistic,
        p_value=float(2 * stats.t.sf(abs(t_statistic), degrees)),
        ci_low=difference - margin,
        ci_high=difference + margin,
        confidence=1 - alpha,
    )


# --- A difference in proportions (binary metrics) ------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ProportionDifference:
    """Treatment minus control, from the two-proportion z test."""

    n_treatment: int
    n_control: int
    rate_treatment: float
    rate_control: float
    difference: float
    std_error: float  # unpooled, which is what the interval uses
    z_statistic: float  # pooled, which is what the test uses
    p_value: float
    ci_low: float
    ci_high: float
    confidence: float


def two_proportion_difference(
    successes_treatment: int,
    n_treatment: int,
    successes_control: int,
    n_control: int,
    *,
    alpha: float = 0.05,
) -> ProportionDifference:
    """The z test and (1 - alpha) Wald interval for rate(treatment) - rate(control).

    The test uses the pooled rate under the null of equal rates; the interval uses the
    unpooled standard error sqrt(p1 q1 / n1 + p2 q2 / n2). Raises `StatsError` when the counts
    are impossible, when every unit in both groups has the same outcome, or when the rates are
    exactly 1 and 0; the interval would then have no width. A rate near 0 or 1, or a small group,
    makes the Wald interval unreliable; the review's rules say so when they use it.
    """
    _check_alpha(alpha)
    for name, successes, n in (
        ("treatment", successes_treatment, n_treatment),
        ("control", successes_control, n_control),
    ):
        if n < 1 or not 0 <= successes <= n:
            raise StatsError(f"{name}: {successes} successes out of {n} is not possible")
    rate_a, rate_b = successes_treatment / n_treatment, successes_control / n_control
    pooled = (successes_treatment + successes_control) / (n_treatment + n_control)
    if pooled in (0.0, 1.0):
        raise StatsError("every unit has the same outcome, so nothing can be tested")
    pooled_error = math.sqrt(pooled * (1 - pooled) * (1 / n_treatment + 1 / n_control))
    std_error = math.sqrt(rate_a * (1 - rate_a) / n_treatment + rate_b * (1 - rate_b) / n_control)
    if std_error == 0:
        raise StatsError(
            "the rates are exactly 1 and 0, so the interval would have no width and claim "
            "certainty the data cannot give"
        )
    difference = rate_a - rate_b
    z_statistic = difference / pooled_error
    margin = float(stats.norm.ppf(1 - alpha / 2)) * std_error
    return ProportionDifference(
        n_treatment=n_treatment,
        n_control=n_control,
        rate_treatment=rate_a,
        rate_control=rate_b,
        difference=difference,
        std_error=std_error,
        z_statistic=z_statistic,
        p_value=float(2 * stats.norm.sf(abs(z_statistic))),
        ci_low=difference - margin,
        ci_high=difference + margin,
        confidence=1 - alpha,
    )
