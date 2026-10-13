"""Typed, validated tracking plan for Tracewright.

A tracking plan is the written contract for what a product sends to analytics: which events
exist, what each property means and what type it has, who owns it, and which business metrics
depend on it. This module answers one question: is the plan well-formed? Whether the plan is
well designed is a separate question for the review rules, which read a valid plan and never
repair an invalid one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from tracewright.reader import Node

PLAN_VERSION = 1
VERSION_KEY = "tracewright_plan_version"

EventStatus = Literal["active", "planned", "deprecated"]
PropertyType = Literal["string", "integer", "number", "boolean", "timestamp", "enum"]

class PlanError(ValueError):
    """The plan is malformed. Carries every violation found, not just the first."""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(violations)
        super().__init__(self.violations)

    def __str__(self) -> str:
        noun = "violation" if len(self.violations) == 1 else "violations"
        header = f"invalid tracking plan: {len(self.violations)} {noun}"
        return "\n".join([header, *(f"  - {violation}" for violation in self.violations)])


@dataclass(frozen=True, kw_only=True)
class Property:
    name: str
    type: PropertyType
    required: bool
    description: str | None
    pii: bool
    allowed_values: tuple[str, ...] | None


@dataclass(frozen=True, kw_only=True)
class Event:
    name: str
    status: EventStatus
    description: str | None
    trigger: str | None
    owner: str | None
    properties: tuple[Property, ...]


@dataclass(frozen=True, kw_only=True)
class Metric:
    name: str
    events: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class TrackingPlan:
    id: str
    title: str
    owner: str | None
    identity_keys: tuple[str, ...]
    events: tuple[Event, ...]
    metrics: tuple[Metric, ...]

    @classmethod
    def from_dict(cls, data: object) -> TrackingPlan:
        """Validate a plain mapping. Raises PlanError listing every violation."""
        violations: list[str] = []
        if not isinstance(data, Mapping):
            raise PlanError(["the plan must be a mapping of fields"])
        plan = _plan(Node(data, "", violations))
        if violations or plan is None:
            raise PlanError(violations or ["the plan could not be read"])
        return plan

    def to_dict(self) -> dict[str, Any]:
        """The plan as the plain mapping a YAML file holds, without unset (None) fields."""
        return {VERSION_KEY: PLAN_VERSION, **_drop_unset(asdict(self))}

    def canonical_json(self) -> str:
        """JSON that ignores comments, key order and layout: the plan's content only."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def sha256(self) -> str:
        """The hex SHA-256 of the canonical JSON as UTF-8: this plan's fingerprint."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _drop_unset(value: Any) -> Any:
    if isinstance(value, dict):
        kept = {key: _drop_unset(item) for key, item in value.items()}
        return {key: item for key, item in kept.items() if item is not None and item != {}}
    if isinstance(value, list | tuple):
        return [_drop_unset(item) for item in value]
    return value


def _property(node: Node) -> Property | None:
    name = node.text("name")
    kind = node.choice("type", get_args(PropertyType), default="string")
    if "type" not in node.data:
        node.fail("type", "is required")
    allowed = node.strings("allowed_values", required=False)
    if allowed is not None and kind != "enum":
        node.fail("allowed_values", "is only meaningful when type is enum")
    if allowed is not None and len(set(allowed)) != len(allowed):
        node.fail("allowed_values", "must not repeat a value")
    prop = Property(
        name=name or "",
        type=kind,  # type: ignore[arg-type]
        required=node.boolean("required", default=False),
        description=node.text("description", required=False),
        pii=node.boolean("pii", default=False),
        allowed_values=allowed,
    )
    node.reject_unknown()
    return prop if name else None


def _event(node: Node) -> Event | None:
    name = node.text("name")
    status = node.choice("status", get_args(EventStatus), default="active")
    properties = []
    for child in node.items("properties", required=False):
        prop = _property(child)
        if prop is not None:
            properties.append(prop)
    seen: set[str] = set()
    for prop in properties:
        if prop.name in seen:
            node.fail("properties", f"property {prop.name!r} is declared twice")
        seen.add(prop.name)
    event = Event(
        name=name or "",
        status=status,  # type: ignore[arg-type]
        description=node.text("description", required=False),
        trigger=node.text("trigger", required=False),
        owner=node.text("owner", required=False),
        properties=tuple(properties),
    )
    node.reject_unknown()
    return event if name else None


def _metric(node: Node) -> Metric | None:
    name = node.text("name")
    events = node.strings("events", required=True)
    node.reject_unknown()
    if name is None or events is None:
        return None
    return Metric(name=name, events=events)


def _plan(node: Node) -> TrackingPlan | None:
    version = node.get(VERSION_KEY, required=True)
    if version is not None and version != PLAN_VERSION:
        node.fail("tracewright_plan_version", f"must be {PLAN_VERSION}, got {version!r}")
    plan_id = node.identifier("id")
    title = node.text("title")
    owner = node.text("owner", required=False)
    identity = node.strings("identity_keys", required=True)
    events = [e for child in node.items("events") if (e := _event(child)) is not None]
    metrics = [m for child in node.items("metrics", required=False) if (m := _metric(child))]
    declared = (("events", [e.name for e in events]), ("metrics", [m.name for m in metrics]))
    for label, names in declared:
        for name in sorted({n for n in names if names.count(n) > 1}):
            node.violations.append(f"{label}: {name!r} is declared more than once")
    node.reject_unknown()
    if plan_id is None or title is None or identity is None:
        return None
    return TrackingPlan(
        id=plan_id,
        title=title,
        owner=owner,
        identity_keys=identity,
        events=tuple(events),
        metrics=tuple(metrics),
    )
