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
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import special, stats

SRM_ALPHA = 0.001  # section 9: the threshold used in the Kohavi, Tang and Xu treatment of SRM
SMALL_EXPECTED_COUNT = 100  # below it the rules use the exact tests (judgement, section 21.4)
_ENUMERATION_LIMIT = 1_000_000  # outcomes an exact test may list before the chi-square is kept
_TOLERANCE = 1e-7  # relative, on a probability: the rule scipy's binomtest and fisher_exact use


class StatsError(ValueError):
    """The input does not allow a meaningful answer; the message says why."""


def _check_alpha(alpha: float) -> None:
    if not 0 < alpha < 1:
        raise StatsError(f"alpha must be between 0 and 1, got {alpha!r}")


def _is_constant(values: Sequence[float]) -> bool:
    """True when the values are equal up to a few units of floating-point rounding.

    Exact repeats of a number such as 0.7 do not average back to 0.7 (`fsum([0.7] * 3) / 3`
    is not 0.7), so their variance comes out as rounding noise of about 1e-32 instead of 0 and
    an exact test for 0 misses them. The tolerance is relative, so it holds at any scale.
    """
    low, high = min(values), max(values)
    return high - low <= 8 * sys.float_info.epsilon * max(abs(low), abs(high))


def _is_whole(value: float) -> bool:
    """A whole number, as an int, a numpy integer or a float without a fraction; not a bool."""
    if isinstance(value, bool | np.bool_):
        return False
    try:
        return math.isfinite(value) and int(value) == value
    except (TypeError, ValueError, OverflowError):
        return False


def _finite(values: Sequence[float], name: str) -> list[float]:
    try:
        numbers = [float(value) for value in values]
    except OverflowError:  # an integer beyond any float
        raise StatsError(f"{name} must hold only finite numbers") from None
    if not all(math.isfinite(number) for number in numbers):
        raise StatsError(f"{name} must hold only finite numbers")
    return numbers


# --- Exact tests for counts too small for the chi-square approximation --------------------


def _compositions(total: int, parts: int) -> np.ndarray:
    """Every way to write `total` as an ordered sum of `parts` whole numbers of at least 0."""
    rows = np.zeros((1, 0), dtype=np.int64)
    remaining = np.array([total], dtype=np.int64)
    for _ in range(parts - 1):
        lengths = remaining + 1
        owner = np.repeat(np.arange(len(rows)), lengths)
        starts = np.cumsum(lengths) - lengths
        take = np.arange(int(lengths.sum())) - np.repeat(starts, lengths)
        rows = np.hstack([rows[owner], take[:, None]])
        remaining = remaining[owner] - take
    return np.hstack([rows, remaining[:, None]])


def _outcomes_listable(total: int, parts: int) -> bool:
    return math.comb(total + parts - 1, parts - 1) <= _ENUMERATION_LIMIT


def _exact_sample_ratio_p(observed: Sequence[int], shares: Sequence[float]) -> float | None:
    """The exact multinomial test: the chance, under the allocation, of a split no likelier
    than the one seen. None when there are too many splits to list."""
    total, arms = sum(int(n) for n in observed), len(observed)
    if not _outcomes_listable(total, arms):
        return None
    log_shares = np.log(np.asarray(shares, dtype=float))

    def log_probability(counts: np.ndarray) -> np.ndarray:
        return (
            special.gammaln(total + 1)
            - special.gammaln(counts + 1).sum(axis=-1)
            + counts @ log_shares
        )

    seen = log_probability(np.asarray(observed, dtype=np.int64))
    every = log_probability(_compositions(total, arms))
    return min(1.0, math.fsum(np.exp(every[every <= seen + _TOLERANCE])))


