"""Which rules block an interim review of the lab's experiment, planted and A/A (design section 24).

For each seed the lab's generator makes the 5,000-player offer-page experiment. Two variants are
read at 2, 3, 5, 7, 10, 14 and 21 days after the first assignment: `orig`, as generated (with its
planted defects), and `aa`, in which every player's arm is redrawn with equal probability and the
configuration version is set to 1, so that nothing differs between the arms. The summary says,
for each rule, in what share of seeds it blocks at each cut, and at which cut RES-001 first
blocks.

    python tests/looks_study/looks_sweep.py --seeds 101 --workers 4 \\
        --out docs/simulations/looks_planted_vs_aa.json

(about 15 minutes on four cores; a seed takes about 15 s).
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import duckdb
import numpy as np
from common import ARMS, EXPERIMENT, SPEC, TABLES, cut_export, generate, origin_of

CUTS = (2, 3, 5, 7, 10, 14, 21)
RULES = ("RES-001", "RES-002", "RES-003", "RES-011", "RES-012", "RES-013")


def _variants(seed: int, work: Path) -> dict[str, Path]:
    base = generate(seed, work / "raw")
    con = duckdb.connect()
    con.sql("set TimeZone = 'UTC'")
    made = {"orig": work / "orig", "aa": work / "aa"}
    for folder in made.values():
        folder.mkdir()
    for table in TABLES:
        con.sql(
            f"copy (select * from read_parquet('{base}/{table}.parquet') order by 1, 2) "
            f"to '{made['orig']}/{table}.csv' (header)"
        )
    players = con.sql(
        f"select distinct player_id from read_parquet('{base}/experiment_assignments.parquet') "
        "order by 1"
    ).df()
    players["new_arm"] = np.random.default_rng(seed + 10_000).choice(ARMS, size=len(players))
    con.register("players", players)
    for table in ("experiment_assignments", "experiment_exposures"):
        con.sql(
            f"copy (select t.* replace (p.new_arm as arm, 1 as arm_config_version) "
            f"from read_parquet('{base}/{table}.parquet') t join players p using (player_id) "
            f"order by 1, 2) to '{made['aa']}/{table}.csv' (header)"
        )
    shutil.copy(made["orig"] / "experiment_outcomes.csv", made["aa"] / "experiment_outcomes.csv")
    return made


def _review(folder: Path, cut, spec) -> dict[str, list]:
    from referee.data import load_export
    from referee.results import ResultsContext
    from referee.review import review_context

    data = replace(load_export(folder, EXPERIMENT), exported_at=cut)
    found = {}
    for finding in review_context(ResultsContext.of(spec, data)).findings:
        found[finding.rule_id] = finding.severity
    return found


def one_seed(seed: int) -> dict:
    from referee.loader import load_spec

    spec = load_spec(str(SPEC))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        out = {"seed": seed}
        for name, folder in _variants(seed, work).items():
            origin = origin_of(folder)
            out[name] = {}
            for days in CUTS:
                cut, _ = cut_export(folder, days, work / f"{name}_d{days}", origin)
                out[name][days] = _review(work / f"{name}_d{days}", cut, spec)
    return out


def summarise(rows: list[dict]) -> dict:
    summary: dict = {"seeds": len(rows), "cuts": list(CUTS)}
    for variant in ("orig", "aa"):
        block: dict = {"blocker_share_by_cut": {}, "fires_share_by_cut": {}}
        for rule in RULES:
            block["blocker_share_by_cut"][rule] = [
                sum(r[variant][c].get(rule) == "blocker" for r in rows) / len(rows) for c in CUTS
            ]
            block["fires_share_by_cut"][rule] = [
                sum(rule in r[variant][c] for r in rows) / len(rows) for c in CUTS
            ]
        block["seeds_with_blocker_at_some_cut"] = {
            rule: sum(any(r[variant][c].get(rule) == "blocker" for c in CUTS) for r in rows)
            for rule in RULES
        }
        first = Counter(
            next((c for c in CUTS if r[variant][c].get("RES-001") == "blocker"), None) for r in rows
        )
        block["first_res001_blocker_cut"] = {
            str(k): v for k, v in sorted(first.items(), key=lambda kv: (kv[0] is None, kv[0]))
        }
        summary[variant] = block
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
