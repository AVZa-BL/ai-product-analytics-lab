"""The pooled effect of an arm against control, for heavy-tailed outcomes (design section 21.10).

Step 7b of milestone 4b-2. RES-008 prints Welch's 95% interval for the difference of means of
an arm and control and shows no bootstrap interval (section 21.11); this study measured the
seeded percentile bootstrap interval as well, to decide that. It measures how often each
interval excludes the TRUE difference when the outcome is a revenue
that most players leave at zero, by the split between the arms, the size of the smaller arm,
the effect, the heaviness of the tail and the share of players who spend, on which side it
misses, and what candidate warnings (Kohavi's skewness rule, a kurtosis, a top-1% share) say in
the runs where it does and in the runs where it does not.

    python tests/pooled_simulation.py --reps 20000 --boot-reps 2000 --workers 4 \\
        --out docs/simulations/pooled_effect_heavy.json

The blocks of the grid: the main one (outcomes x splits x sizes up to 3,000 players in the
smaller arm x no effect and +20%), a block of large arms (10,000 to 100,000), an effect ladder
(+50%, +100%), and payer shares of 3% and 30%. The bootstrap, which is slow, runs on a subset
of the main block. Every statistic is checked against `referee.methods` in the tests. The
tailed outcomes are drawn sparsely (the number of players who spend is binomial, and only their
amounts are drawn), which is the same distribution as drawing every player; so is the sparse
bootstrap, whose resamples draw a binomial number of the nonzero values instead of every value.
"""

import argparse
import math
import shlex
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from cohort_simulation import (
    BASE,
    LOG_SD,
    PAYING,
    SD,
    SPEND_SD,
    TAILED,
    render,
)
from scipy import stats

ALPHA = 0.05  # the intervals are 95% intervals
RESAMPLES = 10_000  # `methods.bootstrap_difference` resamples this many times by default
PICKS_AT_A_TIME = 50_000  # nonzero values drawn at a time by the sparse bootstrap
OUTCOMES = ("normal", "lognormal", *TAILED)
BOOT_OUTCOMES = (
    TAILED  # the sparse bootstrap needs zeros to be cheap, and revenue is what it is for
)
EFFECTS = (0.0, 0.2)  # the effects of the main block: none, and +20% of the control's mean
RATIOS = (1, 1.5, 2, 2.5, 3, 4, 9)  # larger arm : smaller arm
SIZES = (100, 300, 1000, 3000)  # players in the smaller arm, main block
BOOT_RATIOS = (1, 2, 3, 9)
BOOT_SIZES = (100, 300, 1000)
BOOT_MOST_PLAYERS = 5000  # beyond this many in the larger arm the bootstrap gets half the runs
LARGE_FROM = 10_000  # a smaller arm this big is in the block of large arms (fewer runs)
LARGE_SIZES = (10_000, 30_000, 100_000)
LARGE_OUTCOMES = ("lognormal", *TAILED)
LARGE_RATIOS = (1, 3, 9)  # 9 only up to 30,000 in the smaller arm
LADDER_EFFECTS = (0.5, 1.0)
LADDER_OUTCOMES = ("revenue", "revenue_heavy")
LADDER_SIZES = (100, 1000)
LADDER_RATIOS = (1, 3, 9)
PAYER_SHARES = (0.03, 0.30)  # the main block has 0.13
PAYER_OUTCOMES = ("revenue", "revenue_heavy")
PAYER_SIZES = (300, 1000, 10_000)
PAYER_RATIOS = (1, 3, 9)
KURTOSIS_THRESHOLDS = (50, 100, 200, 500, 1000)
TOP_SHARE_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
KOHAVI = 355  # Kohavi, Deng, Longbotham, Xu (2014), rule 7: n >= 355 * skewness^2 for a normal mean
OR_KURTOSIS, OR_TOP_SHARE = 100, 0.5  # the limbs tried beside Kohavi's rule, and on all arms
TALLY = ("fired", "above_fired", "below_fired", "above_not", "below_not")  # a criterion's counts
SHAPE_PERCENTILES = (5, 50, 95)
ERROR_PERCENTILES = (2.5, 50, 97.5)


