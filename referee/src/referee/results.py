"""What the results rules look at: one export, read against the spec it belongs to.

`ResultsContext.of(spec, data)` joins the three tables into one record per player, decides
which players are analysed, and fixes the origin from which weeks are counted. It refuses an
export that cannot be reviewed against the spec (an arm the spec does not list, a metric the
export does not hold) and says everything wrong at once. Rules read the context and never
change it. The decisions are those of design section 21.3 and 21.8.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from referee.data import Assignment, ExperimentData, Exposure, Outcome
from referee.methods import StatsError, two_proportion_difference, welch_difference
from referee.power import PowerError, PowerPlan, plan_power, power_alpha_adjustment
from referee.spec import ExperimentSpec

DAYS_PER_BLOCK = 7
_ESTIMATE_DIGITS = 6


class ResultsError(ValueError):
    """The export cannot be reviewed against this spec. Carries every problem found."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        noun = "problem" if len(self.problems) == 1 else "problems"
        header = f"the export cannot be reviewed against the spec: {len(self.problems)} {noun}"
        super().__init__("\n".join([header, *(f"  - {problem}" for problem in self.problems)]))


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    """One assigned player: arm, first exposure and outcome, joined."""

    player_id: str
    arm: str
    assigned_at: datetime
    assigned_version: int
    first_exposed_at: datetime | None
    first_exposure_version: int | None
    sessions_7d: int
    purchases_7d: int
    revenue_usd_7d: float
    first_purchase_at: datetime | None
    window_end: datetime | None

    @property
    def exposed(self) -> bool:
        return self.first_exposed_at is not None

    @property
    def version(self) -> int:
        """The configuration version the player first saw: the exposure's, else the assignment's."""
        if self.first_exposure_version is None:
            return self.assigned_version
        return self.first_exposure_version

    @property
    def late_exposed(self) -> bool:
        """First exposed after the first purchase (an exposure at that instant is not late)."""
        return (
            self.first_exposed_at is not None
            and self.first_purchase_at is not None
            and self.first_exposed_at > self.first_purchase_at
        )


@dataclass(frozen=True, slots=True)
class ExportMetric:
    """A player-level metric the export holds, by the name a spec gives it."""

    name: str
    kind: Literal["binary", "continuous"]
    value: Callable[[PlayerRecord], float]


METRICS: Mapping[str, ExportMetric] = {
    metric.name: metric
    for metric in (
        ExportMetric("sessions_7d", "continuous", lambda p: float(p.sessions_7d)),
        ExportMetric("purchases_7d", "continuous", lambda p: float(p.purchases_7d)),
        ExportMetric("revenue_usd_7d", "continuous", lambda p: p.revenue_usd_7d),
        ExportMetric("purchased_7d", "binary", lambda p: 1.0 if p.purchases_7d > 0 else 0.0),
    )
}


@dataclass(frozen=True, kw_only=True)
class ResultsContext:
    """Everything a results rule may read.

    `players` are the assigned players at or after `origin`, in player order. Players assigned
    before `design.start_utc` are left out of every count and listed in `ignored_before_start`.
    The power plan is worked out as the design review does, and exactly one of `plan` and
    `power_error` is set.
    """

    spec: ExperimentSpec
    plan: PowerPlan | None
    power_error: str | None
    experiment_id: str
    exported_at: datetime | None
    origin: datetime
    players: tuple[PlayerRecord, ...]
    ignored_before_start: tuple[str, ...]
    metrics: Mapping[str, ExportMetric]

    @classmethod
    def of(cls, spec: ExperimentSpec, data: ExperimentData) -> ResultsContext:
        problems: list[str] = []
        listed = {arm.name for arm in spec.arms}
        unknown = sorted({a.arm for a in data.assignments} - listed)
        if unknown:
            problems.append(
                f"the export has arms the spec does not list: {unknown} "
                f"(the spec's arms: {[arm.name for arm in spec.arms]})"
            )
        metrics = _metrics_of(spec, problems)

        if not data.assignments:
            problems.append("the export has no assignments")
        start = (
            None if spec.design.start_utc is None else datetime.fromisoformat(spec.design.start_utc)
        )
        first_assignment = min((a.assigned_at for a in data.assignments), default=None)
        origin = start if start is not None else first_assignment
        kept = (
            [a for a in data.assignments if origin is not None and a.assigned_at >= origin]
            if data.assignments
            else []
        )
        if data.assignments and not kept:
            problems.append("no player was assigned at or after design.start_utc")

        outcome = {o.player_id: o for o in data.outcomes}
        lacking = [a.player_id for a in kept if a.player_id not in outcome]
        if lacking:
            problems.append(
                f"{len(lacking)} assigned players have no outcome row (first: {lacking[0]!r})"
            )
        if problems or origin is None:
            raise ResultsError(problems)

        first_exposure = {}
        for exposure in data.exposures:  # in player order, and each player's by time
            first_exposure.setdefault(exposure.player_id, exposure)
        players = tuple(
            _record(a, first_exposure.get(a.player_id), outcome[a.player_id])
            for a in sorted(kept, key=lambda a: a.player_id)
        )
        try:
            plan, power_error = (
                plan_power(spec, alpha_adjustment=power_alpha_adjustment(spec)),
                None,
            )
        except PowerError as error:
            plan, power_error = None, str(error)
        return cls(
            spec=spec,
            plan=plan,
            power_error=power_error,
            experiment_id=data.experiment_id,
            exported_at=data.exported_at,
            origin=origin,
            players=players,
            ignored_before_start=tuple(
                sorted(a.player_id for a in data.assignments if a.assigned_at < origin)
            ),
            metrics=metrics,
        )

    @property
    def arm_names(self) -> tuple[str, ...]:
        return tuple(arm.name for arm in self.spec.arms)

    @property
    def control(self) -> str:
        return next(arm.name for arm in self.spec.arms if arm.is_control)

    @property
    def analysed(self) -> tuple[PlayerRecord, ...]:
        """Assigned, exposed, and not first exposed after the first purchase (section 21.3)."""
        return tuple(p for p in self.players if p.exposed and not p.late_exposed)

    def count_by_arm(self, players: Iterable[PlayerRecord]) -> dict[str, int]:
        """Players per arm, in the spec's order, with 0 for an arm nobody is in."""
        counted = Counter(p.arm for p in players)
        return {name: counted[name] for name in self.arm_names}

    def week_of(self, moment: datetime) -> int:
        """The 7-day block of `moment`, counted from the origin (negative before it)."""
        return (moment - self.origin) // timedelta(days=DAYS_PER_BLOCK)

    def required_n(self, arm: str) -> int | None:
        """The arm's required sample size from the power plan, found by name."""
        if self.plan is None:
            return None
        return dict(self.plan.required_per_arm).get(arm)


