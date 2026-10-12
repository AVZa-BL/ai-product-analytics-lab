"""Hand-built exports for the cohort tests: players placed in 7-day blocks of first exposure."""

import numpy as np
from results_helpers import TWO_ARMS, Row, at, build_data, results_spec

from referee.results import ResultsContext

START = "2026-04-11T00:00:00Z"
SESSIONS = {
    "primary_metric__name": "sessions_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 10.0,
    "primary_metric__baseline_std": 5.0,
    "design__mde_relative": 2.0,
}
THREE_ARMS = [
    {"name": "control", "allocation": 0.4, "is_control": True},
    {"name": "variant_b", "allocation": 0.3},
    {"name": "variant_c", "allocation": 0.3},
]


def cohort_rows(
    arm: str, per_block: dict[int, list[int]], *, tag: str = "", version_of=lambda block: 1
) -> list[Row]:
    """One player per session count, assigned and first exposed in the given 7-day block.

    `version_of` gives the configuration version a block's players were assigned and exposed on.
    """
    rows = []
    for block, sessions in per_block.items():
        for i, count in enumerate(sessions):
            rows.append(
                Row(
                    f"{arm}{tag}_{block:02d}_{i:04d}",
                    arm,
                    assigned_at=at(7 * block),
                    exposed_at=at(7 * block, 1),
                    assigned_version=version_of(block),
                    exposure_version=version_of(block),
                    sessions=count,
                )
            )
    return rows


def cohort_draws(seed: int, means: dict[int, float], n: int = 80) -> dict[int, list[int]]:
    """Poisson session counts, `n` players for each block's mean."""
    rng = np.random.default_rng(seed)
    return {block: [int(v) for v in rng.poisson(mean, n)] for block, mean in means.items()}


def spread(mean: int, unit: int = 1, n: int = 80) -> list[int]:
    """`n` session counts with exactly this mean and a standard deviation of about 1.4 units."""
    return [mean + unit * step for step in (-2, -1, 0, 1, 2)] * (n // 5)


def cohort_context(
    raw_spec, rows: list[Row], *, days: int = 28, arms=TWO_ARMS, exported_at=None, **more
) -> ResultsContext:
    """A results context over `rows`, planned for `days` days, with blocks counted from START."""
    spec = results_spec(
        raw_spec,
        arms=arms,
        design__planned_duration_days=days,
        design__min_duration_days=7,
        design__start_utc=START,
        **{**SESSIONS, **more},
    )
    return ResultsContext.of(spec, build_data(rows, exported_at=exported_at))


def sized_context(
    raw_spec,
    arm: dict[int, int],
    control: dict[int, int],
    *,
    days: int,
    copies: int = 1,
    exported_at=None,
    extra: dict[str, dict[int, int]] | None = None,
    arms=TWO_ARMS,
    stretch: bool = False,
    **more,
) -> ResultsContext:
    """`arm[b]` and `control[b]` players first exposed in weekly block b, `copies` times over.

    Only the sizes matter here: every player has the default outcomes. A copy is a distinct
    player with the same times, so `copies` multiplies every cohort exactly. `extra` gives the
    sizes of further arms by name (with `arms` listing them all, as in THREE_ARMS). With
    `stretch`, the last control player is placed on the last day of the plan (which must be
    the last block of its window), so that the assignments span the planned duration and the
    run is not an interim look.
    """
    rows = []
    cohorts = {"variant_b": arm, "control": control, **(extra or {})}
    for name, sizes in cohorts.items():
        for block, count in sizes.items():
            for i in range(count * copies):
                rows.append(
                    Row(
                        f"{name}_{block:02d}_{i:05d}",
                        name,
                        assigned_at=at(7 * block),
                        exposed_at=at(7 * block, 1),
                    )
                )
    if stretch:
        last = max(i for i, row in enumerate(rows) if row.arm == "control")
        rows[last].assigned_at, rows[last].exposed_at = at(days - 1, 23), at(days - 1, 23.5)
    return cohort_context(raw_spec, rows, days=days, arms=arms, exported_at=exported_at, **more)
