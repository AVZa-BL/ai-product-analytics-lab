"""The data contract: what an export must hold for Referee to read it (design section 28).

`python -m referee.data_contract` writes `docs/data-contract.md` from the tables of the loader
(`referee.data`), the metrics Referee knows by name (`referee.results`), the reasons a metric can
fail to be read, and the worked example in `examples/custom-metrics/`. A test fails if the
committed file differs from what this writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from referee.data import (
    _REQUIRED,
    ASSIGNMENTS_FILE,
    BUILT_IN_COLUMNS,
    EXPOSURES_FILE,
    MANIFEST_FILE,
    OUTCOMES_FILE,
)
from referee.results import METRICS, REASONS
from referee.spec import RESERVED_COLUMNS

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "custom-metrics"

# Columns that are read when they are there (the others of each file are ignored, except in the
# outcomes file, where any other column may hold a metric).
OPTIONAL_COLUMNS: dict[str, dict[str, str]] = {
    ASSIGNMENTS_FILE: {
        "first_seen_at_utc": (
            "when the product first saw the player; when the column is there every row must hold "
            "a UTC instant, not after `assigned_at_utc`"
        ),
    },
    EXPOSURES_FILE: {
        "arm_config_version": (
            "the configuration the player saw at that exposure; when the column is there every "
            "row must hold a whole number"
        ),
    },
    OUTCOMES_FILE: {
        "window_end_utc": (
            "when the player's outcome window closes; when the column is there every row must "
            "hold a UTC instant. Without it the window is taken to be 7 days from the assignment"
        ),
        "sessions_7d": "a whole number of at least 0; the built-in metric of that name",
        "purchases_7d": (
            "a whole number of at least 0; when it is there, `first_purchase_at_utc` must be "
            "present exactly when it is above 0"
        ),
        "revenue_usd_7d": "a number of at least 0; the built-in metric of that name",
    },
}

_REQUIRED_MEANING = {
    "experiment_id": "which experiment the row belongs to; one folder may hold several",
    "player_id": (
        "the unit that was randomised; one row for each player in the assignments and the "
        "outcomes files"
    ),
    "arm": "the arm's name as the spec spells it",
    "assigned_at_utc": "when the player was assigned, as a UTC instant",
    "arm_config_version": (
        "the configuration of the arm at the assignment, a whole number of at least 0"
    ),
    "exposed_at_utc": (
        "when the player was exposed, as a UTC instant; a player may have several rows"
    ),
    "first_purchase_at_utc": (
        "when the player first bought, as a UTC instant, or empty if they did not; keep the "
        "column even if nobody buys, because RES-012 reads it"
    ),
}

_REASON_MEANING = {
    "column_missing": "the column the metric names is not in the outcomes file",
    "column_not_numeric": (
        "the column holds an empty cell, or a value that is not a finite number, in some row"
    ),
    "values_not_binary": (
        "the metric is declared binary and the column holds a value other than 0 or 1"
    ),
    "kind_mismatch": "a built-in metric is declared with another kind than it has",
    "kind_unsupported": (
        "the metric is declared `ratio`, which needs the delta method; it is not built"
    ),
}

_NO_RATE = "no simulated error rate is quoted"
_FAMILY_MEANING = (
    (
        "revenue_like",
        "an amount most players leave at 0 and a few make large",
        "RES-008 quotes its simulated error rates; RES-004 allows for the skew",
    ),
    ("count", "a whole number of events per player", _NO_RATE),
    ("binary", "0 or 1", _NO_RATE),
    (
        "other",
        "anything else (the default for a continuous metric on a column of your own)",
        _NO_RATE,
    ),
)


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _meaning(file: str, column: str) -> str:
    if (file, column) == (EXPOSURES_FILE, "player_id"):
        return "the player; a player may have several rows"
    return _REQUIRED_MEANING.get(column, "")


def _files() -> str:
    parts = []
    for name in (ASSIGNMENTS_FILE, EXPOSURES_FILE, OUTCOMES_FILE):
        rows = [[f"`{c}`", "required", _meaning(name, c)] for c in _REQUIRED[name]]
        rows += [[f"`{c}`", "read if present", text] for c, text in OPTIONAL_COLUMNS[name].items()]
        parts.append(f"### `{name}`\n\n" + _table(["Column", "", "Meaning"], rows))
    return "\n\n".join(parts)


def _builtin_table() -> str:
    definitions = {
        "sessions_7d": "the column `sessions_7d`",
        "purchases_7d": "the column `purchases_7d`",
        "revenue_usd_7d": "the column `revenue_usd_7d`",
        "purchased_7d": (
            "1 if `purchases_7d` is above 0, else 0 (a column named `purchased_7d` is read "
            "instead, if the file has one)"
        ),
    }
    rows = [[f"`{m.name}`", m.kind, m.family, definitions[m.name]] for m in METRICS.values()]
    return _table(["Metric", "Kind", "Family", "Value for a player"], rows)


def _example() -> str:
    spec = (EXAMPLE / "spec.yaml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(spec) if line.startswith("primary_metric:"))
    stop = next(i for i, line in enumerate(spec) if line.startswith("design:"))
    metrics = "\n".join(line for line in spec[start:stop]).rstrip()
    with (EXAMPLE / OUTCOMES_FILE).open(encoding="utf-8", newline="") as handle:
        rows = [line for _, line in zip(range(6), handle, strict=False)]
    return (
        "The metrics of `examples/custom-metrics/spec.yaml`:\n\n```yaml\n"
        + metrics
        + "\n```\n\nand the first rows of `examples/custom-metrics/experiment_outcomes.csv`, which "
        "holds no built-in metric column:\n\n```csv\n"
        + "".join(rows).rstrip()
        + "\n```\n\nRun it with `python -m referee review-results "
        "examples/custom-metrics/spec.yaml examples/custom-metrics "
        "--experiment-id tutorial_test --as-of 2026-03-20T00:00:00Z --mode monitor`."
    )


def render_data_contract_markdown() -> str:
    """The contract as markdown, from the loader's tables."""
    blocks = [
        "# Data contract\n\nGenerated from the loader by `python -m referee.data_contract`. Do not "
        "edit this file by hand: a test fails if it differs from the generated text.\n\n"
        "A folder of three CSV files (UTF-8, a header row) describes an experiment, with an "
        f"optional `{MANIFEST_FILE}` that may hold `exported_at_utc`. Every timestamp is ISO 8601 "
        "in UTC (`2026-04-11T00:02:25Z`, `2026-04-11 00:02:25+00`). Every row of the chosen "
        "experiment is read; nothing is sampled. A file that breaks the contract is refused with "
        "every problem listed, each with its file and line.",
        "## The files\n\n" + _files(),
        "## Metrics\n\n"
        "A spec names the metrics it wants read: the primary metric, the guardrails and, "
        "optionally, `secondary_metrics`. Each is read from one column of "
        f"`{OUTCOMES_FILE}`: the one named by its `column`, else the one named like the metric. "
        "The column holds one number for each player. For a `binary` metric every value is 0 or "
        "1; for a `continuous` metric every value is a finite number. An empty cell or a value "
        "that is not a number makes the column unreadable as a metric. Any column of the file "
        "that is not listed above can hold a metric, and the names "
        + ", ".join(f"`{c}`" for c in sorted(RESERVED_COLUMNS))
        + " cannot be used as `column`.",
        "### Metrics Referee knew by name\n\n"
        f"The columns {', '.join(f'`{c}`' for c in BUILT_IN_COLUMNS)}, and `purchased_7d`, "
        "keep the kind and family below, so a spec written for the lab's export still works. A "
        "spec may declare another `family` for them.\n\n" + _builtin_table(),
        "### Family\n\n"
        "A metric's `family` says what its values look like, and so which simulated error rates "
        "Referee may quote for it. It is declared in the spec, or defaults to `binary` for a "
        "binary metric, to the table above for a built-in one, and to `other` for any other "
        "metric. The monitor's ledger prints the family each metric was read as.\n\n"
        + _table(["Family", "Values", "Effect"], [[f"`{a}`", b, c] for a, b, c in _FAMILY_MEANING]),
        "### When a metric cannot be read\n\n"
        "A results review refuses to run, and lists the problem, when the primary metric or a "
        "guardrail cannot be read. A secondary metric that cannot be read is listed with its "
        "reason (a review analyses no secondary metric) and never refuses a review or changes "
        "its verdict. The monitor (`--mode monitor`) refuses only when the primary metric cannot "
        "be read; for any other declared metric it lists the reason in its ledger and goes "
        "on.\n\n"
        + _table(["Reason", "Meaning"], [[f"`{r}`", _REASON_MEANING[r]] for r in REASONS])
        + "\n\nThe monitor adds `window_not_matured` (every analysed player's outcome window is "
        "still open) and `no_estimate` (the data allow no estimate; the statistics' reason is "
        "given).",
        "## A worked example\n\n" + _example(),
    ]
    return "\n\n".join(block.strip("\n") for block in blocks) + "\n"


def main() -> None:
    sys.stdout.write(render_data_contract_markdown())


if __name__ == "__main__":
    main()
