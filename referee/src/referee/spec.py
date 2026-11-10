"""Typed, validated experiment specification for Referee.

A spec is the pre-registered description of an A/B/n test. This module answers one
question: is the spec well-formed? Whether the experiment is well designed is a separate
question for the review rules, which read a valid spec and never repair an invalid one.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from referee.display import for_line
from referee.schema import (
    COLUMN_PATTERN,
    ID_PATTERN,
    Node,
    SpecError,
    canonical_json,
    drop_unset,
    fingerprint,
    show,
)

SPEC_VERSION = 1
ALLOCATION_TOLERANCE = 1e-9

RandomizationUnit = Literal["player", "user", "device", "session", "cluster"]
Direction = Literal["increase", "decrease", "two_sided"]
MetricKind = Literal["binary", "continuous", "ratio"]
MetricFamily = Literal["revenue_like", "count", "binary", "other"]
HarmfulDirection = Literal["increase", "decrease"]
Sidedness = Literal["two_sided", "one_sided"]
ExposureTiming = Literal["pre_treatment", "post_treatment"]
Interference = Literal["none_expected", "possible"]
PopulationKind = Literal["new_users", "existing_users", "mixed"]
AlphaCorrection = Literal["none", "bonferroni", "dunnett"]
StoppingRule = Literal["fixed_horizon", "sequential"]
SrmCadence = Literal["daily", "weekly", "none"]

# SpecError is defined in referee.schema; the CLI and the tests import it from here, as before.

# Columns of the outcomes file that mean something to the loader and cannot hold a metric.
RESERVED_COLUMNS = frozenset(
    {"experiment_id", "player_id", "first_purchase_at_utc", "window_end_utc"}
)


@dataclass(frozen=True, kw_only=True)
class Hypothesis:
    null: str
    alternative: str
    direction: Direction


@dataclass(frozen=True, kw_only=True)
class Population:
    randomization_unit: RandomizationUnit
    analysis_unit: RandomizationUnit
    eligibility: str
    daily_eligible_units: int
    exposure_trigger: str
    exposure_timing: ExposureTiming | None
    interference: Interference | None
    kind: PopulationKind | None


@dataclass(frozen=True, kw_only=True)
class Arm:
    name: str
    allocation: float
    is_control: bool


@dataclass(frozen=True, kw_only=True)
class Metric:
    """A metric the spec declares. `column` is the column of the outcomes file that holds one
    value for each player (default: the metric's name); `family` says what the values look like
    (default: from the kind), and decides which simulated error rates Referee may quote."""

    name: str
    kind: MetricKind
    baseline: float
    baseline_std: float | None
    column: str | None = None
    family: MetricFamily | None = None


@dataclass(frozen=True, kw_only=True)
class SecondaryMetric:
    """A metric the analyst wants watched that is neither the primary metric nor a guardrail:
    it has no baseline and no tolerance, and is read for its effect only."""

    name: str
    kind: MetricKind
    column: str | None = None
    family: MetricFamily | None = None


@dataclass(frozen=True, kw_only=True)
class PrimaryMetric(Metric):
    governed_reference: str | None


@dataclass(frozen=True, kw_only=True)
class Guardrail(Metric):
    harmful_direction: HarmfulDirection
    tolerance_relative: float


@dataclass(frozen=True, kw_only=True)
class Design:
    mde_relative: float
    alpha: float
    power: float
    sided: Sidedness
    planned_duration_days: int
    min_duration_days: int
    alpha_adjustment: AlphaCorrection | None
    pre_period_covariate: str | None
    start_utc: str | None


@dataclass(frozen=True, kw_only=True)
class Procedure:
    """How the test will be run. Every field is optional; an absent one is what a rule reads."""

    stopping_rule: StoppingRule | None
    srm_check_cadence: SrmCadence | None
    bucketing_salt: str | None


@dataclass(frozen=True, kw_only=True)
class ExperimentSpec:
    """A validated experiment spec. Build it with `from_dict`, never by hand.

    Direct construction skips validation: the dataclasses are plain, immutable data.
    """

    referee_spec_version: int
    id: str
    title: str
    owner: str
    hypothesis: Hypothesis
    population: Population
    arms: tuple[Arm, ...]
    primary_metric: PrimaryMetric
    guardrails: tuple[Guardrail, ...]
    design: Design
    procedure: Procedure
    secondary_metrics: tuple[SecondaryMetric, ...] | None = None  # None: none declared

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExperimentSpec:
        """Validate `data` and return the spec, or raise SpecError listing every violation."""
        if not isinstance(data, Mapping):
            raise SpecError([f"spec: must be a mapping, got {show(data)}"])

        violations: list[str] = []
        root = Node(data, "", violations)

        version = root.integer("referee_spec_version", ge=1)
        if not root.failed("referee_spec_version") and version != SPEC_VERSION:
            root.fail(
                "referee_spec_version",
                f"unsupported version {version}; this Referee reads version {SPEC_VERSION}",
            )

        # Keyword arguments evaluate top to bottom, so violations come out in schema order.
        spec = cls(
            referee_spec_version=version,
            id=root.text("id", pattern=ID_PATTERN),
            title=root.text("title"),
            owner=root.text("owner"),
            hypothesis=_hypothesis(root.mapping("hypothesis")),
            population=_population(root.mapping("population")),
            arms=_arms(root),
            primary_metric=_primary_metric(root.mapping("primary_metric")),
            guardrails=_guardrails(root),
            design=_design(root.mapping("design")),
            procedure=_procedure(root.mapping("procedure", required=False)),
            secondary_metrics=_secondary_metrics(root),
        )
        _reject_reused_metric_names(root, spec)
        root.reject_unknown()

        if violations:
            raise SpecError(violations)
        return spec

    def to_dict(self) -> dict[str, Any]:
        """The spec as plain data that `from_dict` accepts, in schema order.

        What was not given is left out: an absent field and an explicit null read the same,
        so neither is written, and a `procedure` section with nothing in it is dropped. That
        keeps the canonical form, and with it the fingerprint, unchanged when a later schema
        version adds an optional field.
        """
        return drop_unset(asdict(self))

    def canonical_json(self) -> str:
        """One fixed text for this spec: sorted keys, no spaces, non-ASCII written as is
        (`referee.schema.canonical_json`). The order of `arms` is kept, because it is part
        of the spec."""
        return canonical_json(self.to_dict())

    def sha256(self) -> str:
        """The hex SHA-256 of the canonical JSON as UTF-8: this spec's fingerprint
        (`referee.schema.fingerprint`)."""
        return fingerprint(self.to_dict())


# --- Section parsers: each one reads like the schema it validates -------------------------


def _hypothesis(node: Node) -> Hypothesis:
    hypothesis = Hypothesis(
        null=node.text("null"),
        alternative=node.text("alternative"),
        direction=node.choice("direction", get_args(Direction)),
    )
    node.reject_unknown()
    return hypothesis


def _population(node: Node) -> Population:
    randomization_unit = node.choice("randomization_unit", get_args(RandomizationUnit))
    population = Population(
        randomization_unit=randomization_unit,
        analysis_unit=node.choice(
            "analysis_unit", get_args(RandomizationUnit), default=randomization_unit
        ),
        eligibility=node.text("eligibility"),
        daily_eligible_units=node.integer("daily_eligible_units", ge=1),
        exposure_trigger=node.text("exposure_trigger"),
        exposure_timing=node.optional_choice("exposure_timing", get_args(ExposureTiming)),
        interference=node.optional_choice("interference", get_args(Interference)),
        kind=node.optional_choice("kind", get_args(PopulationKind)),
    )
    node.reject_unknown()
    return population


def _arms(root: Node) -> tuple[Arm, ...]:
    nodes = root.sequence("arms")
    arms = tuple(_arm(node) for node in nodes)
    if root.failed("arms"):
        return arms

    if len(arms) < 2:
        root.fail("arms", f"at least two arms are required, got {len(arms)}")
    _reject_duplicate_names(root, "arms", nodes, arms)
    if not any(node.failed("is_control") for node in nodes):
        controls = sum(arm.is_control for arm in arms)
        if controls != 1:
            root.fail("arms", f"exactly one arm must set is_control: true, found {controls}")
    if not any(node.failed("allocation") for node in nodes):
        total = math.fsum(arm.allocation for arm in arms)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=ALLOCATION_TOLERANCE):
            root.fail(
                "arms",
                f"allocations must sum to 1 (within {ALLOCATION_TOLERANCE:g}), got {total:.12g}",
            )
    return arms


def _arm(node: Node) -> Arm:
    arm = Arm(
        name=node.text("name"),
        allocation=node.number("allocation", gt=0),
        is_control=node.boolean("is_control", default=False),
    )
    node.reject_unknown()
    return arm


def _read_metric(node: Node) -> Metric:
    """Read the fields primary metrics and guardrails share, with their kind-specific rules."""
    kind = node.choice("kind", get_args(MetricKind))
    metric = Metric(
        name=node.text("name"),
        kind=kind,
        baseline=node.number("baseline"),
        baseline_std=node.optional_number("baseline_std"),
        column=_column(node),
        family=node.optional_choice("family", get_args(MetricFamily)),
    )
    if node.failed("kind"):
        return metric

    if kind == "binary":
        if not node.failed("baseline") and not 0 < metric.baseline < 1:
            node.fail(
                "baseline",
                f"must be a rate with 0 < baseline < 1 for a binary metric, "
                f"got {metric.baseline:g}",
            )
        if metric.baseline_std is not None:
            node.fail(
                "baseline_std", "must be null for a binary metric (its variance follows the rate)"
            )
    elif metric.baseline_std is None:
        if not node.failed("baseline_std"):
            node.fail("baseline_std", f"is required, and must be > 0, for a {kind} metric")
    elif metric.baseline_std <= 0:
        node.fail("baseline_std", f"must be > 0, got {metric.baseline_std:g}")
    return metric


def _primary_metric(node: Node) -> PrimaryMetric:
    metric = _read_metric(node)
    primary = PrimaryMetric(
        name=metric.name,
        kind=metric.kind,
        baseline=metric.baseline,
        baseline_std=metric.baseline_std,
        column=metric.column,
        family=metric.family,
        governed_reference=node.optional_text("governed_reference"),
    )
    node.reject_unknown()
    return primary


def _guardrails(root: Node) -> tuple[Guardrail, ...]:
    nodes = root.sequence("guardrails", required=False)
    guardrails = tuple(_guardrail(node) for node in nodes)
    _reject_duplicate_names(root, "guardrails", nodes, guardrails)
    return guardrails


def _guardrail(node: Node) -> Guardrail:
    metric = _read_metric(node)
    guardrail = Guardrail(
        name=metric.name,
        kind=metric.kind,
        baseline=metric.baseline,
        baseline_std=metric.baseline_std,
        column=metric.column,
        family=metric.family,
        harmful_direction=node.choice("harmful_direction", get_args(HarmfulDirection)),
        tolerance_relative=node.number("tolerance_relative", gt=0),
    )
    node.reject_unknown()
    return guardrail


def _design(node: Node) -> Design:
    design = Design(
        mde_relative=node.number("mde_relative", gt=0),
        alpha=node.number("alpha", gt=0, lt=1),
        power=node.number("power", gt=0, lt=1),
        sided=node.choice("sided", get_args(Sidedness)),
        planned_duration_days=node.integer("planned_duration_days", ge=1),
        min_duration_days=node.integer("min_duration_days", ge=1),
        alpha_adjustment=node.optional_choice("alpha_adjustment", get_args(AlphaCorrection)),
        pre_period_covariate=node.optional_text("pre_period_covariate"),
        start_utc=node.optional_utc_timestamp("start_utc"),
    )
    if (
        not node.failed("planned_duration_days", "min_duration_days")
        and design.min_duration_days > design.planned_duration_days
    ):
        node.fail(
            "min_duration_days",
            f"must be <= planned_duration_days ({design.planned_duration_days}), "
            f"got {design.min_duration_days}",
        )
    node.reject_unknown()
    return design


def _procedure(node: Node) -> Procedure:
    procedure = Procedure(
        stopping_rule=node.optional_choice("stopping_rule", get_args(StoppingRule)),
        srm_check_cadence=node.optional_choice("srm_check_cadence", get_args(SrmCadence)),
        bucketing_salt=node.optional_text("bucketing_salt"),
    )
    node.reject_unknown()
    return procedure


def _column(node: Node) -> str | None:
    """The optional `column` of a metric: a name the outcomes file can hold, not a reserved one."""
    column = node.optional_text("column")
    if column is None:
        return None
    if not COLUMN_PATTERN.match(column):
        node.fail(
            "column", f"must be a column name (letters, digits and underscores), got {column!r}"
        )
    elif column in RESERVED_COLUMNS:
        node.fail("column", f"{column!r} is a column the loader reads for another purpose")
    return column


def _secondary_metrics(root: Node) -> tuple[SecondaryMetric, ...] | None:
    nodes = root.sequence("secondary_metrics", required=False)
    if not nodes:
        return None
    metrics = tuple(_secondary_metric(node) for node in nodes)
    _reject_duplicate_names(root, "secondary_metrics", nodes, metrics)
    return metrics


def _secondary_metric(node: Node) -> SecondaryMetric:
    metric = SecondaryMetric(
        name=node.text("name"),
        kind=node.choice("kind", get_args(MetricKind)),
        column=_column(node),
        family=node.optional_choice("family", get_args(MetricFamily)),
    )
    node.reject_unknown()
    return metric


def _reject_reused_metric_names(root: Node, spec: ExperimentSpec) -> None:
    """A metric is declared once: a secondary metric may not repeat the primary metric's name
    or a guardrail's."""
    taken = {spec.primary_metric.name, *(g.name for g in spec.guardrails)}
    for metric in spec.secondary_metrics or ():
        if metric.name in taken:
            root.fail(
                "secondary_metrics",
                f"{metric.name!r} is already the primary metric or a guardrail",
            )


def _reject_duplicate_names(
    root: Node,
    key: str,
    nodes: Sequence[Node],
    items: Sequence[Arm | Guardrail | SecondaryMetric],
) -> None:
    """Names must differ, and must still differ as a report writes them: the text and memo
    reports key a table by the written form (`for_line`), and the JSON report is ASCII, which
    writes a character outside the basic plane as the same two escapes as its two surrogates.
    Names written the same would be one entry."""
    names = [item.name for node, item in zip(nodes, items, strict=True) if not node.failed("name")]
    for name, count in Counter(names).items():
        if count > 1:
            root.fail(key, f"duplicate name {name!r} (used {count} times)")
    for write in (for_line, json.dumps):
        written: dict[str, list[str]] = {}
        for name in dict.fromkeys(names):
            written.setdefault(write(name), []).append(name)
        for text, group in written.items():
            if len(group) > 1:
                listed = ", ".join(map(repr, group))
                root.fail(key, f"names {listed} are written the same in a report, as {text}")

