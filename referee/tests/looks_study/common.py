"""Shared pieces of the repeated-looks studies (design section 24).

These scripts are studies, not tests: pytest does not collect them. They need the analytics lab's
generator (`pip install -e ../analytics-lab`, which brings DuckDB) next to Referee, because they
make fresh experiments with `python -m analytics_lab.generate`; Referee itself does not.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "referee" / "examples" / "offer-page-results.yaml"
EXPERIMENT = "hybrid_offer_page"
ARMS = ("control", "variant_b", "variant_c")
TABLES = ("experiment_assignments", "experiment_exposures", "experiment_outcomes")


def instant(text: str) -> datetime:
    """A timestamp as DuckDB writes it (`2026-04-11 00:02:25+00`)."""
    return datetime.fromisoformat(text.replace("+00", "+00:00"))


def generate(seed: int, out: Path) -> Path:
    """Run the lab's generator at the 5,000-player reference scale; return the raw folder."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "analytics_lab.generate",
            "--scenario",
            "hybrid_subscription",
            "--seed",
            str(seed),
            "--start-date",
            "2026-01-01",
            "--days",
            "180",
            "--scale",
            "5000",
            "--output-dir",
            str(out),
        ],
        check=True,
        capture_output=True,
        cwd=REPO / "analytics-lab",
    )
    return out / "hybrid_subscription"


def cut_export(source: Path, days: int, target: Path, origin: datetime) -> tuple[datetime, int]:
    """The export as it would stand `days` days after `origin`: the assignments and exposures
    before that instant, and the outcomes of the players kept. Judgement: the outcomes keep the
    rows of their whole seven days, which Referee leaves out of the effect table where the
    window is still open; a late exposure needs an exposure and a purchase both before the cut,
    so the rows past it change RES-012 little."""
    cut = origin + timedelta(days=days)
    read = {name: list(csv.DictReader(open(source / f"{name}.csv"))) for name in TABLES}
    assigned = [r for r in read["experiment_assignments"] if instant(r["assigned_at_utc"]) < cut]
    kept = {r["player_id"] for r in assigned}
    rows = {
        "experiment_assignments": assigned,
        "experiment_exposures": [
            r
            for r in read["experiment_exposures"]
            if instant(r["exposed_at_utc"]) < cut and r["player_id"] in kept
        ],
        "experiment_outcomes": [r for r in read["experiment_outcomes"] if r["player_id"] in kept],
    }
    target.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        with open(target / f"{name}.csv", "w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(read[name][0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows[name])
    return cut, len(assigned)


def origin_of(folder: Path) -> datetime:
    """The first assignment's day, which is the origin Referee counts weeks from."""
    first = min(
        instant(r["assigned_at_utc"])
        for r in csv.DictReader(open(folder / "experiment_assignments.csv"))
    )
    return first.replace(hour=0, minute=0, second=0, microsecond=0)
