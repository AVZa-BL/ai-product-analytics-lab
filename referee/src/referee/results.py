"""What the results rules look at: one export, read against the spec it belongs to.

`ResultsContext.of(spec, data)` joins the three tables into one record per player, decides
which players are analysed, and fixes the origin from which weeks are counted. It refuses an
export that cannot be reviewed against the spec (an arm the spec does not list, a metric the
export does not hold) and says everything wrong at once. Rules read the context and never
change it. The decisions are those of design section 21.3 and 21.8.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from referee.data import Assignment, ExperimentData, Exposure, Outcome, exposure_time_key
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
        self.header = f"the export cannot be reviewed against the spec: {len(self.problems)} {noun}"
        super().__init__("\n".join([self.header, *(f"  - {problem}" for problem in self.problems)]))


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
    first_seen_at: datetime | None = None  # None when the export has no such column

    @property
    def exposed(self) -> bool:
        return self.first_exposed_at is not None

    @property
    def window_closes_at(self) -> datetime:
        """When the player's seven-day outcome window closes: the export's `window_end_utc`,
        else seven days after the assignment (the length the lab's export uses). An assignment
        in the last days of the calendar has a window that closes after any instant that exists."""
        if self.window_end is not None:
            return self.window_end
        try:
            return self.assigned_at + timedelta(days=DAYS_PER_BLOCK)
        except OverflowError:
            return datetime.max.replace(tzinfo=self.assigned_at.tzinfo)

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


def _as_float(count: int) -> float:
    """A count as a float; one beyond any float is infinite, which the statistics refuse."""
    try:
        return float(count)
    except OverflowError:
        return math.inf


# Module-level functions, not lambdas, so that a context can be pickled.
def _sessions(player: PlayerRecord) -> float:
    return _as_float(player.sessions_7d)


def _purchases(player: PlayerRecord) -> float:
    return _as_float(player.purchases_7d)


def _revenue(player: PlayerRecord) -> float:
    return player.revenue_usd_7d


def _purchased(player: PlayerRecord) -> float:
    return 1.0 if player.purchases_7d > 0 else 0.0


METRICS: Mapping[str, ExportMetric] = {
    metric.name: metric
    for metric in (
        ExportMetric("sessions_7d", "continuous", _sessions),
        ExportMetric("purchases_7d", "continuous", _purchases),
        ExportMetric("revenue_usd_7d", "continuous", _revenue),
        ExportMetric("purchased_7d", "binary", _purchased),
    )
}


MetricFamily = Literal["revenue_like", "count", "binary"]

# What kind of values each export metric holds, which decides what Referee has simulated for it.
# `revenue_like`: an amount of money that most players leave at zero (the family of the pooled-
# effect study, design section 21.10); `count`: a whole number of events per player (not
# simulated for the pooled effect); `binary`: 0 or 1.
METRIC_FAMILIES: Mapping[str, MetricFamily] = {
    "sessions_7d": "count",
    "purchases_7d": "count",
    "revenue_usd_7d": "revenue_like",
    "purchased_7d": "binary",
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
    analysed: tuple[PlayerRecord, ...] = field(init=False)
    """Assigned, exposed, and not first exposed after the first purchase (section 21.3)."""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "analysed", tuple(p for p in self.players if p.exposed and not p.late_exposed)
        )

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

        for table, ids in (
            ("assignments", [a.player_id for a in data.assignments]),
            ("outcomes", [o.player_id for o in data.outcomes]),
        ):
            repeated = sorted(player for player, n in Counter(ids).items() if n > 1)
            if repeated:
                problems.append(
                    f"{len(repeated)} players appear more than once in the {table} "
                    f"(first: {repeated[0]!r})"
                )
        outcome = {o.player_id: o for o in data.outcomes}
        lacking = [a.player_id for a in kept if a.player_id not in outcome]
        if lacking:
            problems.append(
                f"{len(lacking)} assigned players have no outcome row (first: {lacking[0]!r})"
            )
        if problems or origin is None:
            raise ResultsError(problems)

        first_exposure: dict[str, Exposure] = {}
        for exposure in data.exposures:  # whatever the order: the earliest wins
            held = first_exposure.get(exposure.player_id)
            if held is None or exposure_time_key(exposure) < exposure_time_key(held):
                first_exposure[exposure.player_id] = exposure
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

    def count_by_arm(self, players: Iterable[PlayerRecord]) -> dict[str, int]:
        """Players per arm, in the spec's order, with 0 for an arm nobody is in."""
        counted = Counter(p.arm for p in players)
        return {name: counted[name] for name in self.arm_names}

    @property
    def observed_days(self) -> int:
        """Whole days, rounded up, from the first to the last assignment of `players`."""
        assigned = [player.assigned_at for player in self.players]
        return math.ceil((max(assigned) - min(assigned)) / timedelta(days=1))

    def week_of(self, moment: datetime) -> int:
        """The 7-day block of `moment`, counted from the origin (negative before it)."""
        return self.block_of(moment, DAYS_PER_BLOCK)

    def block_of(self, moment: datetime, block_days: int) -> int:
        """The block of `block_days` days that `moment` falls in, counted from the origin."""
        return (moment - self.origin) // timedelta(days=block_days)

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
    return effect_estimates(context, players, arms=(arm,))[arm]


def effect_estimates(
    context: ResultsContext, players: Iterable[PlayerRecord], *, arms: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    """`effect_estimate` for each of `arms` (every arm but the control by default).

    The players are grouped once, so the cost does not grow with the number of arms.
    """
    metric = context.metrics[context.spec.primary_metric.name]
    values: dict[str, list[float]] = {name: [] for name in context.arm_names}
    for player in players:
        values[player.arm].append(metric.value(player))
    wanted = [name for name in context.arm_names if name != context.control]
    return {
        arm: difference_summary(metric, values[arm], values[context.control])
        for arm in (wanted if arms is None else arms)
    }


def window_is_open(player: PlayerRecord, as_of: datetime | None) -> bool:
    """Whether the player's seven-day outcome window closes after `as_of`, the time of the export.

    A window that closes exactly at `as_of` is complete (as in `referee.cohorts`). With no time
    for the export nothing can be told, and no window is taken to be open.
    """
    return as_of is not None and player.window_closes_at > as_of


def effect_table(context: ResultsContext) -> dict[str, Any]:
    """The primary metric's difference against control for every other arm (design section 22.3).

    It is read among the analysed players (section 21.3) whose outcome window had closed at the
    time of the export, as RES-004 does: a window still open holds a part of the seven days, and
    the players left out are counted in `left_out`. Each arm's mean, the difference with its
    95% interval and its two-sided p value (Welch's test for a continuous metric, the pooled
    two-proportion z test for a binary one, whatever `design.sided` and `design.alpha` say),
    the difference relative to control's mean when that is above 0, and the p value adjusted
    for the number of arms compared with control. The adjustment is the one the power plan
    uses: Bonferroni, unless the spec registers none (`dunnett` is planned as Bonferroni, which
    is the more conservative). It adjusts for the arms only, not for the guardrails, other
    metrics or repeated looks. An arm whose data allow no estimate carries the reason in
    `error` and still counts as a comparison. The table describes the sample; it is not a test
    of the effect, and the review's verdict is what says whether the sample can be read.
    """
    spec = context.spec
    metric = context.metrics[spec.primary_metric.name]
    values: dict[str, list[float]] = {name: [] for name in context.arm_names}
    left_out = dict.fromkeys(context.arm_names, 0)
    for player in context.analysed:
        if window_is_open(player, context.exported_at):
            left_out[player.arm] += 1
        else:
            values[player.arm].append(metric.value(player))
    adjustment = power_alpha_adjustment(spec)
    arms = [name for name in context.arm_names if name != context.control]
    control = values[context.control]
    rows = []
    for arm in arms:
        row: dict[str, Any] = {
            "arm": arm,
            "n_treatment": len(values[arm]),
            "n_control": len(control),
        }
        try:
            found = _compare(metric, values[arm], control)
        except StatsError as error:
            rows.append({**row, "error": str(error)})
            continue
        mean_treatment, mean_control = found.mean_treatment, found.mean_control
        adjusted = min(1.0, found.p_value * len(arms)) if adjustment == "bonferroni" else None
        relative = found.difference / mean_control if mean_control > 0 else None
        rows.append(
            {
                **row,
                "mean_treatment": _shown(mean_treatment),
                "mean_control": _shown(mean_control),
                "difference": _shown(found.difference),
                "ci_low": _shown(found.ci_low),
                "ci_high": _shown(found.ci_high),
                "confidence": found.confidence,
                "relative_difference": (
                    _shown(relative) if relative is not None and math.isfinite(relative) else None
                ),
                "p_value": found.p_value,
                "adjusted_p_value": found.p_value if adjusted is None else adjusted,
            }
        )
    return {
        "metric": metric.name,
        "kind": metric.kind,
        "population": (
            "analysed players with a closed outcome window"
            if context.exported_at is not None
            else "analysed players (the export has no time, so no outcome window was checked)"
        ),
        "left_out": left_out,
        "adjustment": adjustment,
        "comparisons": len(arms),
        "arms": rows,
    }


def _shown(value: float) -> float:
    """`value` rounded for a report, and never a negative zero."""
    return round(value, _ESTIMATE_DIGITS) + 0.0


@dataclass(frozen=True, slots=True)
class _Compared:
    """What `effect_table` reads of a comparison, whichever test made it."""

    mean_treatment: float
    mean_control: float
    difference: float
    ci_low: float
    ci_high: float
    confidence: float
    p_value: float


def _compare(
    metric: ExportMetric, treatment: Sequence[float], control: Sequence[float]
) -> _Compared:
    """Treatment against control for one metric, or `StatsError` saying why not."""
    if not treatment or not control:
        empty = [
            name for name, group in (("treatment", treatment), ("control", control)) if not group
        ]
        said = (
            "the treatment and control groups have"
            if len(empty) == 2
            else f"the {empty[0]} group has"
        )
        raise StatsError(f"{said} no players")
    if metric.kind == "binary":
        rates = two_proportion_difference(
            round(sum(treatment)), len(treatment), round(sum(control)), len(control)
        )
        return _Compared(
            rates.rate_treatment,
            rates.rate_control,
            rates.difference,
            rates.ci_low,
            rates.ci_high,
            rates.confidence,
            rates.p_value,
        )
    means = welch_difference(treatment, control)
    return _Compared(
        means.mean_treatment,
        means.mean_control,
        means.difference,
        means.ci_low,
        means.ci_high,
        means.confidence,
        means.p_value,
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
        found = _compare(metric, treatment, control)
    except StatsError as error:
        return {**counts, "error": str(error)}
    return {
        **counts,
        "difference": _shown(found.difference),
        "ci_low": _shown(found.ci_low),
        "ci_high": _shown(found.ci_high),
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
        first_seen_at=assignment.first_seen_at,
    )


_KINDS_OBSERVED = {"existing_users": "existing users", "new_users": "new users"}


def first_seen_summary(context: ResultsContext) -> dict[str, Any] | None:
    """How long the assigned players had existed, from the export's `first_seen_at_utc`.

    None when the column is absent (the loader reads it for every row or for none). A player
    first seen before the origin is an existing user and one first seen at or after it a new
    user, and the population's kind, `observed`, is the kind of more than half of its players;
    at exactly half there is no such kind, so `observed` is None. `agrees` says whether the
    spec's `population.kind` is consistent with it: a declared `mixed` is consistent with any
    kind, and an undeclared kind, or no kind observed, leaves it None. Judgement: the origin is
    the one instant the review has for when the experiment began, so it is the line between
    existing and new; the majority decides because without a registered start the origin is
    the first assignment, and a player first seen minutes before it must not turn a population
    of new users into a mixed one; an exact tie is neither, and is not called either. The ages
    are the days from first seen to assignment, rounded to a tenth.
    """
    players = context.players
    if any(player.first_seen_at is None for player in players):
        return None
    before = sum(player.first_seen_at < context.origin for player in players)  # type: ignore[operator]
    ages = sorted(
        (player.assigned_at - player.first_seen_at).total_seconds() / 86_400  # type: ignore[operator]
        for player in players
    )
    observed = (
        "existing_users"
        if 2 * before > len(players)
        else "new_users"
        if 2 * before < len(players)
        else None
    )
    declared = context.spec.population.kind
    return {
        "before_origin": before,
        "from_origin": len(players) - before,
        "days_before_assignment": {
            "min": round(ages[0], 1),
            "median": round(statistics.median(ages), 1),
            "max": round(ages[-1], 1),
        },
        "observed": observed,
        "agrees": None if declared is None or observed is None else declared in ("mixed", observed),
    }


def describe_first_seen(summary: dict[str, Any] | None, declared: str | None) -> str:
    """One sentence on what `first_seen_at_utc` says of the players and whether the declared
    `population.kind` agrees, or that the column is absent and the kind is unchecked."""
    if summary is None:
        said = "not declared" if declared is None else f"declared as {declared}"
        return (
            f"population.kind is {said}; the export has no first_seen_at_utc column, so the "
            "kind of players is unchecked."
        )
    total = summary["before_origin"] + summary["from_origin"]
    ages = summary["days_before_assignment"]
    kind = None if summary["observed"] is None else _KINDS_OBSERVED[summary["observed"]]
    greater = (
        "exactly half each, so neither kind is the greater number"
        if kind is None
        else f"so by the greater number they are {kind}"
    )
    facts = (
        f"By first_seen_at_utc, {summary['before_origin']:,} of the {total:,} assigned players "
        f"were first seen before the origin and {summary['from_origin']:,} at or after it "
        f"(existing before the origin, new from it), {greater}; "
        f"at assignment they had existed for {ages['min']:g} to {ages['max']:g} days "
        f"(median {ages['median']:g})."
    )
    if declared is None:
        return f"{facts} population.kind is not declared."
    if kind is None:
        return (
            f"{facts} population.kind is declared as {declared}, and the column neither "
            "confirms nor contradicts it."
        )
    if declared == "mixed" and 0 in (summary["before_origin"], summary["from_origin"]):
        return (  # it agrees with any kind (23.2), but a column of one kind confirms nothing
            f"{facts} population.kind is declared as mixed, and the column shows only {kind}: "
            "that does not contradict a mixed population, and does not confirm one."
        )
    if summary["agrees"]:
        return f"{facts} population.kind is declared as {declared}, and the column agrees."
    return f"{facts} population.kind is declared as {declared}, but the column says {kind}."


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
