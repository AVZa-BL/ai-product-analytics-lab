"""Helpers shared by the results-review test modules: small exports built by hand."""

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from referee.data import Assignment, ExperimentData, Exposure, Outcome
from referee.spec import ExperimentSpec

T0 = datetime(2026, 4, 11, tzinfo=UTC)
ARMS = ("control", "variant_b", "variant_c")


def at(days: float = 0.0, hours: float = 0.0) -> datetime:
    """An instant `days` and `hours` after the start of the test."""
    return T0 + timedelta(days=days, hours=hours)


@dataclass
class Row:
    """One player as the three tables would hold them.

    Times are instants. `exposed_at` of None means the player was never exposed;
    `extra_exposures` are later (or earlier) exposures of the same player.
    """

    player_id: str
    arm: str = "control"
    assigned_at: datetime = T0
    exposed_at: datetime | None = T0 + timedelta(minutes=5)
    assigned_version: int = 1
    exposure_version: int | None = 1
    extra_exposures: tuple[tuple[datetime, int | None], ...] = ()
    sessions: int = 3
    purchases: int = 0
    revenue: float = 0.0
    first_purchase_at: datetime | None = None
    window_end: datetime | None = None  # None: seven days after the assignment


def build_data(rows: list[Row], *, experiment_id: str = "e1", exported_at=None) -> ExperimentData:
    """The `ExperimentData` the loader would return for these rows (in player order)."""
    assignments, exposures, outcomes = [], [], []
    for row in sorted(rows, key=lambda r: r.player_id):
        assignments.append(
            Assignment(row.player_id, row.arm, row.assigned_at, row.assigned_version)
        )
        if row.exposed_at is not None:
            exposures.append(Exposure(row.player_id, row.exposed_at, row.exposure_version))
        exposures.extend(Exposure(row.player_id, when, v) for when, v in row.extra_exposures)
        outcomes.append(
            Outcome(
                row.player_id,
                row.sessions,
                row.purchases,
                row.revenue,
                row.first_purchase_at,
                row.window_end
                if row.window_end is not None
                else row.assigned_at + timedelta(days=7),
            )
        )
    exposures.sort(
        key=lambda e: (
            e.player_id,
            e.exposed_at,
            -1 if e.config_version is None else e.config_version,
        )
    )
    return ExperimentData(
        experiment_id=experiment_id,
        assignments=tuple(assignments),
        exposures=tuple(exposures),
        outcomes=tuple(outcomes),
        exported_at=exported_at,
    )


def results_spec(raw_spec: dict, **changes: object) -> ExperimentSpec:
    """The shared test spec turned into one a results review can read.

    Three equal arms, a binary primary metric the export holds (`purchased_7d`) and no
    guardrails. A change is `section__field=value`; a double underscore stands for the dot.
    """
    raw = copy.deepcopy(raw_spec)
    third = 1 / 3
    raw["arms"] = [
        {"name": "control", "allocation": third, "is_control": True},
        {"name": "variant_b", "allocation": third},
        {"name": "variant_c", "allocation": third},
    ]
    raw["primary_metric"] = {"name": "purchased_7d", "kind": "binary", "baseline": 0.05}
    raw["guardrails"] = []
    raw["design"]["mde_relative"] = 0.3
    for dotted, value in changes.items():
        *parents, leaf = dotted.split("__")
        node = raw
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return ExperimentSpec.from_dict(raw)


def crowd(arm: str, count: int, *, prefix: str | None = None, **fields: object) -> list[Row]:
    """`count` players of one arm, with ids `<prefix>_0000`... and the same other fields."""
    name = prefix or arm
    return [Row(f"{name}_{i:04d}", arm, **fields) for i in range(count)]


def evaluate_results(rule, spec: ExperimentSpec, rows: list[Row]):
    """Run one results rule over hand-built rows read against `spec`."""
    from referee.results import ResultsContext

    return rule.evaluate(ResultsContext.of(spec, build_data(rows)))


TWO_ARMS = [
    {"name": "control", "allocation": 0.5, "is_control": True},
    {"name": "variant_b", "allocation": 0.5},
]
