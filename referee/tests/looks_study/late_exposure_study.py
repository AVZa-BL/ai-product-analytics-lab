"""Late exposure (RES-012) and the sample-ratio onset in the lab's experiment (design section 25).

Per seed, with the lab's generator at the 5,000-player scale:

- `onset`: the share of variant_c among the assignments of each day, and the weekly counts;
- `calibration`: on the planted data, at 2, 3, 5, 7, 10, 14 and 21 days, how often a chi-squared
  test of the late share of the exposed players, of the late share of the purchasers and of the
  purchase rate of the exposed players rejects at 0.05 and at 0.001;
- `power`: on data with the arms redrawn (A/A), a delay of 0, 1, 6 or 24 hours added to every
  exposure of variant_b, and at 10 and 21 days how often RES-012 blocks as it is now, and how
  often a test of the late share of the purchasers or of the delay between assignment and first
  exposure (Kruskal-Wallis) has p below 0.001.

    python tests/looks_study/late_exposure_study.py --seeds 101 --workers 4 \\
        --out docs/simulations/late_exposure.json

(about 15 minutes on four cores).
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import duckdb
import numpy as np
from common import ARMS, EXPERIMENT, SPEC, cut_export, generate, instant, origin_of
from scipy.stats import chi2_contingency, chisquare, kruskal

CUTS = (2, 3, 5, 7, 10, 14, 21)
POWER_CUTS = (10, 21)
SHIFT_HOURS = (0, 1, 6, 24)
ALPHA = 0.001


def _chi2(success: np.ndarray, total: np.ndarray) -> float:
    if total.min() == 0 or success.sum() in (0, total.sum()):
        return 1.0
    return float(chi2_contingency(np.array([success, total - success]))[1])


def _planted_tests(con, base: Path, origin, days: int) -> dict[str, float]:
    cut = f"timestamp '{origin}' + interval {days} day"
    rows = con.sql(f"""
        with a as (select player_id, arm from read_parquet('{base}/experiment_assignments.parquet')
                   where assigned_at_utc < {cut}),
        fx as (select player_id, min(exposed_at_utc) first_exposed
               from read_parquet('{base}/experiment_exposures.parquet')
               where exposed_at_utc < {cut} group by 1),
        j as (select arm, first_exposed, first_purchase_at_utc purchase
              from a join fx using (player_id)
              join read_parquet('{base}/experiment_outcomes.parquet') using (player_id))
        select arm, count(*), count(purchase),
               sum(case when purchase is not null and first_exposed > purchase then 1 else 0 end)
        from j group by 1 order by 1""").fetchall()
    exposed, purchasers, late = (np.array([r[i] for r in rows]) for i in (1, 2, 3))
    return {
        "late_of_exposed": _chi2(late, exposed),
        "late_of_purchasers": _chi2(late, purchasers),
        "purchase_rate": _chi2(purchasers, exposed),
    }


def _res012_severity(folder: Path, cut, spec) -> str:
    from referee.data import load_export
    from referee.results import ResultsContext
    from referee.review import review_context
    from referee.rules import RESULTS_RULES

    rules = [rule for rule in RESULTS_RULES if rule.id == "RES-012"]
    data = replace(load_export(folder, EXPERIMENT), exported_at=cut)
    review = review_context(ResultsContext.of(spec, data), rules=rules)
    return review.findings[0].severity if review.findings else "none"


def _candidates(folder: Path) -> dict[str, float]:
    arm = {}
    assigned = {}
    for r in csv.DictReader(open(folder / "experiment_assignments.csv")):
        arm[r["player_id"]] = r["arm"]
        assigned[r["player_id"]] = instant(r["assigned_at_utc"])
    first = {}
    for r in csv.DictReader(open(folder / "experiment_exposures.csv")):
        when = instant(r["exposed_at_utc"])
        if r["player_id"] not in first or when < first[r["player_id"]]:
            first[r["player_id"]] = when
    purchase = {
        r["player_id"]: instant(r["first_purchase_at_utc"]) if r["first_purchase_at_utc"] else None
        for r in csv.DictReader(open(folder / "experiment_outcomes.csv"))
    }
    purchasers = dict.fromkeys(ARMS, 0)
    late = dict.fromkeys(ARMS, 0)
    delays: dict[str, list[float]] = {a: [] for a in ARMS}
    for player, when in first.items():
        delays[arm[player]].append((when - assigned[player]).total_seconds())
        if purchase.get(player) is not None:
            purchasers[arm[player]] += 1
            late[arm[player]] += when > purchase[player]
    n_late = np.array([late[a] for a in ARMS])
    n_purchasers = np.array([purchasers[a] for a in ARMS])
    return {
        "late_of_purchasers": _chi2(n_late, n_purchasers),
        "delay": float(kruskal(*[delays[a] for a in ARMS])[1]),
        "late_share_gap": late["variant_b"] / max(1, len(delays["variant_b"]))
        - late["control"] / max(1, len(delays["control"])),
    }


def one_seed(seed: int) -> dict:
    from referee.loader import load_spec

    spec = load_spec(str(SPEC))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        base = generate(seed, work / "raw")
        con = duckdb.connect()
        con.sql("set TimeZone = 'UTC'")
        assign = f"read_parquet('{base}/experiment_assignments.parquet')"
        origin = con.sql(
            f"select date_trunc('day', min(assigned_at_utc)) from {assign}"
        ).fetchone()[0]
        daily = con.sql(f"""select date_diff('day', timestamp '{origin}', assigned_at_utc) as d,
                            arm, count(*) as n from {assign} group by 1, 2""").df()
        pivot = daily.pivot_table(index="d", columns="arm", values="n", fill_value=0)
        out = {
            "seed": seed,
            "weekly_counts": [
                [int(pivot.loc[7 * w : 7 * w + 6, a].sum()) for a in ARMS] for w in range(3)
            ],
            "variant_c_share_by_day": [
                float(pivot.loc[d, "variant_c"] / pivot.loc[d].sum()) for d in range(21)
            ],
            "calibration": {str(d): _planted_tests(con, base, origin, d) for d in CUTS},
            "power": {},
        }
        players = con.sql(f"select distinct player_id from {assign} order by 1").df()
        players["new_arm"] = np.random.default_rng(seed + 10_000).choice(ARMS, size=len(players))
        con.register("players", players)
        for hours in SHIFT_HOURS:
            folder = work / f"shift{hours}"
            folder.mkdir()
            con.sql(
                f"copy (select t.* replace (p.new_arm as arm, 1 as arm_config_version) "
                f"from {assign} t join players p using (player_id) order by 1, 2) "
                f"to '{folder}/experiment_assignments.csv' (header)"
            )
            con.sql(
                f"copy (select t.* replace (p.new_arm as arm, 1 as arm_config_version, "
                f"case when p.new_arm = 'variant_b' then t.exposed_at_utc + interval {hours} hour "
                f"else t.exposed_at_utc end as exposed_at_utc) "
                f"from read_parquet('{base}/experiment_exposures.parquet') t "
                f"join players p using (player_id) order by 1, 2) "
                f"to '{folder}/experiment_exposures.csv' (header)"
            )
            con.sql(
                f"copy (select * from read_parquet('{base}/experiment_outcomes.parquet') "
                f"order by 1, 2) to '{folder}/experiment_outcomes.csv' (header)"
            )
            out["power"][str(hours)] = {}
            for days in POWER_CUTS:
                target = work / f"shift{hours}_d{days}"
                cut, _ = cut_export(folder, days, target, origin_of(folder))
                found = _candidates(target)
                found["res012"] = _res012_severity(target, cut, spec)
                out["power"][str(hours)][str(days)] = found
    return out


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    weekly = np.array([r["weekly_counts"] for r in rows])  # seed, week, arm
    summary: dict = {
        "seeds": n,
        "alpha": ALPHA,
        "variant_c_share_by_day": np.round(
            np.mean([r["variant_c_share_by_day"] for r in rows], axis=0), 4
        ).tolist(),
        "weekly_srm_p_below_0.001": [
            float(np.mean([chisquare(w).pvalue < ALPHA for w in weekly[:, week]]))
            for week in range(3)
        ],
        "calibration": {},
        "power": {},
    }
    for days in CUTS:
        summary["calibration"][str(days)] = {
            test: {
                "p_below_0.05": float(
                    np.mean([r["calibration"][str(days)][test] < 0.05 for r in rows])
                ),
                "p_below_0.001": float(
                    np.mean([r["calibration"][str(days)][test] < ALPHA for r in rows])
                ),
            }
            for test in ("late_of_exposed", "late_of_purchasers", "purchase_rate")
        }
    for hours in SHIFT_HOURS:
        summary["power"][str(hours)] = {}
        for days in POWER_CUTS:
            cell = [r["power"][str(hours)][str(days)] for r in rows]
            summary["power"][str(hours)][str(days)] = {
                "res012_blocker": float(np.mean([c["res012"] == "blocker" for c in cell])),
                "late_of_purchasers_p_below_0.001": float(
                    np.mean([c["late_of_purchasers"] < ALPHA for c in cell])
                ),
                "delay_p_below_0.001": float(np.mean([c["delay"] < ALPHA for c in cell])),
                "mean_late_share_gap_b_minus_control": float(
                    np.mean([c["late_share_gap"] for c in cell])
                ),
            }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=101, help="seeds 1..N")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(one_seed, range(1, args.seeds + 1)))
    args.out.write_text(json.dumps(summarise(rows), indent=1) + "\n")


if __name__ == "__main__":
    main()