@dataclass(frozen=True)
class Cell:
    outcome: str
    arm_n: int
    control_n: int
    effect: float  # the arm's mean is the control's times (1 + effect)
    paying: float | None = None  # the share of players who spend; None is PAYING

    @property
    def share(self) -> float:
        return PAYING if self.paying is None else self.paying

    @property
    def arm_mean(self) -> float:
        return BASE[self.outcome] * (1 + self.effect)

    @property
    def truth(self) -> float:
        """The true difference of means, arm less control."""
        return self.arm_mean - BASE[self.outcome]

    @property
    def ratio(self) -> float:
        return max(self.arm_n, self.control_n) / min(self.arm_n, self.control_n)

    def seed_sequence(self, seed: int) -> np.random.SeedSequence:
        key = f"pooled|{self.outcome}|{self.arm_n}|{self.control_n}|{self.effect}|{self.paying}"
        return np.random.SeedSequence([seed, zlib.crc32(key.encode())])


@dataclass
class ArmSample:
    """`size` simulated arms of n players: the statistics of each, as arrays of length `size`."""

    n: int
    mean: np.ndarray
    variance: np.ndarray  # unbiased
    skewness: np.ndarray  # biased, as scipy.stats.skew and the export checks use it
    kurtosis: np.ndarray  # excess, biased, as scipy.stats.kurtosis and `heavy_tail_measures`
    top_share: np.ndarray  # the share of the total held by the largest ceil(n / 100) values
    nonzero: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None  # count, values, starts


