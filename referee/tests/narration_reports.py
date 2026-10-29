"""The eight reports of the narration tests (design section 24.11), the only report names used.

`report(name, raw_spec)` returns a copy of the named results report. `golden` is the committed
report; the others are made from the rows of `results_helpers` with the engine's public functions,
once for each name and spec dict in a session (`raw_spec` is a function-scoped fixture that a test
may change, so it is a parameter and its hash is part of the cache key).

    clear                a clear verdict: a binary primary metric, no guardrail, 28 days of 5,000
                         players an arm (fewer, or a shorter plan, and RES-002 or RES-007 speak)
    warnings_only        a caution: RES-012 (equal late shares) and RES-013 (a changed arm)
    harm_blocker         invalid by RES-004 alone: variant_b makes a guardrail worse
    unattainable_design  RES-002 for a design that cannot be sized
    short_arms           RES-002 for arms smaller than the plan asks
    short_run            RES-003: the assignments span 5 of the 14 registered days
    weekly_drift         RES-011: two weeks fail the sample ratio check, the total passes
"""

import copy
import hashlib
import json
import random
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from results_helpers import Row, at, build_data, results_spec

from referee.report import results_report
from referee.results import ResultsContext
from referee.review import origin_sensitivity, review_context

NAMES = (
    "golden",
    "clear",
    "warnings_only",
    "harm_blocker",
    "unattainable_design",
    "short_arms",
    "short_run",
    "weekly_drift",
)
GOLDEN = Path(__file__).resolve().parent / "golden" / "offer-page-results.json"

ARMS = ("control", "variant_b", "variant_c")
START = "2026-04-11T00:00:00Z"  # the origin of the helpers' clock
FILES = {
    "experiment_assignments.csv": "a" * 64,
    "experiment_exposures.csv": "b" * 64,
    "experiment_outcomes.csv": "c" * 64,
}
SESSIONS_GUARDRAIL = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 4.5,
    "baseline_std": 3.2,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.10,
}


def _players(arm, count, rng, *, days=28.0, first_day=0.0, tag="") -> list[Row]:
    """`count` players of one arm, assigned at random over `days` days and exposed five minutes
    later, 5% of whom buy a day and a half after the assignment."""
    rows = []
    for number in range(count):
        assigned = at(first_day + days * rng.random())
        buys = rng.random() < 0.05
        rows.append(
            Row(
                f"{arm}{tag}_{number:05d}",
                arm,
                assigned_at=assigned,
                exposed_at=assigned + timedelta(minutes=5),
                purchases=int(buys),
                first_purchase_at=assigned + timedelta(days=1.5) if buys else None,
            )
        )
    return rows


def _crowd(count, seed, **options) -> list[Row]:
    rng = random.Random(seed)
    return [row for arm in ARMS for row in _players(arm, count, rng, **options)]


def _report_of(raw_spec, rows, **changes) -> dict:
    spec = results_spec(raw_spec, **changes)
    data = build_data(rows, experiment_id="e1", exported_at=at(45))
    context = ResultsContext.of(spec, data)
    review = review_context(context)
    return results_report(
        review,
        context,
        file_hashes=FILES,
        as_of_source="command line",
        sensitivity=origin_sensitivity(spec, data, review),
    )


def _plan_of_28_days(**changes) -> dict:
    """The changes to the spec of a run of 28 days from the origin, which saves the long run of
    `origin_sensitivity` (it does not vary a registered origin)."""
    return {"design__planned_duration_days": 28, "design__start_utc": START, **changes}


def _clear(raw_spec) -> dict:
    return _report_of(raw_spec, _crowd(5_000, 11), **_plan_of_28_days())


def _warnings_only(raw_spec) -> dict:
    rng = random.Random(13)
    rows = []
    for row in _crowd(5_000, 11):
        if rng.random() < 0.04:  # exposed a day after the first purchase, in every arm alike
            row = replace(
                row,
                exposed_at=row.assigned_at + timedelta(days=2),
                purchases=1,
                first_purchase_at=row.assigned_at + timedelta(days=1),
            )
        if row.arm == "variant_b" and row.assigned_at >= at(18):  # a new configuration
            row = replace(row, assigned_version=2, exposure_version=2)
        rows.append(row)
    return _report_of(raw_spec, rows, **_plan_of_28_days())


def _harm_blocker(raw_spec) -> dict:
    rng = random.Random(7)
    rows = [
        replace(row, sessions=max(0, round(rng.gauss(3.0 if row.arm == "variant_b" else 4.5, 1.5))))
        for row in _crowd(5_000, 11)
    ]
    return _report_of(raw_spec, rows, **_plan_of_28_days(guardrails=[SESSIONS_GUARDRAIL]))


def _unattainable_design(raw_spec) -> dict:
    # a rate of 0.9 and a relative effect of 0.3 leave the range 0 to 1
    return _report_of(raw_spec, _crowd(300, 3, days=14.0), primary_metric__baseline=0.9)


def _short_arms(raw_spec) -> dict:
    return _report_of(raw_spec, _crowd(300, 3, days=14.0))


def _short_run(raw_spec) -> dict:
    early = [Row(f"early_{number}", "control", assigned_at=at(-3)) for number in range(4)]
    return _report_of(
        raw_spec, [*early, *_crowd(300, 3, days=5.0)], design__start_utc=START
    )  # the four before the start are left out


def _weekly_drift(raw_spec) -> dict:
    rng = random.Random(5)
    rows = []
    for week, sizes in enumerate([(100, 100, 100), (150, 75, 75), (50, 125, 125), (100, 100, 100)]):
        for arm, size in zip(ARMS, sizes, strict=True):
            rows += _players(arm, size, rng, days=7.0, first_day=7.0 * week, tag=f"_w{week}")
    return _report_of(raw_spec, rows, **_plan_of_28_days())


_BUILDERS = {
    "golden": lambda raw_spec: json.loads(GOLDEN.read_text(encoding="utf-8")),
    "clear": _clear,
    "warnings_only": _warnings_only,
    "harm_blocker": _harm_blocker,
    "unattainable_design": _unattainable_design,
    "short_arms": _short_arms,
    "short_run": _short_run,
    "weekly_drift": _weekly_drift,
}
_BUILT: dict[tuple[str, str], dict] = {}


def report(name: str, raw_spec: dict) -> dict:
    """A copy of the report `name`, built from `raw_spec` the first time that pair is asked for."""
    key = (name, hashlib.sha256(json.dumps(raw_spec, sort_keys=True).encode()).hexdigest())
    if key not in _BUILT:
        _BUILT[key] = _BUILDERS[name](raw_spec)
    return copy.deepcopy(_BUILT[key])