def _exact_homogeneity_p(successes: Sequence[int], totals: Sequence[int]) -> float | None:
    """The exact conditional test of a 2 x k table (Fisher's for k = 2, Freeman and Halton's
    for more): the chance, with the margins fixed, of a table no likelier than the one seen.
    None when there are too many tables to list."""
    size, hits = sum(int(n) for n in totals), sum(int(s) for s in successes)
    if hits > size - hits:  # a table and its mirror image are equally likely: list the shorter
        successes, hits = (
            [int(n) - int(s) for s, n in zip(successes, totals, strict=True)],
            size - hits,
        )
    groups = len(totals)
    if not _outcomes_listable(hits, groups):
        return None
    caps = np.asarray([int(n) for n in totals], dtype=np.int64)

    def log_probability(counts: np.ndarray) -> np.ndarray:
        within = (
            special.gammaln(caps + 1)
            - special.gammaln(counts + 1)
            - special.gammaln(caps - counts + 1)
        )
        pooled = (
            special.gammaln(size + 1) - special.gammaln(hits + 1) - special.gammaln(size - hits + 1)
        )
        return within.sum(axis=-1) - pooled

    candidates = _compositions(hits, groups)
    every = log_probability(candidates[(candidates <= caps).all(axis=1)])
    seen = log_probability(np.asarray(successes, dtype=np.int64))
    return min(1.0, math.fsum(np.exp(every[every <= seen + _TOLERANCE])))


# --- Sample ratio mismatch -----------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SrmResult:
    observed: tuple[int, ...]
    expected: tuple[float, ...]
    chi_square: float
    degrees_of_freedom: int
    p_value: float
    flagged: bool
    method: Literal["chi_square", "exact"] = "chi_square"


def srm_test(
    observed: Sequence[int],
    allocation: Sequence[float],
    *,
    alpha: float = SRM_ALPHA,
    exact_below: float | None = None,
) -> SrmResult:
    """Chi-square goodness of fit of observed arm counts against the registered allocation.

    The expected count of an arm is the total times its allocated share; the statistic is
    sum((observed - expected)^2 / expected) on (arms - 1) degrees of freedom, and the mismatch
    is flagged when p < alpha. An arm with no assignments counts as 0 rather than being left
    out, so a vanished arm shows up as the mismatch it is. Reference: Fabijan et al.,
    "Diagnosing Sample Ratio Mismatch in Online Controlled Experiments" (KDD 2019).

    The chi-square p value is an approximation that is too small, at the tail a rule needs,
    when an expected count is small. With `exact_below` set, a test whose smallest expected
    count is below it takes the exact multinomial p value instead (`method` says which one
    was used); the chi-square statistic is still reported. The exact test lists every possible
    split, so beyond 1,000,000 of them the chi-square is kept.
    """
    _check_alpha(alpha)
    if len(observed) != len(allocation) or len(observed) < 2:
        raise StatsError("need one count per arm for at least two arms, and one share per count")
    if not all(_is_whole(n) and n >= 0 for n in observed):
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
    method: Literal["chi_square", "exact"] = "chi_square"
    if exact_below is not None and min(expected) < exact_below:
        exact = _exact_sample_ratio_p(observed, shares)
        if exact is not None:
            p_value, method = exact, "exact"
    return SrmResult(
        observed=tuple(int(n) for n in observed),
        expected=expected,
        chi_square=chi_square,
        degrees_of_freedom=degrees,
        p_value=p_value,
        flagged=p_value < alpha,
        method=method,
    )


# --- Do groups share one rate? -------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class HomogeneityResult:
    successes: tuple[int, ...]
    totals: tuple[int, ...]
    chi_square: float
    degrees_of_freedom: int
    p_value: float
    smallest_expected: float
    method: Literal["chi_square", "exact"] = "chi_square"


