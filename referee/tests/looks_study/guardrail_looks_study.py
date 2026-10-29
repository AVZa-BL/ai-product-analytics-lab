"""How often RES-004's guardrail check alarms on A/A data when it is read at several looks
(design section 25).

Three equal arms are drawn from one distribution whose mean is the registered baseline, so
nothing differs. The samples are nested: the first n players of each arm are what the review sees
after the first n arrive, with n per arm 95, 145, 240, 330, 470, 650 and 940 (the lab's
experiment at 2, 3, 5, 7, 10, 14 and 21 days). Each look is read by `referee.guardrails`, the code
of RES-004, with a tolerance of 10%. "Shown" is the blocker tier (the whole 95% interval beyond
the tolerance), "possible" the warning tier (the point estimate beyond it). The share of runs
with an alarm at least once in the 7 looks is combined for m guardrails by 1 - (1 - p) ** m, which
assumes the guardrails are independent.

    python tests/looks_study/guardrail_looks_study.py --reps 800 \\
        --out docs/simulations/guardrail_looks.json

(about 8 minutes on four cores; `--reps` is divided into four streams per type).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

N_PER_ARM = (95, 145, 240, 330, 470, 650, 940)
ARMS = ("control", "variant_b", "variant_c")
TYPES = {
    # name: (metric name in the registry, kind, harmful direction, baseline, standard deviation)
    "sessions_like": ("sessions_7d", "continuous", "decrease", 4.5, 3.2),
    "revenue_like": ("revenue_usd_7d", "continuous", "decrease", 1.9, 10.0),
    "binary_rate": ("purchased_7d", "binary", "increase", 0.10, None),
}
TOLERANCE = 0.10
# Revenue-like: 15% of players spend, a lognormal amount with mean 12.67; the overall mean is
# 1.9 and the overall standard deviation 10 (exp(sigma^2) = 4.30).
_SIGMA = float(np.sqrt(np.log(4.30)))
_MU = float(np.log(12.67) - _SIGMA**2 / 2)


def draw(rng: np.random.Generator, kind: str, n: int) -> np.ndarray:
    if kind == "sessions_like":  # gamma with mean 4.5 and standard deviation 3.2
        shape = (4.5 / 3.2) ** 2
        return rng.gamma(shape, 4.5 / shape, n)
    if kind == "revenue_like":
        return (rng.random(n) < 0.15) * rng.lognormal(_MU, _SIGMA, n)
    return (rng.random(n) < 0.10).astype(float)


def run(job: tuple[str, int, int]) -> tuple[str, np.ndarray, np.ndarray]:
    from referee.guardrails import _tests_of
    from referee.results import ExportMetric
    from referee.spec import Guardrail

    kind, seed, reps = job
    name, metric_kind, direction, baseline, std = TYPES[kind]
    guardrail = Guardrail(
        name=name,
        kind=metric_kind,
        baseline=baseline,
        baseline_std=std,
        harmful_direction=direction,
        tolerance_relative=TOLERANCE,
    )
    metric = ExportMetric(name, metric_kind, lambda player: player.value)
    rng = np.random.default_rng(seed)
    possible = np.zeros((reps, len(N_PER_ARM)), bool)
    shown = np.zeros_like(possible)
    for rep in range(reps):
        full = {arm: draw(rng, kind, N_PER_ARM[-1]) for arm in ARMS}
        for look, n in enumerate(N_PER_ARM):
            players = [NS(arm=arm, value=float(v)) for arm in ARMS for v in full[arm][:n]]
            context = NS(
                spec=NS(guardrails=[guardrail]),
                metrics={name: metric},
                analysed=players,
                arm_names=list(ARMS),
                control="control",
                exported_at=None,
            )
            tiers = [test.tier for test in _tests_of(context, guardrail)]
            possible[rep, look] = any(t in ("possible", "shown") for t in tiers)
            shown[rep, look] = "shown" in tiers
    return kind, possible, shown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=800)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    jobs = [(kind, 100 + i, args.reps // 4) for kind in TYPES for i in range(4)]
    stacked = {kind: ([], []) for kind in TYPES}
    with ProcessPoolExecutor(args.workers) as pool:
        for kind, possible, shown in pool.map(run, jobs):
            stacked[kind][0].append(possible)
            stacked[kind][1].append(shown)
    out: dict = {"looks_n_per_arm": list(N_PER_ARM), "tolerance": TOLERANCE}
    for kind, (possible_runs, shown_runs) in stacked.items():
        possible, shown = np.vstack(possible_runs), np.vstack(shown_runs)
        ever_possible, ever_shown = possible.any(1).mean(), shown.any(1).mean()
        out[kind] = {
            "reps": len(possible),
            "possible_or_shown_by_look": possible.mean(0).round(4).tolist(),
            "shown_by_look": shown.mean(0).round(4).tolist(),
            "possible_or_shown_at_least_once": float(ever_possible),
            "shown_at_least_once": float(ever_shown),
            "shown_at_least_once_for_m_independent_guardrails": {
                str(m): float(1 - (1 - ever_shown) ** m) for m in (1, 2, 5, 10)
            },
        }
    args.out.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
