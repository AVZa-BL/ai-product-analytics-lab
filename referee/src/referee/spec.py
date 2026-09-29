"""Typed, validated experiment specification for Referee.

A spec is the pre-registered description of an A/B/n test. This module answers one
question: is the spec well-formed? Whether the experiment is well designed is a separate
question for the review rules, which read a valid spec and never repair an invalid one.
"""

from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

SPEC_VERSION = 1
ALLOCATION_TOLERANCE = 1e-9

RandomizationUnit = Literal["player", "user", "device", "session", "cluster"]
Direction = Literal["increase", "decrease", "two_sided"]
MetricKind = Literal["binary", "continuous", "ratio"]
HarmfulDirection = Literal["increase", "decrease"]
Sidedness = Literal["two_sided", "one_sided"]

_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


class SpecError(ValueError):
    """The spec is malformed. Carries every violation found, not just the first."""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(violations)
        super().__init__(self.violations)

    def __str__(self) -> str:
        noun = "violation" if len(self.violations) == 1 else "violations"
        header = f"invalid experiment spec: {len(self.violations)} {noun}"
        return "\n".join([header, *(f"  - {violation}" for violation in self.violations)])


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


@dataclass(frozen=True, kw_only=True)
class Arm:
    name: str
    allocation: float
    is_control: bool


@dataclass(frozen=True, kw_only=True)
class Metric:
    name: str
    kind: MetricKind
    baseline: float
    baseline_std: float | None


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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExperimentSpec:
        """Validate `data` and return the spec, or raise SpecError listing every violation."""
        if not isinstance(data, Mapping):
            raise SpecError([f"spec: must be a mapping, got {_show(data)}"])

        violations: list[str] = []
        root = _Node(data, "", violations)

        version = root.integer("referee_spec_version", ge=1)
        if not root.failed("referee_spec_version") and version != SPEC_VERSION:
            root.fail(
                "referee_spec_version",
                f"unsupported version {version}; this Referee reads version {SPEC_VERSION}",
            )

        # Keyword arguments evaluate top to bottom, so violations come out in schema order.
        spec = cls(
            referee_spec_version=version,
            id=root.text("id", pattern=_ID_PATTERN),
            title=root.text("title"),
            owner=root.text("owner"),
            hypothesis=_hypothesis(root.mapping("hypothesis")),
            population=_population(root.mapping("population")),
            arms=_arms(root),
            primary_metric=_primary_metric(root.mapping("primary_metric")),
            guardrails=_guardrails(root),
            design=_design(root.mapping("design")),
        )
        root.reject_unknown()

        if violations:
            raise SpecError(violations)
        return spec


# --- Section parsers: each one reads like the schema it validates -------------------------


def _hypothesis(node: _Node) -> Hypothesis:
    hypothesis = Hypothesis(
        null=node.text("null"),
        alternative=node.text("alternative"),
        direction=node.choice("direction", get_args(Direction)),
    )
    node.reject_unknown()
    return hypothesis


def _population(node: _Node) -> Population:
    randomization_unit = node.choice("randomization_unit", get_args(RandomizationUnit))
    population = Population(
        randomization_unit=randomization_unit,
        analysis_unit=node.choice(
            "analysis_unit", get_args(RandomizationUnit), default=randomization_unit
        ),
        eligibility=node.text("eligibility"),
        daily_eligible_units=node.integer("daily_eligible_units", ge=1),
        exposure_trigger=node.text("exposure_trigger"),
    )
    node.reject_unknown()
    return population


def _arms(root: _Node) -> tuple[Arm, ...]:
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


def _arm(node: _Node) -> Arm:
    arm = Arm(
        name=node.text("name"),
        allocation=node.number("allocation", gt=0),
        is_control=node.boolean("is_control", default=False),
    )
    node.reject_unknown()
    return arm