def effect_estimate(
    context: ResultsContext, arm: str, players: Iterable[PlayerRecord]
) -> dict[str, Any]:
    """The primary metric's difference for `arm` against control among `players`.

    Welch's interval for a continuous metric, the two-proportion interval for a binary one,
    both at 95% and unadjusted for the number of arms or looks: a description of the
    estimate, not a test. When the data allow no estimate (a group too small, or no variation)
    the answer carries the reason in "error" in place of the numbers.
    """
    metric = context.metrics[context.spec.primary_metric.name]
    chosen = list(players)
    return difference_summary(
        metric,
        [metric.value(p) for p in chosen if p.arm == arm],
        [metric.value(p) for p in chosen if p.arm == context.control],
    )


def difference_summary(
    metric: ExportMetric, treatment: Sequence[float], control: Sequence[float]
) -> dict[str, Any]:
    """mean(treatment) - mean(control) of one metric's values, with its 95% interval.

    Welch's interval for a continuous metric, the two-proportion interval for a binary one.
    The groups need not be arms: any two sets of players will do. When the data allow no
    estimate the answer carries the reason in "error" in place of the numbers.
    """
    counts = {"n_treatment": len(treatment), "n_control": len(control)}
    try:
        if metric.kind == "binary":
            found = two_proportion_difference(
                round(sum(treatment)), len(treatment), round(sum(control)), len(control)
            )
        else:
            found = welch_difference(treatment, control)
    except StatsError as error:
        return {**counts, "error": str(error)}
    return {
        **counts,
        "difference": round(found.difference, _ESTIMATE_DIGITS),
        "ci_low": round(found.ci_low, _ESTIMATE_DIGITS),
        "ci_high": round(found.ci_high, _ESTIMATE_DIGITS),
        "confidence": found.confidence,
    }


def _record(assignment: Assignment, exposure: Exposure | None, outcome: Outcome) -> PlayerRecord:
    return PlayerRecord(
        player_id=assignment.player_id,
        arm=assignment.arm,
        assigned_at=assignment.assigned_at,
        assigned_version=assignment.config_version,
        first_exposed_at=None if exposure is None else exposure.exposed_at,
        first_exposure_version=None if exposure is None else exposure.config_version,
        sessions_7d=outcome.sessions_7d,
        purchases_7d=outcome.purchases_7d,
        revenue_usd_7d=outcome.revenue_usd_7d,
        first_purchase_at=outcome.first_purchase_at,
        window_end=outcome.window_end,
    )


def _metrics_of(spec: ExperimentSpec, problems: list[str]) -> dict[str, ExportMetric]:
    """The export metrics for the spec's primary metric and guardrails, or why not."""
    found: dict[str, ExportMetric] = {}
    named = [("primary_metric", spec.primary_metric)]
    named += [(f"guardrails[{i}]", g) for i, g in enumerate(spec.guardrails)]
    for where, metric in named:
        export_metric = METRICS.get(metric.name)
        if export_metric is None:
            problems.append(
                f"{where}.name: {metric.name!r} is not a metric the export holds; "
                f"the registry has: {', '.join(METRICS)}"
            )
        elif metric.kind != export_metric.kind:
            problems.append(
                f"{where}.kind: {metric.name!r} is {metric.kind} in the spec but "
                f"{export_metric.kind} in the export"
            )
        else:
            found[metric.name] = export_metric
    return found
