"""A simulation of the covariate adjustment (CUPED) that Referee applies (design section 29).

It measures, for `referee.methods.cuped_difference` and Welch's interval, with the true
difference known:

- `variance`: the variance of the adjusted estimate over the variance of the unadjusted one when
  the outcome and the covariate are normal with correlation rho (theory: 1 - rho^2, with a factor
  of about (n - 2) / (n - 3) from estimating the slope), and how often each 95% interval holds the
  true difference;
- `leaking`: the same when the covariate is moved by the treatment, so it is not a pre-period
  measure, by a shift of `shift` standard deviations of the covariate: the bias of the adjusted
  estimate, how often its interval holds the truth, and how often Referee's balance check flags
  the covariate;
- `heavy`: revenue-like outcomes of the lab's own model (a Poisson number of purchases with
  lognormal amounts, from a lognormal engagement), where the pre-period revenue predicts almost
  nothing, and a variant where a player's spending scale persists, so that it predicts some:
  the coverage of the adjusted interval against Welch's.

Every cell draws from its own seed, so a run with more replications shares nothing it need not.

    python tests/cuped_simulation.py --reps 4000 --out docs/simulations/cuped.json

(about two minutes).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from referee.methods import StatsError, cuped_difference, welch_difference

SEED = 20261030
RHOS = (0.0, 0.3, 0.7)
SIZES = (50, 200, 1000)  # players an arm
SHIFTS = (0.0, 0.1, 0.25, 0.5)
HEAVY_SIZES = (200, 940)
EFFECT = 0.5  # the true difference, in standard deviations of the outcome (normal cells)
BALANCE_ALPHA = 0.001 / 2  # three arms: two comparisons against control


def _normal_pair(
    rng: np.random.Generator, rho: float, n: int, shift: float = 0.0, effect: float = 0.0
):
    """Covariate x and outcome y for two arms of n players, unit variances, correlation rho before
    the treatment; the treatment adds `effect` to y and `shift` to x."""
    common = rng.standard_normal((2, n))
    x = common
    y = rho * common + np.sqrt(1 - rho**2) * rng.standard_normal((2, n))
    x[1] = x[1] + shift
    y[1] = y[1] + effect
    return y[1], x[1], y[0], x[0]


def _row(estimates: list[float], intervals: list[tuple[float, float]], truth: float) -> dict:
    est = np.asarray(estimates)
    low = np.asarray([i[0] for i in intervals])
    high = np.asarray([i[1] for i in intervals])
    return {
        "mean": float(est.mean()),
        "variance": float(est.var(ddof=1)),
        "coverage": float(np.mean((low <= truth) & (truth <= high))),
    }


def _cell(sample, reps: int, truth: float, seed: int) -> dict:
    """Adjusted and unadjusted estimates over `reps` samples drawn by `sample(rng)`."""
    rng = np.random.default_rng(seed)
    adjusted, plain, flagged, failed = [], [], 0, 0
    for _ in range(reps):
        y1, x1, y0, x0 = sample(rng)
        try:
            a = cuped_difference(y1, x1, y0, x0)
            w = welch_difference(y1, y0)
        except StatsError:
            failed += 1
            continue
        adjusted.append((a.difference, (a.ci_low, a.ci_high)))
        plain.append((w.difference, (w.ci_low, w.ci_high)))
        flagged += a.balance_p_value < BALANCE_ALPHA
    done = len(adjusted)
    out = {
        "reps": done,
        "failed": failed,
        "adjusted": _row([a[0] for a in adjusted], [a[1] for a in adjusted], truth),
        "unadjusted": _row([p[0] for p in plain], [p[1] for p in plain], truth),
        "balance_flag_rate": flagged / done,
    }
    out["variance_ratio"] = out["adjusted"]["variance"] / out["unadjusted"]["variance"]
    return out


def study_variance(reps: int) -> list[dict]:
    rows = []
    for i, (rho, n) in enumerate((r, n) for r in RHOS for n in SIZES):
        cell = _cell(
            lambda rng, rho=rho, n=n: _normal_pair(rng, rho, n, effect=EFFECT),
            reps,
            EFFECT,
            SEED + i,
        )
        rows.append({"rho": rho, "n": n, "theory": 1 - rho**2, **cell})
    return rows


def study_leaking(reps: int) -> list[dict]:
    rows = []
    for i, shift in enumerate(SHIFTS):
        cell = _cell(
            lambda rng, shift=shift: _normal_pair(rng, 0.7, 1000, shift=shift, effect=EFFECT),
            reps,
            EFFECT,
            SEED + 100 + i,
        )
        # theory: the adjusted estimate is centred on effect - rho * shift (unit variances)
        rows.append({"rho": 0.7, "n": 1000, "shift": shift, "theory_bias": -0.7 * shift, **cell})
    return rows


def _lab_revenue(rng: np.random.Generator, n: int, persistent: float):
    """Revenue in two periods for two arms of n players, from the lab's model: a lognormal
    engagement scales a Poisson number of purchases, and each purchase is a lognormal amount.
    With `persistent` above 0 a player's amount scale persists across the periods."""
    engagement = rng.lognormal(0.0, 0.5, (2, n))
    scale = np.exp(persistent * rng.standard_normal((2, n)))

    def revenue() -> np.ndarray:
        counts = rng.poisson(0.2 * engagement)
        out = np.zeros((2, n))
        for arm in range(2):
            for j in np.flatnonzero(counts[arm]):
                amounts = rng.lognormal(np.log(2.5), 1.7, counts[arm][j])
                out[arm, j] = np.maximum(0.99, amounts * scale[arm, j]).sum()
        return out

    pre, post = revenue(), revenue()
    return post[1], pre[1], post[0], pre[0]


def study_heavy(reps: int) -> list[dict]:
    rows = []
    cells = [(n, p) for n in HEAVY_SIZES for p in (0.0, 1.5)]
    for i, (n, persistent) in enumerate(cells):
        cell = _cell(
            lambda rng, n=n, p=persistent: _lab_revenue(rng, n, p), reps, 0.0, SEED + 200 + i
        )
        rows.append({"n": n, "persistent_scale_sigma": persistent, **cell})
    return rows


def run(reps: int, heavy_reps: int) -> dict:
    return {
        "seed": SEED,
        "reps": reps,
        "heavy_reps": heavy_reps,
        "variance": study_variance(reps),
        "leaking": study_leaking(reps),
        "heavy": study_heavy(heavy_reps),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=4000)
    parser.add_argument("--heavy-reps", type=int, default=1500)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(
        json.dumps(run(args.reps, args.heavy_reps), indent=1) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