def _read_metric(node: _Node) -> Metric:
    """Read the fields primary metrics and guardrails share, with their kind-specific rules."""
    kind = node.choice("kind", get_args(MetricKind))
    metric = Metric(
        name=node.text("name"),
        kind=kind,
        baseline=node.number("baseline"),
        baseline_std=node.optional_number("baseline_std"),
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


def _primary_metric(node: _Node) -> PrimaryMetric:
    metric = _read_metric(node)
    primary = PrimaryMetric(
        name=metric.name,
        kind=metric.kind,
        baseline=metric.baseline,
        baseline_std=metric.baseline_std,
        governed_reference=node.optional_text("governed_reference"),
    )
    node.reject_unknown()
    return primary


def _guardrails(root: _Node) -> tuple[Guardrail, ...]:
    nodes = root.sequence("guardrails", required=False)
    guardrails = tuple(_guardrail(node) for node in nodes)
    _reject_duplicate_names(root, "guardrails", nodes, guardrails)
    return guardrails


def _guardrail(node: _Node) -> Guardrail:
    metric = _read_metric(node)
    guardrail = Guardrail(
        name=metric.name,
        kind=metric.kind,
        baseline=metric.baseline,
        baseline_std=metric.baseline_std,
        harmful_direction=node.choice("harmful_direction", get_args(HarmfulDirection)),
        tolerance_relative=node.number("tolerance_relative", gt=0),
    )
    node.reject_unknown()
    return guardrail


def _design(node: _Node) -> Design:
    design = Design(
        mde_relative=node.number("mde_relative", gt=0),
        alpha=node.number("alpha", gt=0, lt=1),
        power=node.number("power", gt=0, lt=1),
        sided=node.choice("sided", get_args(Sidedness)),
        planned_duration_days=node.integer("planned_duration_days", ge=1),
        min_duration_days=node.integer("min_duration_days", ge=1),
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


def _reject_duplicate_names(
    root: _Node, key: str, nodes: Sequence[_Node], items: Sequence[Arm | Guardrail]
) -> None:
    names = [item.name for node, item in zip(nodes, items, strict=True) if not node.failed("name")]
    for name, count in Counter(names).items():
        if count > 1:
            root.fail(key, f"duplicate name {name!r} (used {count} times)")


# --- Machinery: typed getters that record violations instead of raising -------------------

_ABSENT: Any = object()


def _show(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 40 else f"{text[:37]}..."


class _Node:
    """One mapping of the spec, read through getters that record violations.

    A getter never raises on bad input. It appends a message to the list shared by the
    whole parse and returns a placeholder of the right type, so parsing carries on and the
    author sees every problem at once. Placeholders never escape: `from_dict` raises
    before it returns anything if even one violation was recorded.

    The keys a parser asks for are the keys the schema allows, so unknown-key detection
    cannot drift out of step with the parsers.

    A node built with raw=None stands for a section that is missing or not a mapping. That
    is reported once, where it was looked up; its own fields stay silent.
    """

    def __init__(self, raw: Mapping[Any, Any] | None, path: str, violations: list[str]) -> None:
        self.path = path
        self._raw: Mapping[Any, Any] = {} if raw is None else raw
        self._silent = raw is None
        self._violations = violations
        self._seen: set[str] = set()
        self._failed: set[str] = set()

    # -- bookkeeping

    def _at(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def fail(self, key: str, problem: str) -> None:
        self._failed.add(key)
        self._violations.append(f"{self._at(key)}: {problem}")

    def failed(self, *keys: str) -> bool:
        """True if any of `keys` was missing or invalid, so a cross-field check must skip."""
        return self._silent or any(key in self._failed for key in keys)

    def _lookup(self, key: str, *, required: bool) -> Any:
        self._seen.add(key)
        if key in self._raw:
            return self._raw[key]
        if required and not self._silent:
            self.fail(key, "is required")
        return _ABSENT

    def reject_unknown(self) -> None:
        for key in self._raw:
            if key in self._seen:
                continue
            close = difflib.get_close_matches(str(key), sorted(self._seen), n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            self._violations.append(f"{self.path or 'spec'}: unknown key {key!r}{hint}")

    # -- text, choices, booleans

    def text(self, key: str, *, pattern: re.Pattern[str] | None = None) -> str:
        value = self._lookup(key, required=True)
        return "" if value is _ABSENT else self._check_text(key, value, pattern)

    def optional_text(self, key: str) -> str | None:
        value = self._lookup(key, required=False)
        return None if value is _ABSENT or value is None else self._check_text(key, value, None)

    def _check_text(self, key: str, value: Any, pattern: re.Pattern[str] | None) -> str:
        if not isinstance(value, str) or not value.strip():
            self.fail(key, f"must be a non-empty string, got {_show(value)}")
            return ""
        if pattern is not None and not pattern.fullmatch(value):
            self.fail(key, f"must match {pattern.pattern}, got {_show(value)}")
            return ""
        return value

    def choice[T](self, key: str, options: tuple[T, ...], *, default: T | None = None) -> T:
        value = self._lookup(key, required=default is None)
        if value is _ABSENT:
            return options[0] if default is None else default
        if value not in options:
            allowed = ", ".join(str(option) for option in options)
            self.fail(key, f"must be one of {allowed}; got {_show(value)}")
            return options[0]
        return value

    def boolean(self, key: str, *, default: bool) -> bool:
        value = self._lookup(key, required=False)
        if value is _ABSENT:
            return default
        if not isinstance(value, bool):
            self.fail(key, f"must be true or false, got {_show(value)}")
            return default
        return value

    # -- numbers (bool is an int in Python and NaN defeats comparisons, so both are handled)

    def integer(self, key: str, *, ge: int) -> int:
        value = self._lookup(key, required=True)
        if value is _ABSENT:
            return ge
        if isinstance(value, bool) or not isinstance(value, int):
            self.fail(key, f"must be an integer, got {_show(value)}")
            return ge
        if value < ge:
            self.fail(key, f"must be >= {ge}, got {value}")
            return ge
        return value

    def number(self, key: str, *, gt: float | None = None, lt: float | None = None) -> float:
        value = self._lookup(key, required=True)
        if value is _ABSENT:
            return 0.0
        number = self._check_finite(key, value)
        if number is None:
            return 0.0
        # Written as a positive test so NaN, which fails every comparison, is rejected.
        if not ((gt is None or number > gt) and (lt is None or number < lt)):
            bounds = " and ".join(
                part
                for part in (
                    f"> {gt:g}" if gt is not None else "",
                    f"< {lt:g}" if lt is not None else "",
                )
                if part
            )
            self.fail(key, f"must be {bounds}, got {_show(value)}")
            return 0.0
        return number

    def optional_number(self, key: str) -> float | None:
        value = self._lookup(key, required=False)
        return None if value is _ABSENT or value is None else self._check_finite(key, value)

    def _check_finite(self, key: str, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.fail(key, f"must be a finite number, got {_show(value)}")
            return None
        try:
            number = float(value)
        except OverflowError:  # an int too large for a float
            number = math.inf
        if not math.isfinite(number):
            self.fail(key, f"must be a finite number, got {_show(value)}")
            return None
        return number

    # -- nested structure

    def mapping(self, key: str) -> _Node:
        value = self._lookup(key, required=True)
        return self._child(key, value)

    def sequence(self, key: str, *, required: bool = True) -> list[_Node]:
        value = self._lookup(key, required=required)
        if value is _ABSENT or (value is None and not required):
            return []
        if not isinstance(value, list | tuple):
            self.fail(key, f"must be a list, got {_show(value)}")
            return []
        return [self._child(f"{key}[{index}]", item) for index, item in enumerate(value)]

    def _child(self, key: str, value: Any) -> _Node:
        if value is _ABSENT:
            return _Node(None, self._at(key), self._violations)
        if not isinstance(value, Mapping):
            self.fail(key, f"must be a mapping, got {_show(value)}")
            return _Node(None, self._at(key), self._violations)
        return _Node(value, self._at(key), self._violations)