def homogeneity_test(
    successes: Sequence[int], totals: Sequence[int], *, exact_below: float | None = None
) -> HomogeneityResult:
    """Pearson's chi-square test that every group has the same rate, without a continuity fix.

    The expected successes of a group are its size times the pooled rate; the statistic is
    sum((s - e)^2 / (n * rate * (1 - rate))) on (groups - 1) degrees of freedom. It is the
    test of a 2 x k table of successes and failures. The chi-square approximation is poor when
    an expected count is small, and `smallest_expected` reports the smallest one, over
    successes and failures. With `exact_below` set, a table whose smallest expected count is
    below it takes the exact conditional p value instead (Fisher's exact test for two groups,
    Freeman and Halton's for more; `method` says which was used), unless there are more than
    1,000,000 tables to list, when the chi-square is kept. Raises `StatsError` for fewer than
    two groups, an empty group, impossible counts, or when every unit in every group has the
    same outcome (the rate would then be 0 or 1 and nothing can differ).
    """
    if len(successes) != len(totals) or len(successes) < 2:
        raise StatsError("need a success count and a size for each of at least two groups")
    for s, n in zip(successes, totals, strict=True):
        if not (_is_whole(s) and _is_whole(n)):
            raise StatsError(f"counts must be whole numbers, got {s} and {n}")
        if n < 1 or not 0 <= s <= n:
            raise StatsError(f"{s} successes out of {n} is not possible")
    successes_all, size_all = sum(int(s) for s in successes), sum(int(n) for n in totals)
    if successes_all in (0, size_all):
        raise StatsError("every unit has the same outcome, so no group can differ from another")
    # With pooled rate S / N, (s - n * S / N)^2 / (n * S / N * (1 - S / N)) is, multiplied
    # through by N^2, (s * N - n * S)^2 / (n * S * (N - S)). Both sides are whole numbers, so
    # the quotient is rounded once, however large the counts or close the rate is to 0 or 1.
    chi_square = math.fsum(
        (int(s) * size_all - int(n) * successes_all) ** 2
        / (int(n) * successes_all * (size_all - successes_all))
        for s, n in zip(successes, totals, strict=True)
    )
    degrees = len(successes) - 1
    smallest = min(
        min(int(n) * successes_all, int(n) * (size_all - successes_all)) / size_all for n in totals
    )
    p_value = float(stats.chi2.sf(chi_square, degrees))
    method: Literal["chi_square", "exact"] = "chi_square"
    if exact_below is not None and smallest < exact_below:
        exact = _exact_homogeneity_p(successes, totals)
        if exact is not None:
            p_value, method = exact, "exact"
    return HomogeneityResult(
        successes=tuple(int(s) for s in successes),
        totals=tuple(int(n) for n in totals),
        chi_square=chi_square,
        degrees_of_freedom=degrees,
        p_value=p_value,
        smallest_expected=smallest,
        method=method,
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
    if _is_constant(values):
        return values[0], 0.0
    try:
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)
    except OverflowError:  # the sum or a squared deviation is beyond any float
        raise StatsError(f"{name} holds values too large to square") from None
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
    # Welch-Satterthwaite, written with each part as a share of the total so that squaring
    # cannot underflow or overflow when the variances are far from 1.
    share_a, share_b = part_a / (part_a + part_b), part_b / (part_a + part_b)
    degrees = 1.0 / (share_a**2 / (len(a) - 1) + share_b**2 / (len(b) - 1))
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
        if not (_is_whole(successes) and _is_whole(n)):
            raise StatsError(f"{name}: counts must be whole numbers, got {successes} and {n}")
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
    if second == 0 or _is_constant(numbers):
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
    treated, controls = _finite(treatment, "treatment"), _finite(control, "control")
    for name, group in (("treatment", treated), ("control", controls)):
        if len(group) < 2:
            raise StatsError(f"{name} needs at least 2 values, got {len(group)}")
    if _is_constant(treated) and _is_constant(controls):
        raise StatsError("neither group varies, so the interval would have no width")
    a, b = np.asarray(treated), np.asarray(controls)
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
    # Rounding leaves a residue of either sign when y is exactly proportional to x (or both are
    # constant); anything below 1e-13 of the variance of the two inputs is that residue.
    residue = 1e-13 * (var_y + ratio**2 * var_x) / (n * mean_x**2)
    if variance <= residue or (_is_constant(y) and _is_constant(x)):
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


# --- Does an effect change from one cohort to the next? ------------------------------------


