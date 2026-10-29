"""Write the hybrid scenario's validation record from dbt's run results and the diagnostic JSON.

The record binds the dbt build that produced the governed DuckDB artifact to the diagnostic
that read it. The two name one commit by construction: the commit is taken from the diagnostic
JSON, and the build must have finished before the diagnostic ran. Counting the outcomes from
`run_results.json` replaces copying them from the terminal.

Run from analytics-lab/ after `bash scripts/validation/run_hybrid_subscription_checks.sh` and
the notebook execution:

    python scripts/validation/write_native_validation.py [game_analytics/target/run_results.json]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_RESULTS = ROOT / "game_analytics" / "target" / "run_results.json"
REPORTS = ROOT / "reports" / "hybrid_subscription"
DIAGNOSTIC = REPORTS / "engagement_cannibalization_diagnostic_results.json"
RECORD = REPORTS / "native_validation.json"
SELECTOR = "hybrid_subscription"
MODE = (
    "dbt build of the selector from the regenerated fixture, before the diagnostic notebook "
    "read the resulting DuckDB artifact"
)


def build_record(run_results: dict, diagnostic: dict) -> dict:
    args, metadata, results = run_results["args"], run_results["metadata"], run_results["results"]
    if (args.get("which"), args.get("selector")) != ("build", SELECTOR):
        raise ValueError(
            f"expected a `dbt build --selector {SELECTOR}` run, got {args.get('which')!r} "
            f"with selector {args.get('selector')!r}"
        )
    executed_at = diagnostic["metadata"]["executed_at_utc"]
    if datetime.fromisoformat(metadata["generated_at"]) > datetime.fromisoformat(executed_at):
        raise ValueError(
            f"the build finished at {metadata['generated_at']}, after the diagnostic ran "
            f"at {executed_at}; the diagnostic must read the artifact this build produced"
        )

    outcomes = Counter((r["unique_id"].split(".")[0], r["status"]) for r in results)
    counts = {
        "successful_models": outcomes.pop(("model", "success"), 0),
        "passed_tests": outcomes.pop(("test", "pass"), 0),
        "passed_unit_tests": outcomes.pop(("unit_test", "pass"), 0),
        "warnings": sum(n for (_, status), n in outcomes.items() if status == "warn"),
        "errors": sum(n for (_, status), n in outcomes.items() if status in ("error", "fail")),
        "skipped": sum(n for (_, status), n in outcomes.items() if status == "skipped"),
    }
    if sum(counts.values()) != len(results):
        known = ("warn", "error", "fail", "skipped")
        unexpected = {key: n for key, n in outcomes.items() if key[1] not in known}
        raise ValueError(f"results with an outcome this record has no field for: {unexpected}")

    return {
        "source_commit": diagnostic["metadata"]["code_version"],
        "mode": MODE,
        "selector": SELECTOR,
        "dbt_version": metadata["dbt_version"],
        "generated_at_utc": metadata["generated_at"],
        "diagnostic_executed_at_utc": executed_at,
        "results": {**counts, "total": len(results)},
    }


def main(argv: list[str]) -> int:
    run_results_path = Path(argv[1]) if len(argv) > 1 else RUN_RESULTS
    run_results = json.loads(run_results_path.read_text(encoding="utf-8"))
    diagnostic = json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))
    record = build_record(run_results, diagnostic)
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {RECORD.relative_to(ROOT)}: {record['results']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