def _top_count(n: int) -> int:
    return -(-n // 100)


def _statistics(n: int, sums: list[np.ndarray], top: np.ndarray) -> tuple[np.ndarray, ...]:
    """Mean, unbiased variance, skewness, excess kurtosis and top share from power sums."""
    m = sums[0] / n
    m2 = sums[1] / n - m**2
    m3 = sums[2] / n - 3 * m * sums[1] / n + 2 * m**3
    m4 = sums[3] / n - 4 * m * sums[2] / n + 6 * m**2 * sums[1] / n - 3 * m**4
    with np.errstate(divide="ignore", invalid="ignore"):
        skew, kurt, share = m3 / m2**1.5, m4 / m2**2 - 3, top / sums[0]
    return m, m2 * n / (n - 1), skew, kurt, share


def draw_arm(
    outcome: str,
    mean: float,
    n: int,
    rng: np.random.Generator,
    size: int,
    keep: bool = False,
    paying: float = PAYING,
) -> ArmSample:
    """`size` arms of n players with the given mean per player.

    A tailed outcome draws only the players who spend: how many (binomial) and what they spend
    (lognormal). `keep` also returns those amounts, for the bootstrap.
    """
    if outcome in SPEND_SD:
        sd = SPEND_SD[outcome]
        mu = math.log(mean / paying) - sd**2 / 2  # a paying player spends mean / paying on average
        count = rng.binomial(n, paying, size=size)
        values = np.exp(mu + sd * rng.standard_normal(int(count.sum())))
        owner = np.repeat(np.arange(size), count)
        square = values * values
        sums = [
            np.bincount(owner, weights=w, minlength=size)
            for w in (values, square, square * values, square * square)
        ]
        starts = np.cumsum(count) - count
        top_n = _top_count(n)
        grid = np.zeros((size, max(int(count.max(initial=0)), top_n)))
        grid[owner, np.arange(values.size) - np.repeat(starts, count)] = values
        top = np.partition(grid, grid.shape[1] - top_n, axis=1)[:, grid.shape[1] - top_n :]
        m, v, skew, kurt, share = _statistics(n, sums, top.sum(axis=1))
        return ArmSample(n, m, v, skew, kurt, share, (count, values, starts) if keep else None)
    if outcome == "lognormal":
        x = np.exp(math.log(mean) - LOG_SD**2 / 2 + LOG_SD * rng.standard_normal((size, n)))
    elif outcome == "normal":
        x = mean + SD * rng.standard_normal((size, n))
    else:
        raise ValueError(f"unknown outcome {outcome!r}")
    centred = x - x.mean(axis=1, keepdims=True)
    squared = centred * centred
    m2, m3, m4 = squared.mean(axis=1), (squared * centred).mean(axis=1), (squared**2).mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        skew, kurt = m3 / m2**1.5, m4 / m2**2 - 3
    if outcome == "normal":  # negative values are possible: no share of a total
        share = np.full(size, np.nan)
    else:
        top_n = _top_count(n)
        share = np.partition(x, n - top_n, axis=1)[:, n - top_n :].sum(axis=1) / x.sum(axis=1)
    return ArmSample(n, x.mean(axis=1), m2 * n / (n - 1), skew, kurt, share)


def welch_interval(
    arm: ArmSample, control: ArmSample, alpha: float = ALPHA
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Welch's interval for arm less control, as `methods.welch_difference`, per replication.

    Returns the low and high end and whether the interval exists (some player varies).
    """
    part_a, part_c = arm.variance / arm.n, control.variance / control.n
    total = part_a + part_c
    exists = total > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        share_a, share_c = part_a / total, part_c / total
        dof = 1.0 / (share_a**2 / (arm.n - 1) + share_c**2 / (control.n - 1))
        margin = stats.t.ppf(1 - alpha / 2, dof) * np.sqrt(total)
    difference = arm.mean - control.mean
    return difference - margin, difference + margin, exists


def sparse_resample_means(
    values: np.ndarray, n: int, resamples: int, rng: np.random.Generator
) -> np.ndarray:
    """The means of `resamples` samples of n drawn with replacement from n values, `values` of
    which are the nonzero ones. A resample holds a binomial number of the nonzero values, each
    one drawn uniformly among them, so only those are drawn. The resamples are taken a few
    thousand picks at a time because that is ten times faster than one array of all of them."""
    m = len(values)
    if m == 0:
        return np.zeros(resamples)
    means = np.empty(resamples)
    step = max(1, PICKS_AT_A_TIME // m)
    for start in range(0, resamples, step):
        size = min(step, resamples - start)
        count = rng.binomial(n, m / n, size=size)
        picked = values[rng.integers(0, m, size=int(count.sum()), dtype=np.int32)]
        running = np.concatenate([[0.0], np.cumsum(picked)])
        ends = np.cumsum(count)
        means[start : start + size] = (running[ends] - running[ends - count]) / n
    return means


def bootstrap_interval(
    arm_values: np.ndarray,
    arm_n: int,
    control_values: np.ndarray,
    control_n: int,
    rng: np.random.Generator,
    resamples: int = RESAMPLES,
    alpha: float = ALPHA,
) -> tuple[float, float]:
    """The percentile interval of `methods.bootstrap_difference`, for sparse data."""
    differences = sparse_resample_means(arm_values, arm_n, resamples, rng) - sparse_resample_means(
        control_values, control_n, resamples, rng
    )
    low, high = np.quantile(differences, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high)


def criteria(arm: ArmSample, control: ArmSample) -> dict[str, np.ndarray]:
    """Which candidate warnings fire, per replication.

    Kohavi's rule as a sample rule (|skewness| > 1 and n < 355 skewness^2) and an excess
    kurtosis or a top-1% share beyond a threshold, each on any arm; the two limbs of the OR with
    Kohavi's rule, and the same thresholds on all arms.
    """
    arms = (arm, control)
    found: dict[str, np.ndarray] = {}
    found["kohavi"] = np.logical_or.reduce(
        [(np.abs(a.skewness) > 1) & (a.n < KOHAVI * a.skewness**2) for a in arms]
    )
    for t in KURTOSIS_THRESHOLDS:
        found[f"kurtosis>{t}"] = np.logical_or.reduce([a.kurtosis > t for a in arms])
    for t in TOP_SHARE_THRESHOLDS:
        found[f"top_share>{t}"] = np.logical_or.reduce([a.top_share > t for a in arms])
    found[f"all:kurtosis>{OR_KURTOSIS}"] = np.logical_and.reduce(
        [a.kurtosis > OR_KURTOSIS for a in arms]
    )
    found[f"all:top_share>{OR_TOP_SHARE}"] = np.logical_and.reduce(
        [a.top_share > OR_TOP_SHARE for a in arms]
    )
    found[f"kohavi|kurtosis>{OR_KURTOSIS}"] = found["kohavi"] | found[f"kurtosis>{OR_KURTOSIS}"]
    found[f"kohavi|top_share>{OR_TOP_SHARE}"] = found["kohavi"] | found[f"top_share>{OR_TOP_SHARE}"]
    return found


def applicable(cell: Cell, criterion: str) -> bool:
    """A normal outcome can be negative, so it has no share of a total."""
    return not (cell.outcome == "normal" and "top_share" in criterion)


def chunk_size(cell: Cell) -> int:
    """Replications drawn at once: from the sizes of the cell alone, so that the same settings
    always draw the same numbers. The first chunk of a cell is the same whatever the number of
    replications, as long as there are at least that many."""
    return int(min(5000, max(20, 4_000_000 // (cell.arm_n + cell.control_n))))


def wants_bootstrap(cell: Cell) -> bool:
    return (
        cell.outcome in BOOT_OUTCOMES
        and cell.paying is None
        and cell.effect in EFFECTS
        and min(cell.arm_n, cell.control_n) in BOOT_SIZES
        and round(cell.ratio, 3) in BOOT_RATIOS
        and (cell.effect > 0 or cell.arm_n >= cell.control_n)
    )


def reps_for(cell: Cell, reps: int, large_reps: int) -> int:
    return large_reps if min(cell.arm_n, cell.control_n) >= LARGE_FROM else reps


def boot_reps_for(cell: Cell, boot_reps: int, reps: int) -> int:
    """The replications that get a bootstrap: none for most cells, half for the larger ones."""
    if not wants_bootstrap(cell):
        return 0
    wanted = boot_reps if max(cell.arm_n, cell.control_n) <= BOOT_MOST_PLAYERS else boot_reps // 2
    return min(wanted, reps)


def _ratio(count: float, total: float) -> float:
    return round(float(count) / total, 5)


def _percentiles(values: np.ndarray, which: tuple[float, ...]) -> list[float | None]:
    if np.isnan(values).all():
        return [None] * len(which)
    return [round(float(x), 5) for x in np.nanpercentile(values, which)]


def run_cell(cell: Cell, reps: int, boot_reps: int, seed: int) -> dict:
    """One row of the study.

    Welch's interval and the sample shapes come from `reps` replications; the bootstrap, and
    Welch's interval on the same data for a fair comparison, from the first `boot_reps` of them
    (`boot_reps` is what `boot_reps_for` gave the cell). Counts are of replications; a "miss" is
    an interval that excludes the true difference, "above" when the interval lies wholly above
    it (the arm looks better than it is) and "below" when wholly below.
    """
    chunk = chunk_size(cell)
    streams = cell.seed_sequence(seed).spawn((reps + chunk - 1) // chunk)
    truth = cell.truth
    keep_error: list[np.ndarray] = []
    keep_se: list[np.ndarray] = []
    shapes: dict[str, list[np.ndarray]] = {
        f"{who}_{what}": [] for who in ("arm", "control") for what in ("skew", "kurt", "share")
    }
    count = dict.fromkeys(
        ("above", "below", "undefined", "b_above", "b_below", "b_undefined", "p_above", "p_below"),
        0,
    )
    pairs = {side: [0, 0, 0] for side in ("above", "below")}  # both, Welch only, bootstrap only
    width = dict.fromkeys(("welch", "p_welch", "boot"), 0.0)
    tallies: dict[str, list[int]] = {}
    done = 0
    for stream in streams:
        sample_stream, boot_stream = stream.spawn(2)
        rng, boot_rng = np.random.default_rng(sample_stream), np.random.default_rng(boot_stream)
        size = min(chunk, reps - done)
        nb = max(0, min(size, boot_reps - done))
        control = draw_arm(
            cell.outcome, BASE[cell.outcome], cell.control_n, rng, size, nb > 0, cell.share
        )
        arm = draw_arm(cell.outcome, cell.arm_mean, cell.arm_n, rng, size, nb > 0, cell.share)
        low, high, exists = welch_interval(arm, control)
        above, below = (low > truth) & exists, (high < truth) & exists
        count["above"] += int(above.sum())
        count["below"] += int(below.sum())
        count["undefined"] += int((~exists).sum())
        width["welch"] += float((high - low)[exists].sum())
        keep_error.append((arm.mean - control.mean - truth)[exists])
        keep_se.append(((high - low) / 2)[exists])
        for who, sample in (("arm", arm), ("control", control)):
            shapes[f"{who}_skew"].append(sample.skewness)
            shapes[f"{who}_kurt"].append(sample.kurtosis)
            shapes[f"{who}_share"].append(sample.top_share)
        for name, hit in criteria(arm, control).items():
            if applicable(cell, name):
                t = tallies.setdefault(name, [0] * len(TALLY))
                t[0] += int(hit.sum())
                t[1] += int((above & hit).sum())
                t[2] += int((below & hit).sum())
                t[3] += int((above & ~hit).sum())
                t[4] += int((below & ~hit).sum())
        if nb:
            a_nonzero, c_nonzero = arm.nonzero, control.nonzero
            assert a_nonzero is not None and c_nonzero is not None
            b_above, b_below = np.zeros(nb, bool), np.zeros(nb, bool)
            for r in range(nb):
                if not exists[r]:
                    continue
                b_low, b_high = bootstrap_interval(
                    a_nonzero[1][a_nonzero[2][r] : a_nonzero[2][r] + a_nonzero[0][r]],
                    cell.arm_n,
                    c_nonzero[1][c_nonzero[2][r] : c_nonzero[2][r] + c_nonzero[0][r]],
                    cell.control_n,
                    boot_rng,
                )
                b_above[r], b_below[r] = b_low > truth, b_high < truth
                width["boot"] += b_high - b_low
            count["b_above"] += int(b_above.sum())
            count["b_below"] += int(b_below.sum())
            count["b_undefined"] += int((~exists[:nb]).sum())
            count["p_above"] += int(above[:nb].sum())
            count["p_below"] += int(below[:nb].sum())
            width["p_welch"] += float((high - low)[:nb][exists[:nb]].sum())
            for side, welch_miss, boot_miss in (
                ("above", above[:nb], b_above),
                ("below", below[:nb], b_below),
            ):
                pairs[side][0] += int((welch_miss & boot_miss).sum())
                pairs[side][1] += int((welch_miss & ~boot_miss).sum())
                pairs[side][2] += int((~welch_miss & boot_miss).sum())
        done += size
    defined = reps - count["undefined"]
    error = np.concatenate(keep_error)
    row: dict = {
        **{k: v for k, v in asdict(cell).items() if v is not None},
        "truth": round(truth, 6),
        "reps": reps,
        "boot_reps": boot_reps,
        "seed": seed,
        "welch_above_n": count["above"],
        "welch_below_n": count["below"],
        "welch_undefined_n": count["undefined"],
        "welch_width": _ratio(width["welch"], defined) if defined else None,
        "error": _percentiles(error, ERROR_PERCENTILES),
        "half_width": _percentiles(np.concatenate(keep_se), (50,))[0],
        "shape": {
            who: [
                x
                for what in ("skew", "kurt", "share")
                for x in _percentiles(np.concatenate(shapes[f"{who}_{what}"]), SHAPE_PERCENTILES)
            ]
            for who in ("arm", "control")
        },
        "criteria": tallies,
    }
    if boot_reps:
        usable = boot_reps - count["b_undefined"]
        row["boot"] = {
            "undefined_n": count["b_undefined"],
            "welch_above_n": count["p_above"],
            "welch_below_n": count["p_below"],
            "boot_above_n": count["b_above"],
            "boot_below_n": count["b_below"],
            "above": pairs["above"],
            "below": pairs["below"],
            "welch_width": _ratio(width["p_welch"], usable) if usable else None,
            "boot_width": _ratio(width["boot"], usable) if usable else None,
        }
    return row


def _splits(size: int, ratios: tuple, both: bool) -> list[tuple[int, int]]:
    """(arm, control) players for a smaller arm of `size`: the arm the larger one, and the
    control the larger one when `both`."""
    out: list[tuple[int, int]] = []
    for r in ratios:
        larger = int(round(size * r))
        out.append((larger, size))
        if both and r != 1:
            out.append((size, larger))
    return out


def pooled_grid() -> list[Cell]:
    """The cells of the study, in the order of its blocks."""
    cells = []
    for outcome in OUTCOMES:  # the main block
        for size in SIZES:
            for effect in EFFECTS:
                for arm_n, control_n in _splits(size, RATIOS, both=effect > 0):
                    cells.append(Cell(outcome, arm_n, control_n, effect))
    for outcome in LARGE_OUTCOMES:  # large arms
        for size in LARGE_SIZES:
            ratios = tuple(r for r in LARGE_RATIOS if not (r == 9 and size > 30_000))
            for effect in EFFECTS:
                for arm_n, control_n in _splits(size, ratios, both=effect > 0):
                    cells.append(Cell(outcome, arm_n, control_n, effect))
    for outcome in LADDER_OUTCOMES:  # the effect ladder
        for size in LADDER_SIZES:
            for effect in LADDER_EFFECTS:
                for arm_n, control_n in _splits(size, LADDER_RATIOS, both=True):
                    cells.append(Cell(outcome, arm_n, control_n, effect))
    for outcome in PAYER_OUTCOMES:  # other shares of players who spend
        for share in PAYER_SHARES:
            for size in PAYER_SIZES:
                for effect in EFFECTS:
                    for arm_n, control_n in _splits(size, PAYER_RATIOS, both=effect > 0):
                        cells.append(Cell(outcome, arm_n, control_n, effect, share))
    return cells


def estimated_cost(cell: Cell, reps: int, boot_reps: int) -> float:
    """Roughly the seconds of work, to start the dear cells first."""
    players = cell.arm_n + cell.control_n
    dense = cell.outcome in ("normal", "lognormal")
    work = reps * players * (6e-8 if dense else 1e-7 * cell.share)
    if boot_reps:
        work += boot_reps * RESAMPLES * players * cell.share * 1.1e-8
    return work


def _job(job: tuple[Cell, int, int, int]) -> dict:
    cell, reps, boot_reps, seed = job
    return run_cell(cell, reps, boot_reps, seed)


def study(
    cells: list[Cell],
    reps: int,
    boot_reps: int,
    seed: int,
    workers: int = 1,
    large_reps: int | None = None,
    progress: bool = False,
) -> list[dict]:
    """One row per cell. Every cell has its own streams, so `workers` changes nothing."""
    large_reps = reps if large_reps is None else large_reps
    jobs = []
    for cell in cells:
        n = reps_for(cell, reps, large_reps)
        jobs.append((cell, n, boot_reps_for(cell, boot_reps, n), seed))
    if workers == 1:
        rows = [_job(job) for job in jobs]
        if progress:
            sys.stderr.write(f"pooled: {len(rows)} cells\n")
        return rows
    order = sorted(range(len(jobs)), key=lambda i: -estimated_cost(*jobs[i][:3]))
    found: list[dict | None] = [None] * len(jobs)
    with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as pool:
        futures = {pool.submit(_job, jobs[i]): i for i in order}
        try:
            for finished, future in enumerate(as_completed(futures), 1):
                found[futures[future]] = future.result()
                if progress and (finished % 25 == 0 or finished == len(jobs)):
                    sys.stderr.write(f"pooled: {finished} of {len(jobs)} cells\n")
        except BaseException:
            for future in futures:  # a failure or Ctrl-C should not wait for the whole queue
                future.cancel()
            raise
    return [row for row in found if row is not None]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate the pooled effect of an arm against control for heavy-tailed "
        "outcomes: how often Welch's interval and a percentile bootstrap interval miss the true "
        "difference, and what candidate warnings say when they do."
    )
    parser.add_argument("--reps", type=int, default=20000, help="replications a cell")
    parser.add_argument(
        "--large-reps", type=int, default=2000, help="replications a cell of large arms"
    )
    parser.add_argument(
        "--boot-reps", type=int, default=2000, help="of them, replications that get a bootstrap"
    )
    parser.add_argument("--seed", type=int, default=20261212)
    parser.add_argument("--out", type=Path, help="write the study here instead of to the screen")
    parser.add_argument("--workers", type=int, default=1, help="processes to spread the cells over")
    return parser


def _claim(parser: argparse.ArgumentParser, out: Path | None) -> bool:
    """Make sure `out` can be written, without emptying a file that is there; True if it is new."""
    if out is None:
        return False
    if out.is_dir():
        parser.error(f"cannot write {out}: it is a directory")
    existed = out.exists()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.touch()
    except OSError as error:
        parser.error(f"cannot write {out}: {error}")
    return not existed


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    for name in ("reps", "large_reps", "workers"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if args.boot_reps < 0 or args.boot_reps > min(args.reps, args.large_reps):
        parser.error("--boot-reps must be from 0 to the smaller of --reps and --large-reps")
    if args.seed < 0:
        parser.error("--seed must be at least 0")
    command = ["python", "tests/pooled_simulation.py", "--reps", str(args.reps)]
    command += ["--large-reps", str(args.large_reps), "--boot-reps", str(args.boot_reps)]
    command += ["--seed", str(args.seed)]
    if args.out:
        command += ["--out", str(args.out)]
    header = {
        "what": "the pooled effect of an arm against control: Welch's interval and a percentile "
        "bootstrap interval, and candidate heavy-tail warnings",
        "reps": args.reps,
        "large_reps": args.large_reps,
        "boot_reps": args.boot_reps,
        "resamples": RESAMPLES,
        "alpha": ALPHA,
        "seed": args.seed,
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "command": shlex.join(command),
        "outcomes": f"a share {PAYING} of the players spend (unless a cell says `paying`), a "
        "lognormal amount with log-scale sd "
        + ", ".join(f"{sd} ({name})" for name, sd in SPEND_SD.items())
        + f"; mean {BASE['revenue']} per player ({BASE['revenue'] / PAYING:.2f} per paying player)"
        f" in all; also a normal outcome (mean {BASE['normal']}, sd {SD}) and a lognormal one "
        f"(mean {BASE['lognormal']}, log-scale sd {LOG_SD})",
        "columns": "counts of replications: `welch_above_n` and `welch_below_n` are the intervals "
        "that lie wholly above or below the true difference (`truth`); `error` is the 2.5th, "
        "50th and 97.5th percentile of the estimated less the true difference and `half_width` "
        "the median half-width of Welch's interval; `shape` the 5th, 50th and 95th percentile "
        "of skewness, excess kurtosis and top-1% share of the arm and of control; `criteria` "
        f"for each warning {list(TALLY)}; `boot` where the bootstrap ran: the intervals on its "
        "`boot_reps` replications, and for each side [both miss, only Welch's, only the "
        "bootstrap's]",
    }
    created = _claim(parser, args.out)  # before the hours of computing, not after
    try:
        rows = study(
            pooled_grid(),
            args.reps,
            args.boot_reps,
            args.seed,
            args.workers,
            args.large_reps,
            progress=args.out is not None,
        )
        text = render(header, {"cells": rows})
    except BaseException:
        if created:
            args.out.unlink(missing_ok=True)
        raise
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
