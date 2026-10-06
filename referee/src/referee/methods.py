"""The statistics the results review uses. Pure functions on numbers: no files, no clock.

Each function says what it computes and where the formula comes from, and the tests check it
against an independent implementation (`scipy`, `statsmodels`) or a known answer. A function
that cannot give a meaningful answer for its input raises `StatsError` instead of returning NaN
or a confident-looking number: a confidence interval of zero width from data with no variation
would claim certainty the data cannot give.

The bootstrap draws its own indices from the raw output of numpy's PCG64 generator, because
numpy does not promise that `Generator.integers` keeps its output between versions, and a
changed output would silently change every interval in every saved report.

Sums use `math.fsum`, which is exactly rounded and so does not depend on the order of the values
or on the platform. The distribution functions come from `scipy.stats`; their last digits can
differ between scipy versions, so reports round what they print.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
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


# --- How heavy the tail of a metric is -----------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class HeavyTail:
    n: int
    excess_kurtosis: float
    top_percent: int
    top_count: int
    top_share: float


def heavy_tail_measures(values: Sequence[float], *, top_percent: int = 1) -> HeavyTail:
    """How concentrated and how heavy-tailed a non-negative metric is. A description, not a test.

    `excess_kurtosis` is m4 / m2^2 - 3 with the moments taken about the mean and divided by n
    (what `scipy.stats.kurtosis` returns by default), so it is 0 for a normal distribution.
    `top_share` is the share of the total held by the largest `ceil(n * top_percent / 100)`
    values, the same rule the lab's readout uses for revenue. Both are noisy for small groups.
    Raises `StatsError` for fewer than 2 values, no variation, a negative value or a total of 0.
    """
    if (
        isinstance(top_percent, bool)
        or not isinstance(top_percent, int)
        or not 1 <= top_percent <= 99
    ):
        raise StatsError(f"top_percent must be a whole number from 1 to 99, got {top_percent!r}")
    numbers = _finite(values, "values")
    if len(numbers) < 2:
        raise StatsError(f"values needs at least 2 values, got {len(numbers)}")
    if min(numbers) < 0:
        raise StatsError("the top share is defined for non-negative values only")
    total = math.fsum(numbers)
    if total == 0:
        raise StatsError("the values sum to 0, so no value holds a share of the total")
    n = len(numbers)
    mean = total / n
    second = math.fsum((v - mean) ** 2 for v in numbers) / n
    if second == 0:
        raise StatsError("the values do not vary, so the kurtosis is undefined")
    fourth = math.fsum((v - mean) ** 4 for v in numbers) / n
    top_count = (n * top_percent + 99) // 100
    top = sorted(numbers, reverse=True)[:top_count]
    return HeavyTail(
        n=n,
        excess_kurtosis=fourth / second**2 - 3.0,
        top_percent=top_percent,
        top_count=top_count,
        top_share=math.fsum(top) / total,
    )


# --- A seeded percentile bootstrap for a difference in means -------------------------------

_CHUNK_ELEMENTS = 2_000_000  # indices drawn at a time; the answer does not depend on it


@dataclass(frozen=True, kw_only=True)
class BootstrapInterval:
    difference: float
    ci_low: float
    ci_high: float
    confidence: float
    resamples: int
    seed: int


def _bootstrap_means(values: np.ndarray, resamples: int, generator: np.random.PCG64) -> np.ndarray:
    """The mean of `resamples` samples drawn with replacement, taken one after another.

    An index is the high 32 bits of a raw 64-bit output times the group size, shifted down 32
    bits: exact integer arithmetic, uniform to within size / 2^32, and always in range. The
    draws are consumed in a fixed order, so the result does not depend on how they are chunked.
    """
    size = len(values)
    rows_per_chunk = max(1, _CHUNK_ELEMENTS // size)
    means = np.empty(resamples)
    done = 0
    while done < resamples:
        rows = min(rows_per_chunk, resamples - done)
        raw = generator.random_raw(rows * size)
        indices = ((raw >> np.uint64(32)) * np.uint64(size)) >> np.uint64(32)
        means[done : done + rows] = values[indices.reshape(rows, size)].sum(axis=1) / size
        done += rows
    return means


def bootstrap_difference(
    treatment: Sequence[float],
    control: Sequence[float],
    *,
    seed: int,
    alpha: float = 0.05,
    resamples: int = 10_000,
) -> BootstrapInterval:
    """A percentile bootstrap (1 - alpha) interval for mean(treatment) - mean(control).

    Each group is resampled with replacement `resamples` times; the interval runs from the
    alpha/2 to the 1 - alpha/2 quantile of the resampled differences. The same values and seed
    give the same interval on any machine with the same numpy, and a test pins one such answer
    so that a changed random stream is noticed. The interval depends on the order of the values
    (the loader puts them in a canonical order). The percentile method is a rough interval for
    small groups; it is reported next to Welch's, not instead of it. Raises `StatsError` when a
    group has fewer than 2 values or fewer than 5 resamples would fall in each tail.
    """
    _check_alpha(alpha)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise StatsError(f"seed must be a whole number of at least 0, got {seed!r}")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples * alpha / 2 < 5:
        raise StatsError(
            f"resamples={resamples!r} leaves fewer than 5 resamples in each tail at alpha={alpha}"
        )
    a = np.asarray(_finite(treatment, "treatment"))
    b = np.asarray(_finite(control, "control"))
    for name, group in (("treatment", a), ("control", b)):
        if len(group) < 2:
            raise StatsError(f"{name} needs at least 2 values, got {len(group)}")
    generator = np.random.PCG64(np.random.SeedSequence(seed))
    differences = _bootstrap_means(a, resamples, generator) - _bootstrap_means(
        b, resamples, generator
    )
    low, high = np.quantile(differences, [alpha / 2, 1 - alpha / 2])
    return BootstrapInterval(
        difference=math.fsum(a.tolist()) / len(a) - math.fsum(b.tolist()) / len(b),
        ci_low=float(low),
        ci_high=float(high),
        confidence=1 - alpha,
        resamples=resamples,
        seed=seed,
    )


# --- A difference in ratios, by the delta method -------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RatioEstimate:
    n: int
    ratio: float
    std_error: float


def ratio_estimate(numerator: Sequence[float], denominator: Sequence[float]) -> RatioEstimate:
    """The ratio mean(numerator) / mean(denominator) of per-unit quantities, and its error.

    By the delta method, Var(Y/X) is about (1 / mu_X^2) * (var_Y - 2 R cov_XY + R^2 var_X) / n,
    where R = mu_Y / mu_X and the variances and covariance are per unit. This is not the
    variance of the unit-level ratios Y_i / X_i, which answers a different question whenever the
    denominators differ. Reference: Deng, Knoblich and Lu, "Applying the Delta Method in Metric
    Analytics" (2018, arXiv:1803.06336). Raises `StatsError` for fewer than 2 units, a mean
    denominator of 0, or no variation in the ratio.
    """
    y, x = _finite(numerator, "numerator"), _finite(denominator, "denominator")
    if len(y) != len(x):
        raise StatsError(f"need one denominator per numerator, got {len(y)} and {len(x)}")
    n = len(y)
    if n < 2:
        raise StatsError(f"need at least 2 units, got {n}")
    mean_y, mean_x = math.fsum(y) / n, math.fsum(x) / n
    if mean_x == 0:
        raise StatsError("the mean denominator is 0, so the ratio is undefined")
    var_y = math.fsum((v - mean_y) ** 2 for v in y) / (n - 1)
    var_x = math.fsum((v - mean_x) ** 2 for v in x) / (n - 1)
    cov = math.fsum((a - mean_y) * (b - mean_x) for a, b in zip(y, x, strict=True)) / (n - 1)
    ratio = mean_y / mean_x
    variance = (var_y - 2 * ratio * cov + ratio**2 * var_x) / (n * mean_x**2)
    if variance <= 0:  # a tiny negative value is rounding; zero means the ratio never varies
        raise StatsError("the ratio does not vary across units, so its standard error is 0")
    return RatioEstimate(n=n, ratio=ratio, std_error=math.sqrt(variance))


@dataclass(frozen=True, kw_only=True)
class RatioDifference:
    ratio_treatment: float
    ratio_control: float
    difference: float
    std_error: float
    z_statistic: float
    p_value: float
    ci_low: float
    ci_high: float
    confidence: float


def ratio_difference(
    numerator_treatment: Sequence[float],
    denominator_treatment: Sequence[float],
    numerator_control: Sequence[float],
    denominator_control: Sequence[float],
    *,
    alpha: float = 0.05,
) -> RatioDifference:
    """Treatment minus control for a ratio metric: the groups are independent, so the variances
    of the two ratios add, and the test and interval use the normal approximation."""
    _check_alpha(alpha)
    treatment = ratio_estimate(numerator_treatment, denominator_treatment)
    control = ratio_estimate(numerator_control, denominator_control)
    std_error = math.hypot(treatment.std_error, control.std_error)
    difference = treatment.ratio - control.ratio
    z_statistic = difference / std_error
    margin = float(stats.norm.ppf(1 - alpha / 2)) * std_error
    return RatioDifference(
        ratio_treatment=treatment.ratio,
        ratio_control=control.ratio,
        difference=difference,
        std_error=std_error,
        z_statistic=z_statistic,
        p_value=float(2 * stats.norm.sf(abs(z_statistic))),
        ci_low=difference - margin,
        ci_high=difference + margin,
        confidence=1 - alpha,
    )