@dataclass(frozen=True, kw_only=True)
class CohortHeterogeneity:
    """Whether an arm's difference against control varies across cohorts, and whether it trends.

    `q_statistic` is Cochran's Q, which asks whether the cohorts' differences are all equal;
    `slope` is the weighted straight-line trend of the difference across the cohorts' positions
    (for example the week of first exposure), which asks the narrower question of whether it
    rises or falls steadily.
    """

    cohorts: int
    pooled_difference: float
    q_statistic: float
    degrees_of_freedom: int
    q_p_value: float
    i_squared: float
    slope: float
    slope_std_error: float
    slope_z_statistic: float
    slope_p_value: float


def cohort_heterogeneity(
    differences: Sequence[float],
    std_errors: Sequence[float],
    *,
    positions: Sequence[float] | None = None,
) -> CohortHeterogeneity:
    """Cochran's Q and a weighted trend for one arm's difference in each of several cohorts.

    Each cohort contributes its estimated difference and that estimate's standard error; the
    cohorts must be made of different units, so that the estimates are independent. Weights are
    1 / se^2, Q = sum(w (d - pooled)^2) is compared with a chi-square on (cohorts - 1) degrees of
    freedom, and I^2 = max(0, (Q - df) / Q) is the share of the variation beyond chance. The
    slope is weighted least squares of the difference on `positions` (default 0, 1, 2, ...) with
    the standard errors taken as known, so its error is 1 / sqrt(sum(w (x - xbar)^2)).
    Reference: Cochran, "The combination of estimates from different experiments" (1954);
    Higgins and Thompson, "Quantifying heterogeneity in a meta-analysis" (2002). The test has
    little power with few or small cohorts, and a significant result says the difference changes,
    not why. Raises `StatsError` for fewer than 2 cohorts or an unusable standard error.
    """
    d = _finite(differences, "differences")
    se = _finite(std_errors, "std_errors")
    if len(d) != len(se):
        raise StatsError(f"need one standard error per difference, got {len(d)} and {len(se)}")
    k = len(d)
    if k < 2:
        raise StatsError(f"need at least 2 cohorts, got {k}")
    if any(error <= 0 for error in se):
        raise StatsError("every standard error must be above 0")
    x = list(range(k)) if positions is None else _finite(positions, "positions")
    if len(x) != k:
        raise StatsError(f"need one position per cohort, got {len(x)} for {k}")
    if len(set(x)) < 2:
        raise StatsError("the cohorts need at least 2 different positions to have a trend")

    # Weights are 1 / se^2, so standard errors far from 1 can underflow to a zero weight or
    # overflow a sum. Any such failure is one clear error, not a crash from inside the sums.
    try:
        weight = [1.0 / error**2 for error in se]
        total_weight = math.fsum(weight)
        pooled = math.fsum(w * v for w, v in zip(weight, d, strict=True)) / total_weight
        q_statistic = math.fsum(w * (v - pooled) ** 2 for w, v in zip(weight, d, strict=True))
        x_bar = math.fsum(w * p for w, p in zip(weight, x, strict=True)) / total_weight
        spread = math.fsum(w * (p - x_bar) ** 2 for w, p in zip(weight, x, strict=True))
        if not (spread > 0 and math.isfinite(q_statistic)):  # an infinite spread fails below
            raise ArithmeticError
        slope = (
            math.fsum(w * (p - x_bar) * v for w, p, v in zip(weight, x, d, strict=True)) / spread
        )
        slope_error = 1.0 / math.sqrt(spread)
        slope_z = slope / slope_error
    except (ArithmeticError, ValueError):  # zero division, overflow, a non-finite sum
        raise StatsError(
            "the standard errors are too small or too large to weigh the cohorts"
        ) from None
    degrees = k - 1
    return CohortHeterogeneity(
        cohorts=k,
        pooled_difference=pooled,
        q_statistic=q_statistic,
        degrees_of_freedom=degrees,
        q_p_value=float(stats.chi2.sf(q_statistic, degrees)),
        i_squared=max(0.0, (q_statistic - degrees) / q_statistic) if q_statistic > 0 else 0.0,
        slope=slope,
        slope_std_error=slope_error,
        slope_z_statistic=slope_z,
        slope_p_value=float(2 * stats.norm.sf(abs(slope_z))),
    )


