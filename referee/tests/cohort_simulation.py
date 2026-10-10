"""A simulation of the RES-007 cohort trigger under the null (design section 21.5).

The trigger flags an arm when both scales (absolute and relative) show heterogeneity, a scale
showing it when Cochran's Q or the weighted slope has p below `LEVEL / arms`. This module
measures how often that happens when nothing changes across cohorts, and how often when an
effect fades. The statistics are written once, vectorised over replications, and
`tests/test_cohort_simulation.py` checks them against `referee.cohort_effects` on random
datasets, so what is measured is what the rule computes.

Every replication has its own random stream, spawned from the seed of its cell, so the first n
replications of a cell are the same whatever the total, and a run is the same on any machine
with the same numpy. Run a full study with

    python tests/cohort_simulation.py --reps 4000 --out docs/simulations/cohort_trigger.json
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import stats

from referee.cohort_effects import TRIGGER_LEVEL as LEVEL

BASE = {"normal": 10.0, "poisson": 3.0, "lognormal": 10.0, "binary": 0.10}
SD = 4.0  # the normal outcome
LOG_SD = 1.0  # the lognormal outcome
DRIFT = 0.3  # the control mean moves by +-30% across the cohorts in the drift scenarios
RELATIVE_EFFECT = 0.2
OUTCOMES = tuple(BASE)
SCENARIOS = {
    "zero": "no effect, a stable baseline",
    "relative": "a constant relative effect of +20%, a stable baseline",
    "relative_drift": "a constant relative effect of +20%, a baseline that drifts by +-30%",
    "absolute_drift": "a constant absolute effect of +20% of the base, a baseline that drifts",
    "fade": "a relative effect of +40% that fades linearly to 0, a stable baseline",
}
NULL_SCENARIOS = ("zero", "relative", "relative_drift", "absolute_drift")


@dataclass(frozen=True)
class Cell:
    outcome: str
    cohorts: int
    n: int
    arms: int  # arms in all, control included
    scenario: str

    @property
    def level(self) -> float:
        return LEVEL / (self.arms - 1)

    def seed_sequence(self, seed: int) -> np.random.SeedSequence:
        key = f"{self.outcome}|{self.cohorts}|{self.n}|{self.arms}|{self.scenario}"
        return np.random.SeedSequence([seed, zlib.crc32(key.encode())])


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
    else:
        raise ValueError(f"unknown scenario {cell.scenario!r}")
    return control, [arm.copy() for _ in range(cell.arms - 1)]


def draw(outcome: str, mean: np.ndarray, n: int, rng: np.random.Generator, reps: int):
    """`reps` x cohorts x n values with the given mean in each cohort."""
    shape = (reps, mean.shape[0], n)
    centre = mean[None, :, None]
    if outcome == "normal":
        return centre + SD * rng.standard_normal(shape)
    if outcome == "poisson":
        return rng.poisson(np.broadcast_to(centre, shape)).astype(float)
    if outcome == "lognormal":
        mu = np.log(centre) - LOG_SD**2 / 2
        return np.exp(mu + LOG_SD * rng.standard_normal(shape))
    if outcome == "binary":
        return (rng.random(shape) < centre).astype(float)
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


def p_values(arm: np.ndarray, control: np.ndarray) -> dict[str, np.ndarray]:
    """The four p values of the trigger for `reps` replications of one arm against control.

    `arm` and `control` are reps x cohorts x n. A cohort that gives no estimate on a scale
    (no variation, a mean that is not above 0, degrees of freedom of 2 or less) is left out
    of that scale, as `referee.cohort_effects` leaves it out, and a scale with fewer than 3
    cohorts left has NaN p values.
    """
    n = arm.shape[-1]
    mean_t, mean_c = arm.mean(axis=-1), control.mean(axis=-1)
    var_t, var_c = arm.var(axis=-1, ddof=1), control.var(axis=-1, ddof=1)

    def scale(estimate, part_t, part_c, extra_valid):
        total = part_t + part_c
        valid = extra_valid & (total > 0)
        safe = np.where(valid, total, 1.0)
        share_t, share_c = part_t / safe, part_c / safe
        with np.errstate(divide="ignore"):  # a cohort with no variation is not valid anyway
            dof = 1.0 / (share_t**2 / (n - 1) + share_c**2 / (n - 1))
        valid &= dof > 2
        corrected = np.sqrt(safe) * np.sqrt(
            np.where(valid, dof, 3.0) / (np.where(valid, dof, 3.0) - 2)
        )
        return _heterogeneity(np.where(valid, estimate, 0.0), corrected, valid)

    out: dict[str, np.ndarray] = {}
    out["q_abs"], out["s_abs"] = scale(
        mean_t - mean_c, var_t / n, var_c / n, np.ones_like(mean_t, bool)
    )
    positive = (mean_t > 0) & (mean_c > 0)
    safe_t, safe_c = np.where(positive, mean_t, 1.0), np.where(positive, mean_c, 1.0)
    out["q_log"], out["s_log"] = scale(
        np.log(safe_t / safe_c), var_t / (n * safe_t**2), var_c / (n * safe_c**2), positive
    )
    return out


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

    The random stream of a chunk is spawned from the seed of the cell, so the first chunk of
    any run is the same whatever the number of replications.
    """
    control_mean, arm_means = means(cell)
    streams = cell.seed_sequence(seed).spawn((reps + chunk - 1) // chunk)
    parts: dict[str, list[np.ndarray]] = {}
    done = 0
    for stream in streams:
        size = min(chunk, reps - done)
        rng = np.random.default_rng(stream)
        control = draw(cell.outcome, control_mean, cell.n, rng, size)
        found: list[dict[str, np.ndarray]] = []
        for arm_mean in arm_means:
            arm = draw(cell.outcome, arm_mean, cell.n, rng, size)
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


def study(cells: list[Cell], reps: int, seed: int) -> list[dict]:
    rows = []
    for cell in cells:
        rows.append({**asdict(cell), "reps": reps, "seed": seed, **run_cell(cell, reps, seed)})
    return rows


def render(rows: list[dict], reps: int, seed: int, *, power: bool) -> str:
    """The study as JSON: a header that says how it was made, then one line per cell."""
    header = {
        "what": "fade (power)" if power else "null (false alarms)",
        "trigger": "both scales show heterogeneity (Q or slope, p below 0.025 / non-control arms)",
        "reps": reps,
        "seed": seed,
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "command": "python tests/cohort_simulation.py" + (" --power" if power else ""),
    }
    lines = ",\n".join("  " + json.dumps(row, separators=(", ", ": ")) for row in rows)
    return json.dumps(header, indent=1)[:-2] + ',\n "cells": [\n' + lines + "\n ]\n}\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reps", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261211)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--part", type=int, default=0, help="which share of the grid, from 0")
    parser.add_argument("--parts", type=int, default=1, help="into how many shares to split it")
    parser.add_argument(
        "--power", action="store_true", help="the fade scenario instead of the null"
    )
    args = parser.parse_args(argv)
    cells = grid(scenarios=("fade",) if args.power else NULL_SCENARIOS)
    cells = cells[args.part :: args.parts]
    rows = study(cells, args.reps, args.seed)
    text = render(rows, args.reps, args.seed, power=args.power)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
