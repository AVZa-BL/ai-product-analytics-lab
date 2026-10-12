"""A simulation of the RES-007 cohort trigger (design section 21.5).

The trigger flags an arm when both scales (absolute and relative) show heterogeneity, a scale
showing it when Cochran's Q or the weighted slope has p below `LEVEL / (arms - 1)`. This module
measures how often that happens when nothing changes across cohorts, and how often when an
effect fades. The statistics are written once, vectorised over replications, and
`tests/test_cohort_simulation.py` checks them against `referee.cohort_effects` on random
datasets, so what is measured is what the rule computes.

The random stream of each chunk of 250 replications is spawned from the seed of its cell, so a
run with more replications shares its first full chunks with a shorter one, and a run is the
same on any machine with the same numpy and scipy. Run a full study with

    python tests/cohort_simulation.py --reps 5000 --out docs/simulations/cohort_trigger_null.json

`--power` runs the fade instead of the null. `--heavy` runs the heavy-tailed outcomes (a revenue
that most players leave at 0): the trigger with equal and with unequal arms, the shift that a
finding would print as the smallest it could have seen and how often a fade of that size is
flagged, and the shape of the outcomes (design section 21.5):

    python tests/cohort_simulation.py --heavy --reps 5000 --printed-reps 3000 \\
        --out docs/simulations/cohort_trigger_heavy.json

`--workers` spreads the cells over processes and changes no number.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import zlib
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from multiprocessing import get_context
from pathlib import Path

import numpy as np
from scipy import stats

from referee.cohort_effects import TRIGGER_LEVEL as LEVEL
from referee.cohorts import raised_floor
from referee.methods import cohort_detectable_shift

BASE = {
    "normal": 10.0,
    "poisson": 3.0,
    "lognormal": 10.0,
    "binary": 0.10,
    "revenue_mild": 3.0,
    "revenue": 3.0,
    "revenue_heavy": 3.0,
}
OUTCOMES = ("normal", "poisson", "lognormal", "binary")  # the outcomes of the first study
# A heavy-tailed outcome: the share PAYING of the players spend something, and what one of them
# spends is lognormal with the log-scale standard deviation given here; everyone else is at 0.
# The mean is 3.0 per player in all three (a paying player spends 23.08 on average). The middle
# and the heavy outcome both bracket the revenue of the committed export, the mild one is
# lighter (`tail_shapes`).
PAYING = 0.13
SPEND_SD = {"revenue_mild": 1.0, "revenue": 1.5, "revenue_heavy": 2.0}
TAILED = tuple(SPEND_SD)
SD = 4.0  # the normal outcome
LOG_SD = 1.0  # the lognormal outcome
DRIFT = 0.3  # the control mean moves by +-30% across the cohorts in the drift scenarios
RELATIVE_EFFECT = 0.2
SCENARIOS = {
    "zero": "no effect, a stable baseline",
    "relative": "a constant relative effect of +20%, a stable baseline",
    "relative_drift": "a constant relative effect of +20%, a baseline that drifts by +-30%",
    "absolute_drift": "a constant absolute effect of +20% of the base, a baseline that drifts",
    "fade": "a relative effect of +40% that fades linearly to 0, a stable baseline",
    "null_se_shift": "a fade of the size `cohort_detectable_shift` gives for the standard error "
    "under no effect, a stable baseline",
    "null_se_location": "the same fade added to every player of the arm, so that its spread stays "
    "that of control",
    "printed_shift": "a fade of the size that the finding printed for a dataset with no effect",
    "printed_location": "the same, added to every player of the arm, so that its spread stays "
    "that of control",
}
NULL_SCENARIOS = ("zero", "relative", "relative_drift", "absolute_drift")


@dataclass(frozen=True)
class Cell:
    outcome: str
    cohorts: int
    n: int  # players in each variant and cohort, and in control's when `control_n` is not given
    arms: int  # arms in all, control included
    scenario: str
    control_n: int | None = None  # players in control's cohorts, when not the variants' number

    @property
    def level(self) -> float:
        return LEVEL / (self.arms - 1)

    @property
    def control_players(self) -> int:
        return self.n if self.control_n is None else self.control_n

    @property
    def ratio(self) -> float:
        """How many times larger the larger of a variant and control is than the smaller."""
        return max(self.n, self.control_players) / min(self.n, self.control_players)

    def seed_sequence(self, seed: int) -> np.random.SeedSequence:
        key = f"{self.outcome}|{self.cohorts}|{self.n}|{self.arms}|{self.scenario}"
        if self.control_n is not None:  # a cell with equal arms and no `control_n` keeps its seed
            key += f"|{self.control_n}"
        return np.random.SeedSequence([seed, zlib.crc32(key.encode())])


def _fade(cohorts: int) -> np.ndarray:
    """A linear fade from 1 in the first cohort to 0 in the last."""
    return 1.0 - np.arange(cohorts) / max(cohorts - 1, 1)


def population_sd(outcome: str) -> float:
    """The standard deviation of one player's value, from the outcome's own formula."""
    if outcome not in BASE:
        raise ValueError(f"unknown outcome {outcome!r}")
    mean = BASE[outcome]
    if outcome == "normal":
        return SD
    if outcome == "poisson":
        return math.sqrt(mean)
    if outcome == "lognormal":
        return mean * math.sqrt(math.exp(LOG_SD**2) - 1)
    if outcome == "binary":
        return math.sqrt(mean * (1 - mean))
    if outcome in SPEND_SD:  # E[X^2] = mean^2 * exp(sd^2) / PAYING, as payers spend mean / PAYING
        return mean * math.sqrt(math.exp(SPEND_SD[outcome] ** 2) / PAYING - 1)
    raise AssertionError(f"no standard deviation written for {outcome!r}")


def null_se_shift(cell: Cell) -> float:
    """The shift that `cohort_detectable_shift` gives from the standard error under no effect.

    The standard error of a cohort's difference of means is worked out from the population's
    standard deviation, the same in every cohort and as it is when nothing changes. It is the
    shift the finding would print if its estimate of the standard error were exact and an effect
    did not change the spread. Neither holds for an outcome whose spread grows with its mean
    (revenue, counts, rates), which is why a fade of this size is flagged less than 80% of the
    time for them; `printed_shifts` is what a finding really prints.
    """
    se = population_sd(cell.outcome) * math.sqrt(1 / cell.n + 1 / cell.control_players)
    return cohort_detectable_shift([se] * cell.cohorts, shape="linear_fade", level=cell.level)


def _require_location(cell: Cell) -> None:
    if cell.outcome not in LOCATION_OUTCOMES:
        raise ValueError(f"a shift cannot be added to every player of a {cell.outcome} outcome")


def means(cell: Cell) -> tuple[np.ndarray, list[np.ndarray]]:
    """The control's mean in each cohort, and each variant's."""
    k = cell.cohorts
    base = BASE[cell.outcome]
    drifting = cell.scenario in ("relative_drift", "absolute_drift")
    position = np.linspace(-1.0, 1.0, k) if k > 1 else np.zeros(1)
    control = base * (1.0 + DRIFT * position) if drifting else np.full(k, base)
    if cell.scenario == "zero":
        arm = control.copy()
    elif cell.scenario in ("relative", "relative_drift"):
        arm = control * (1.0 + RELATIVE_EFFECT)
    elif cell.scenario == "absolute_drift":
        arm = control + RELATIVE_EFFECT * base
    elif cell.scenario == "fade":
        arm = control * (1.0 + 0.4 * (1.0 - np.arange(k) / max(k - 1, 1)))
    elif cell.scenario == "null_se_shift":
        arm = control + null_se_shift(cell) * (1.0 - np.arange(k) / max(k - 1, 1))
    elif cell.scenario == "null_se_location":
        _require_location(cell)
        arm = control.copy()  # the fade is added to the players, see `cell_flags`
    else:
        raise ValueError(f"unknown scenario {cell.scenario!r}")
    return control, [arm.copy() for _ in range(cell.arms - 1)]


def draw(outcome: str, mean: np.ndarray, n: int, rng: np.random.Generator, reps: int):
    """`reps` x cohorts x n values with the given mean in each cohort.

    `mean` has one value for each cohort, or one for each replication and cohort.
    """
    shape = (reps, mean.shape[-1], n)
    centre = mean[..., None]
    if outcome == "binary" and (centre > 1).any():
        raise ValueError("a binary outcome cannot have a rate above 1")
    if outcome == "normal":
        return centre + SD * rng.standard_normal(shape)
    if outcome == "poisson":
        return rng.poisson(np.broadcast_to(centre, shape)).astype(float)
    if outcome == "lognormal":
        mu = np.log(centre) - LOG_SD**2 / 2
        return np.exp(mu + LOG_SD * rng.standard_normal(shape))
    if outcome == "binary":
        return (rng.random(shape) < centre).astype(float)
    if outcome in SPEND_SD:
        sd = SPEND_SD[outcome]
        mu = np.log(centre / PAYING) - sd**2 / 2  # a payer spends centre / PAYING on average
        pays = rng.random(shape) < PAYING
        return np.where(pays, np.exp(mu + sd * rng.standard_normal(shape)), 0.0)
    raise ValueError(f"unknown outcome {outcome!r}")


def _heterogeneity(d: np.ndarray, se: np.ndarray, valid: np.ndarray):
    """Q's p value and the slope's, per replication; NaN where fewer than 3 cohorts are valid."""
    reps, k = d.shape
    count = valid.sum(axis=1)
    weight = np.where(valid, 1.0 / np.where(valid, se, 1.0) ** 2, 0.0)
    d = np.where(valid, d, 0.0)
    total = weight.sum(axis=1)
    safe = np.where(total > 0, total, 1.0)
    pooled = (weight * d).sum(axis=1) / safe
    q = (weight * (d - pooled[:, None]) ** 2).sum(axis=1)
    x = np.arange(k, dtype=float)[None, :]
    x_bar = (weight * x).sum(axis=1) / safe
    spread = (weight * (x - x_bar[:, None]) ** 2).sum(axis=1)
    safe_spread = np.where(spread > 0, spread, 1.0)
    slope = (weight * (x - x_bar[:, None]) * d).sum(axis=1) / safe_spread
    z = slope * np.sqrt(spread)
    ok = count >= 3
    p_q = np.where(ok, stats.chi2.sf(q, np.maximum(count - 1, 1)), np.nan)
    p_s = np.where(ok, 2 * stats.norm.sf(np.abs(z)), np.nan)
    return p_q, p_s


def _scales(arm: np.ndarray, control: np.ndarray) -> dict[str, tuple[np.ndarray, ...]]:
    """For each scale, the estimate of every cohort, its corrected standard error and whether
    the cohort gives an estimate on that scale, for `reps` replications of one arm against control.

    `arm` and `control` are reps x cohorts x players, and the players of the two may differ in
    number. A cohort that gives no estimate on a scale (no variation, a mean that is not above
    0, degrees of freedom of 2 or less) is left out of that scale, as `referee.cohort_effects`
    leaves it out; the estimate of a cohort that is left out is 0.
    """
    n_arm, n_control = arm.shape[-1], control.shape[-1]
    mean_t, mean_c = arm.mean(axis=-1), control.mean(axis=-1)
    var_t, var_c = arm.var(axis=-1, ddof=1), control.var(axis=-1, ddof=1)

    def scale(estimate, part_t, part_c, extra_valid):
        total = part_t + part_c
        valid = extra_valid & (total > 0)
        safe = np.where(valid, total, 1.0)
        share_t, share_c = part_t / safe, part_c / safe
        with np.errstate(divide="ignore"):  # a cohort with no variation is not valid anyway
            dof = 1.0 / (share_t**2 / (n_arm - 1) + share_c**2 / (n_control - 1))
        valid &= dof > 2
        corrected = np.sqrt(safe) * np.sqrt(
            np.where(valid, dof, 3.0) / (np.where(valid, dof, 3.0) - 2)
        )
        return np.where(valid, estimate, 0.0), corrected, valid

    positive = (mean_t > 0) & (mean_c > 0)
    safe_t, safe_c = np.where(positive, mean_t, 1.0), np.where(positive, mean_c, 1.0)
    return {
        "absolute": scale(
            mean_t - mean_c, var_t / n_arm, var_c / n_control, np.ones_like(mean_t, bool)
        ),
        "log_ratio": scale(
            np.log(safe_t / safe_c),
            var_t / (n_arm * safe_t**2),
            var_c / (n_control * safe_c**2),
            positive,
        ),
    }


def p_values(arm: np.ndarray, control: np.ndarray) -> dict[str, np.ndarray]:
    """The four p values of the trigger for `reps` replications of one arm against control.

    A scale with fewer than 3 cohorts left has NaN p values. See `_scales` for which cohorts are
    left out.
    """
    found = _scales(arm, control)
    out: dict[str, np.ndarray] = {}
    out["q_abs"], out["s_abs"] = _heterogeneity(*found["absolute"])
    out["q_log"], out["s_log"] = _heterogeneity(*found["log_ratio"])
    return out


def printed_shifts(arm: np.ndarray, control: np.ndarray, level: float) -> np.ndarray:
    """The shift a finding prints as the smallest linear fade it could have seen, per replication.

    It is `referee.cohort_effects.detectable_shifts` for the absolute scale: the shift that
    Q-or-slope at `level` flags with 80% probability, worked out from the corrected standard
    errors of the cohorts that give an estimate and their block numbers. NaN where the finding
    prints none: where fewer than 3 cohorts give an estimate on the absolute scale or on the
    log-ratio scale, since it then reports the test as not evaluated (`referee.rules.cohorts`).
    """
    found = _scales(arm, control)
    _, corrected, valid = found["absolute"]
    evaluated = found["log_ratio"][2].sum(axis=1) >= 3
    shifts = np.full(valid.shape[0], np.nan)
    for r in range(valid.shape[0]):
        if valid[r].sum() >= 3 and evaluated[r]:
            shifts[r] = cohort_detectable_shift(
                corrected[r][valid[r]].tolist(),
                positions=np.flatnonzero(valid[r]).tolist(),
                shape="linear_fade",
                level=level,
            )
    return shifts


def flags(p: dict[str, np.ndarray], level: float) -> dict[str, np.ndarray]:
    """Which replications each rule of thumb flags, at `level` per statistic."""
    with np.errstate(invalid="ignore"):
        q_abs, s_abs = p["q_abs"] < level, p["s_abs"] < level
        q_log, s_log = p["q_log"] < level, p["s_log"] < level
    absolute, relative = q_abs | s_abs, q_log | s_log
    return {
        "q_abs": q_abs,
        "s_abs": s_abs,
        "q_log": q_log,
        "s_log": s_log,
        "absolute": absolute,
        "relative": relative,
        "both": absolute & relative,
        "q_both": q_abs & q_log,
    }


def cell_flags(cell: Cell, reps: int, seed: int, chunk: int = 250) -> dict[str, np.ndarray]:
    """For each rule of thumb, a reps x (arms - 1) array of which replications flag which arm.

    The random stream of a chunk is spawned from the seed of the cell, so the first full chunk
    of any run is the same whatever the number of replications.
    """
    control_mean, arm_means = means(cell)
    streams = cell.seed_sequence(seed).spawn((reps + chunk - 1) // chunk)
    parts: dict[str, list[np.ndarray]] = {}
    done = 0
    for stream in streams:
        size = min(chunk, reps - done)
        rng = np.random.default_rng(stream)
        control = draw(cell.outcome, control_mean, cell.control_players, rng, size)
        found: list[dict[str, np.ndarray]] = []
        for arm_mean in arm_means:
            arm = draw(cell.outcome, arm_mean, cell.n, rng, size)
            if cell.scenario == "null_se_location":
                arm = arm + _fade(cell.cohorts)[None, :, None] * null_se_shift(cell)
            found.append(flags(p_values(arm, control), cell.level))
        for name in found[0]:
            parts.setdefault(name, []).append(np.stack([f[name] for f in found], axis=1))
        done += size
    return {name: np.concatenate(chunks, axis=0) for name, chunks in parts.items()}


def run_cell(cell: Cell, reps: int, seed: int, chunk: int = 250) -> dict[str, float]:
    """The share of replications each rule flags, per arm, and for any arm."""
    found = cell_flags(cell, reps, seed, chunk)
    result = {name: float(hit.mean()) for name, hit in found.items()}
    result["any_arm_both"] = float(found["both"].any(axis=1).mean())
    return result


def grid(
    outcomes: Iterable[str] = OUTCOMES,
    cohorts: Iterable[int] = (3, 4, 8, 12),
    sizes: Iterable[int] = (30, 100, 300),
    arms: Iterable[int] = (2, 3),
    scenarios: Iterable[str] = NULL_SCENARIOS,
) -> list[Cell]:
    return [
        Cell(o, k, n, a, s)
        for o in outcomes
        for k in cohorts
        for n in sizes
        for a in arms
        for s in scenarios
    ]


EQUAL_PLAYERS = (30, 100, 300, 1000)
HEAVY_COHORTS = (4, 8, 12)
SPLITS = (2, 3, 4, 9)  # the larger arm over the smaller, up to the 9 to 1 that the rule allows
FLOOR_MULTIPLES = (1, 3)  # the smaller arm of an unequal split, in times the floor raised for it
SHAPE_SIZES = (300, 900, 3000)
SHIFT_OUTCOMES = (*OUTCOMES, *TAILED)
LOCATION_OUTCOMES = ("normal", "lognormal", *TAILED)  # where a shift can be added to every player
REPLICATION = ("revenue", 8, 258, 2322, "relative", 30000, 777)  # the worst 8-cohort cell, again
SHIFT_COHORTS = (4, 8)
SHIFT_PLAYERS = (100, 300, 1000)


def heavy_grid() -> list[Cell]:
    """The cells of the heavy-tailed study (the trigger's flag rates), 540 in all.

    Equal arms, for the three tailed outcomes: four sizes with the null scenarios and the fade.
    Unequal arms, with the variant the larger and with it the smaller: the smaller arm has once
    and three times the floor that the rule raises for that split (`referee.cohorts.raised_floor`)
    and the larger has the split times that; no effect and +20% only. And for all seven outcomes,
    the fade of the size that `cohort_detectable_shift` gives from the standard error under no
    effect (`null_se_shift`), with the normal outcome, whose spread does not grow with its mean,
    as the reference, and the same fade added to every player of the arm for the five outcomes
    where that is possible (`null_se_location`), so that the arm keeps the spread of control.
    """
    cells = []
    for outcome in TAILED:
        for cohorts in HEAVY_COHORTS:
            for n in EQUAL_PLAYERS:
                for scenario in (*NULL_SCENARIOS, "fade"):
                    cells.append(Cell(outcome, cohorts, n, 2, scenario, control_n=n))
            for split in SPLITS:
                for multiple in FLOOR_MULTIPLES:
                    small = multiple * raised_floor(split)
                    for n, control_n in ((split * small, small), (small, split * small)):
                        for scenario in ("zero", "relative"):
                            cells.append(
                                Cell(outcome, cohorts, n, 2, scenario, control_n=control_n)
                            )
    for scenario, outcomes in (
        ("null_se_shift", SHIFT_OUTCOMES),
        ("null_se_location", LOCATION_OUTCOMES),
    ):
        for outcome in outcomes:
            for cohorts in SHIFT_COHORTS:
                for n in SHIFT_PLAYERS:
                    cells.append(Cell(outcome, cohorts, n, 2, scenario, control_n=n))
    return cells


def printed_grid() -> list[Cell]:
    """The cells of the study of the shift a finding prints: all seven outcomes with the effect
    scaling the arm's mean, and the five where a shift can be added to every player with it
    added to them; equal arms."""
    return [
        Cell(outcome, cohorts, n, 2, scenario, control_n=n)
        for scenario, outcomes in (
            ("printed_shift", SHIFT_OUTCOMES),
            ("printed_location", LOCATION_OUTCOMES),
        )
        for outcome in outcomes
        for cohorts in SHIFT_COHORTS
        for n in SHIFT_PLAYERS
    ]


def _printed_chunk(cell: Cell, size: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """`size` replications: the printed shift, whether it is low information, and whether a fade
    of exactly that size is flagged (absolute scale alone, and the trigger with both scales)."""
    base = np.full(cell.cohorts, BASE[cell.outcome])
    fade = _fade(cell.cohorts)
    control = draw(cell.outcome, base, cell.n, rng, size)
    quiet = draw(cell.outcome, base, cell.n, rng, size)
    shift = printed_shifts(quiet, control, cell.level)
    printed = ~np.isnan(shift)
    seen = np.where(printed, shift, 0.0)[:, None] * fade  # the fade of each replication
    if cell.scenario == "printed_location":
        arm = draw(cell.outcome, base, cell.n, rng, size) + seen[:, :, None]
    else:
        arm = draw(cell.outcome, BASE[cell.outcome] + seen, cell.n, rng, size)
    found = flags(p_values(arm, draw(cell.outcome, base, cell.n, rng, size)), cell.level)
    return {
        "shift": shift,
        "control_mean": control.mean(axis=(1, 2)),
        "low_information": printed & (shift > control.mean(axis=(1, 2))),
        "absolute": found["absolute"],
        "both": found["both"],
    }


def run_printed(cell: Cell, reps: int, seed: int, chunk: int = 250) -> dict[str, float | None]:
    """What a finding prints as the smallest fade it could have seen, and how often it is right.

    For each replication a dataset with no effect gives the shift the finding would print
    (`printed_shifts`, from its observed standard errors) and whether it would call the result
    low information because that shift exceeds the observed mean of control
    (`referee.cohort_effects.low_information`; the other labels depend on a registered minimum
    detectable effect or on a binary metric's events and are not simulated). A fresh dataset with
    a fade of exactly that size then says whether the test flags it. The finding claims 80%.

    The figures are shares of the replications that print a shift: `ratio_p5`, `ratio_p50` and
    `ratio_p95` of the printed shift to the shift from the true standard error (`true_shift`),
    `low_information`, the share of flagged fades on the absolute scale (`absolute`) and for the
    trigger with both scales (`both`), and the same two among the replications whose result is not
    called low information; `runs` and `not_low_information_runs` count the replications behind
    them. None where there are no such replications. In the scenario `printed_location` the
    fade is added to every player of the arm instead of scaling its mean, so that the arm keeps
    the spread of control.
    """
    if cell.arms != 2 or cell.control_players != cell.n:
        raise ValueError("the shift a finding prints is simulated for two arms of equal size")
    if cell.scenario not in ("printed_shift", "printed_location"):
        raise ValueError(f"not a scenario of the shift a finding prints: {cell.scenario!r}")
    if cell.scenario == "printed_location":
        _require_location(cell)
    streams = cell.seed_sequence(seed).spawn((reps + chunk - 1) // chunk)
    parts: dict[str, list[np.ndarray]] = {}
    done = 0
    for stream in streams:
        size = min(chunk, reps - done)
        for name, values in _printed_chunk(cell, size, np.random.default_rng(stream)).items():
            parts.setdefault(name, []).append(values)
        done += size
    shift, low, absolute, both = (
        np.concatenate(parts[name]) for name in ("shift", "low_information", "absolute", "both")
    )
    printed = ~np.isnan(shift)
    kept = printed & ~low
    true_shift = null_se_shift(cell)
    ratio = shift[printed] / true_shift
    share = lambda hit, among: float(hit[among].mean()) if among.any() else None  # noqa: E731
    percentile = lambda q: round(float(np.percentile(ratio, q)), 4) if printed.any() else None  # noqa: E731
    return {
        "printed": float(printed.mean()),
        "runs": int(printed.sum()),
        "not_low_information_runs": int(kept.sum()),
        "true_shift": round(true_shift, 4),
        "ratio_p5": percentile(5),
        "ratio_p50": percentile(50),
        "ratio_p95": percentile(95),
        "low_information": share(low, printed),
        "absolute": share(absolute, printed),
        "both": share(both, printed),
        "absolute_not_low_information": share(absolute, kept),
        "both_not_low_information": share(both, kept),
    }


def _row(job: tuple[Cell, int, int]) -> dict:
    cell, reps, seed = job
    fields = {k: v for k, v in asdict(cell).items() if v is not None}
    if cell.scenario in ("printed_shift", "printed_location"):
        return {**fields, "reps": reps, "seed": seed, **run_printed(cell, reps, seed)}
    if cell.scenario in ("null_se_shift", "null_se_location"):
        shift = null_se_shift(cell)
        fields["shift"] = round(shift, 4)
        fields["shift_share_of_mean"] = round(shift / BASE[cell.outcome], 4)
    return {**fields, "reps": reps, "seed": seed, **run_cell(cell, reps, seed)}


def study(cells: list[Cell], reps: int, seed: int, workers: int = 1) -> list[dict]:
    """One row per cell. Every cell has its own streams, so `workers` changes nothing."""
    jobs = [(cell, reps, seed) for cell in cells]
    if workers == 1:
        return [_row(job) for job in jobs]
    with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as pool:  # not fork:
        return list(pool.map(_row, jobs, chunksize=1))  # numpy has threads by now


def shape_sample(outcome: str, n: int, samples: int, seed: int) -> np.ndarray:
    """`samples` arms of n players each, as a samples x n array."""
    key = f"shape|{outcome}|{n}"
    rng = np.random.default_rng(np.random.SeedSequence([seed, zlib.crc32(key.encode())]))
    return draw(outcome, np.array([BASE[outcome]]), n, rng, samples)[:, 0, :]


def tail_shapes(
    outcomes: Iterable[str] = TAILED,
    sizes: Iterable[int] = SHAPE_SIZES,
    samples: int = 4000,
    seed: int = 20261211,
) -> list[dict]:
    """What one arm of n players of each tailed outcome looks like to a reader of the export.

    The skewness, the excess kurtosis, the share of the total held by the top 1% of players and
    the standard deviation as a share of the population's, each over `samples` arms: the 5th,
    50th and 95th percentile. A sample of a few hundred players shows far less of a tail than the
    population has, so these, and not the population's moments, are what to compare with an
    export; the last says how much of the spread a sample usually misses.
    """
    rows = []
    for outcome in outcomes:
        for n in sizes:
            values = shape_sample(outcome, n, samples, seed)
            top = np.sort(values, axis=1)[:, ::-1][:, : (n + 99) // 100].sum(axis=1)
            measures = {
                "skewness": stats.skew(values, axis=1),
                "excess_kurtosis": stats.kurtosis(values, axis=1),
                "top_1_percent_share": top / values.sum(axis=1),
                "sd_ratio": values.std(axis=1, ddof=1) / population_sd(outcome),
            }
            row: dict = {"outcome": outcome, "n": n, "samples": samples}
            for name, found in measures.items():
                for percentile in (5, 50, 95):
                    row[f"{name}_p{percentile}"] = round(float(np.percentile(found, percentile)), 4)
            rows.append(row)
    return rows


def render(header: dict, tables: dict[str, list[dict]]) -> str:
    """A study as JSON: a header that says how it was made, then one line per row of each table."""
    body = ",\n".join(
        f' "{name}": [\n'
        + ",\n".join("  " + json.dumps(row, separators=(", ", ": ")) for row in rows)
        + "\n ]"
        for name, rows in tables.items()
    )
    return json.dumps(header, indent=1)[:-2] + ",\n" + body + "\n}\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate the RES-007 cohort trigger: false alarms (the default), power "
        "(--power), or heavy-tailed outcomes (--heavy)."
    )
    parser.add_argument("--reps", type=int, default=4000, help="replications a cell")
    parser.add_argument(
        "--printed-reps",
        type=int,
        default=3000,
        help="replications a cell for the shift a finding prints (--heavy only)",
    )
    parser.add_argument("--seed", type=int, default=20261211)
    parser.add_argument("--out", type=Path, help="write the study here instead of to the screen")
    parser.add_argument("--part", type=int, default=0, help="which share of the grid, from 0")
    parser.add_argument("--parts", type=int, default=1, help="into how many shares to split it")
    parser.add_argument("--workers", type=int, default=1, help="processes to spread the cells over")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--power", action="store_true", help="the fade instead of the null")
    kind.add_argument("--heavy", action="store_true", help="the heavy-tailed outcomes")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    for name in ("reps", "printed_reps", "workers", "parts"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if not 0 <= args.part < args.parts:
        parser.error("--part must be from 0 to one less than --parts")
    if args.seed < 0:
        parser.error("--seed must be at least 0")
    if args.heavy and args.parts > 1:
        parser.error("--heavy is not split into parts")
    if args.heavy:
        cells, flag = heavy_grid(), "--heavy"
        what = "heavy-tailed outcomes (false alarms, power, and the shift a finding prints)"
    elif args.power:
        cells, what, flag = grid(scenarios=("fade",)), "fade (power)", "--power"
    else:
        cells, what, flag = grid(scenarios=NULL_SCENARIOS), "null (false alarms)", ""
    cells = cells[args.part :: args.parts]
    if not cells:
        parser.error("--part selects no cell")
    command = ["python tests/cohort_simulation.py", flag, f"--reps {args.reps}"]
    if args.heavy:
        command.append(f"--printed-reps {args.printed_reps}")
    command.append(f"--seed {args.seed}")
    if args.parts > 1:
        command.append(f"--part {args.part} --parts {args.parts}")
    if args.out:
        command.append(f"--out {args.out}")
    header = {
        "what": what,
        "trigger": "both scales show heterogeneity "
        f"(Q or slope, p below {LEVEL} / non-control arms)",
        "reps": args.reps,
        "seed": args.seed,
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "command": " ".join(part for part in command if part),
    }
    if args.parts > 1:
        header["part"], header["parts"] = args.part, args.parts
    created = _claim(parser, args.out)  # before the hours of computing, not after
    try:
        text = _study_text(args, header, cells)
    except BaseException:
        if created:
            args.out.unlink(missing_ok=True)
        raise
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


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


def _study_text(args: argparse.Namespace, header: dict, cells: list[Cell]) -> str:
    tables = {"cells": study(cells, args.reps, args.seed, args.workers)}
    if args.heavy:
        header["printed_reps"] = args.printed_reps
        header["outcomes"] = (
            f"a share {PAYING} of the players spend, a lognormal amount with log-scale sd "
            + ", ".join(f"{sd} ({name})" for name, sd in SPEND_SD.items())
            + f"; mean {BASE['revenue']} per player ({BASE['revenue'] / PAYING:.2f} per paying "
            "player) in all"
        )
        outcome, cohorts, n, control_n, scenario, reps, seed = REPLICATION
        again = Cell(outcome, cohorts, n, 2, scenario, control_n=control_n)
        tables = {
            "shapes": tail_shapes(seed=args.seed),
            **tables,
            "printed": study(printed_grid(), args.printed_reps, args.seed, args.workers),
            "replication": study([again], reps, seed),
        }
    return render(header, tables)


if __name__ == "__main__":
    main()