# --- Several comparisons at once -----------------------------------------------------------
#
# Dunnett's test, which section 9 names as the less conservative choice for several arms
# against one control, is not implemented: the corrections here work from p-values, and
# scipy.stats.dunnett (which takes the samples) can be added if a rule needs it.


@dataclass(frozen=True, kw_only=True)
class Adjusted:
    """Adjusted p-values in the order the raw ones were given, and which stay significant."""

    method: str
    alpha: float
    p_values: tuple[float, ...]
    adjusted: tuple[float, ...]
    rejected: tuple[bool, ...]


def _check_p_values(p_values: Sequence[float]) -> list[float]:
    values = _finite(p_values, "p_values")
    if not values:
        raise StatsError("need at least one p-value")
    if any(not 0.0 <= p <= 1.0 for p in values):
        raise StatsError(f"p-values must be between 0 and 1, got {values!r}")
    return values


def bonferroni(p_values: Sequence[float], *, alpha: float = 0.05) -> Adjusted:
    """Bonferroni: each p-value times the number of comparisons, capped at 1.

    It controls the chance of any false positive among the comparisons. A comparison stays
    significant when its adjusted p-value is at most `alpha`.
    """
    _check_alpha(alpha)
    values = _check_p_values(p_values)
    adjusted = tuple(min(1.0, p * len(values)) for p in values)
    return Adjusted(
        method="bonferroni",
        alpha=alpha,
        p_values=tuple(values),
        adjusted=adjusted,
        rejected=tuple(a <= alpha for a in adjusted),
    )


def _step_up(values: list[float], *, method: str, alpha: float, inflation: float) -> Adjusted:
    """The step-up adjustment shared by Benjamini-Hochberg (inflation 1) and Yekutieli."""
    m = len(values)
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, values[index] * m * inflation / rank)
        adjusted[index] = running
    return Adjusted(
        method=method,
        alpha=alpha,
        p_values=tuple(values),
        adjusted=tuple(adjusted),
        rejected=tuple(a <= alpha for a in adjusted),
    )


def benjamini_hochberg(p_values: Sequence[float], *, alpha: float = 0.05) -> Adjusted:
    """Benjamini-Hochberg: controls the expected share of false positives among the discoveries.

    With m comparisons and the p-values sorted ascending, the adjusted value of the i-th is the
    smallest of m * p_j / j over all j from i upward, capped at 1; ties share one value. It is
    less conservative than Bonferroni and assumes independent or positively dependent tests.
    Reference: Benjamini and Hochberg, "Controlling the false discovery rate" (1995); that it
    also holds under positive dependence is Benjamini and Yekutieli (2001). When the dependence
    between the tests is unknown, for example arms compared with one shared control, use
    `benjamini_yekutieli`, which holds under any dependence.
    """
    _check_alpha(alpha)
    return _step_up(
        _check_p_values(p_values), method="benjamini_hochberg", alpha=alpha, inflation=1.0
    )


def benjamini_yekutieli(p_values: Sequence[float], *, alpha: float = 0.05) -> Adjusted:
    """Benjamini-Yekutieli: false-discovery-rate control under any dependence between the tests.

    It is Benjamini-Hochberg with every adjusted value multiplied by 1 + 1/2 + ... + 1/m, so it
    is more conservative; the price of not assuming anything about the dependence. Reference:
    Benjamini and Yekutieli, "The control of the false discovery rate in multiple testing under
    dependency" (Annals of Statistics, 2001).
    """
    _check_alpha(alpha)
    values = _check_p_values(p_values)
    harmonic = math.fsum(1.0 / k for k in range(1, len(values) + 1))
    return _step_up(values, method="benjamini_yekutieli", alpha=alpha, inflation=harmonic)
