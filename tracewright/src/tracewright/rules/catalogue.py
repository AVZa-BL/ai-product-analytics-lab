"""The rules (NAM naming, SCH schema, DOC documentation, GOV governance, COV coverage)."""

from __future__ import annotations

import re
from typing import Any

from tracewright.plan import Event, Property, TrackingPlan
from tracewright.rules.base import Rule
from tracewright.rules.references import GDPR_2016_679, KOHAVI_TANG_XU_2020

# object_action: at least two lowercase words joined by underscores, e.g. checkout_started.
EVENT_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
PROPERTY_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# Name parts that usually mean personal data. A heuristic, so a hit is a question, not a verdict.
PII_TOKENS = frozenset(
    {
        "email", "phone", "ssn", "password", "passport", "dob", "birthdate", "birthday",
        "surname", "address", "ip",
        # joined spellings, which a snake_case split cannot take apart
        "firstname", "lastname", "fullname", "phonenumber", "emailaddress", "ipaddress",
    }
)
PII_PAIRS = frozenset(
    {("first", "name"), ("last", "name"), ("full", "name"), ("birth", "date"), ("ip", "address")}
)
_CAMEL_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")


def _live(plan: TrackingPlan) -> tuple[Event, ...]:
    """Events that are, or will be, sent: everything except deprecated ones."""
    return tuple(event for event in plan.events if event.status != "deprecated")


def _looks_like_pii(name: str) -> bool:
    # camelCase and PascalCase are split like snake_case, so userEmail and IPAddress are seen.
    spaced = _CAMEL_ACRONYM.sub(r"\1_\2", _CAMEL_LOWER_UPPER.sub(r"\1_\2", name))
    parts = spaced.lower().split("_")
    return any(part in PII_TOKENS for part in parts) or any(
        pair in PII_PAIRS for pair in zip(parts, parts[1:], strict=False)
    )


def _all_properties(plan: TrackingPlan) -> list[tuple[Event, Property]]:
    return [(event, prop) for event in plan.events for prop in event.properties]


# --- Naming -------------------------------------------------------------------------------


def _event_names(plan: TrackingPlan) -> dict[str, Any] | None:
    bad = [event.name for event in plan.events if not EVENT_NAME.fullmatch(event.name)]
    return {"events": bad} if bad else None


def _property_names(plan: TrackingPlan) -> dict[str, Any] | None:
    names = {prop.name for _, prop in _all_properties(plan)}
    bad = sorted(name for name in names if not PROPERTY_NAME.fullmatch(name))
    return {"properties": bad} if bad else None


NAM_001 = Rule(
    id="NAM-001",
    severity="warning",
    title="Event name does not follow object_action",
    fires_when="An event name is not at least two lowercase words joined by underscores.",
    why_it_matters=(
        "Names such as 'click' or 'CheckoutStarted' cannot be searched, grouped or governed "
        "consistently. A single convention is what lets a query select every event about one "
        "object, and keeps two spellings of one event from splitting its counts."
    ),
    remediation=(
        "Rename the event to object_action in snake_case, for example checkout_started. "
        "Deprecate the old name instead of reusing it."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_event_names,
)

NAM_002 = Rule(
    id="NAM-002",
    severity="warning",
    title="Property name is not snake_case",
    fires_when="A property name is not lowercase words joined by underscores.",
    why_it_matters=(
        "Warehouses fold case differently, so 'planId' and 'plan_id' can become two columns or "
        "one, depending on the destination. A fixed style removes the ambiguity."
    ),
    remediation="Rename the property to snake_case, for example plan_id.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_property_names,
)

# --- Schema -------------------------------------------------------------------------------


def _conflicting_types(plan: TrackingPlan) -> dict[str, Any] | None:
    types: dict[str, dict[str, list[str]]] = {}
    for event, prop in _all_properties(plan):
        types.setdefault(prop.name, {}).setdefault(prop.type, []).append(event.name)
    conflicts = {
        name: {kind: sorted(events) for kind, events in sorted(by_type.items())}
        for name, by_type in sorted(types.items())
        if len(by_type) > 1
    }
    return {"properties": conflicts} if conflicts else None


def _enum_without_values(plan: TrackingPlan) -> dict[str, Any] | None:
    bad = [
        f"{event.name}.{prop.name}"
        for event, prop in _all_properties(plan)
        if prop.type == "enum" and not prop.allowed_values
    ]
    return {"properties": bad} if bad else None


def _no_identity(plan: TrackingPlan) -> dict[str, Any] | None:
    keys = set(plan.identity_keys)
    bad = [
        event.name
        for event in _live(plan)
        if not any(prop.name in keys and prop.required for prop in event.properties)
    ]
    return {"identity_keys": list(plan.identity_keys), "events": bad} if bad else None


SCH_001 = Rule(
    id="SCH-001",
    severity="blocker",
    title="Same property name has different types on different events",
    fires_when="Two events declare a property with the same name but a different type.",
    why_it_matters=(
        "A property that is a string on one event and a number on another cannot be stored in "
        "one warehouse column, so loads fail or silently coerce, and joins across events give "
        "wrong results."
    ),
    remediation=(
        "Give the property one type everywhere, or rename one of them if they mean different "
        "things."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_conflicting_types,
)

SCH_002 = Rule(
    id="SCH-002",
    severity="warning",
    title="Enum property declares no allowed values",
    fires_when="A property of type enum has no allowed_values.",
    why_it_matters=(
        "Without a closed list, every typo or new spelling becomes a new category, and a funnel "
        "split by that property silently loses rows."
    ),
    remediation="List every permitted value in allowed_values, or change the type to string.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_enum_without_values,
)

SCH_003 = Rule(
    id="SCH-003",
    severity="blocker",
    title="Event cannot be tied to a user or device",
    fires_when=(
        "A planned or active event has no required property named in identity_keys."
    ),
    why_it_matters=(
        "An event that does not say who or which device produced it cannot be counted per user, "
        "joined to other events, or used in any retention or conversion metric."
    ),
    remediation=(
        "Add one of the identity_keys to the event as a required property, or set it once "
        "globally and list it on every event."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_no_identity,
)

# --- Documentation ------------------------------------------------------------------------


def _undocumented(plan: TrackingPlan) -> dict[str, Any] | None:
    bad = [e.name for e in _live(plan) if e.description is None or e.trigger is None]
    return {"events": bad} if bad else None


def _unowned(plan: TrackingPlan) -> dict[str, Any] | None:
    if plan.owner is not None:
        return None
    bad = [e.name for e in _live(plan) if e.owner is None]
    return {"events": bad} if bad else None


DOC_001 = Rule(
    id="DOC-001",
    severity="warning",
    title="Event has no description or trigger",
    fires_when="A planned or active event lacks a description or a trigger.",
    why_it_matters=(
        "If nobody wrote down when the event fires, each analyst guesses, and the same event name "
        "ends up meaning different things in different dashboards."
    ),
    remediation=(
        "Add a description (what it means) and a trigger (the exact user or system action "
        "that emits it)."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_undocumented,
)

DOC_002 = Rule(
    id="DOC-002",
    severity="warning",
    title="Event has no owner",
    fires_when="A planned or active event has no owner and the plan has no default owner.",
    why_it_matters=(
        "When an event breaks or its meaning must change, someone has to be asked. Without an "
        "owner the question has no answer, and broken events stay broken."
    ),
    remediation="Set the event's owner, or set a plan-level owner that covers every event.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_unowned,
)

# --- Governance ---------------------------------------------------------------------------


def _undeclared_pii(plan: TrackingPlan) -> dict[str, Any] | None:
    bad = [
        f"{event.name}.{prop.name}"
        for event, prop in _all_properties(plan)
        if not prop.pii and _looks_like_pii(prop.name)
    ]
    return {"properties": bad} if bad else None


GOV_001 = Rule(
    id="GOV-001",
    severity="blocker",
    title="Property name suggests personal data but is not marked pii",
    fires_when=(
        "A property is not marked pii: true and its name, split into words at underscores and at "
        "camelCase boundaries, contains a personal-data word such as email, phone, address, ip, "
        "ssn, password, passport, dob, birthdate, birthday or surname, a joined spelling such as "
        "firstname or phonenumber, or a pair such as first_name, last_name, full_name or "
        "ip_address."
    ),
    why_it_matters=(
        "Personal data sent to analytics without a recorded decision is a privacy risk and a "
        "compliance question (data minimisation). The check is by name, so it can be wrong in "
        "both directions: it will miss a personal value with an innocent name."
    ),
    remediation=(
        "If the property holds personal data, set pii: true and record the lawful basis outside "
        "this plan, or stop sending it. If it does not, rename it so it is not mistaken for "
        "personal data."
    ),
    references=(GDPR_2016_679,),
    check=_undeclared_pii,
)

# --- Coverage -----------------------------------------------------------------------------


def _undefined_events(plan: TrackingPlan) -> dict[str, Any] | None:
    known = {event.name for event in plan.events}
    bad = {m.name: [e for e in m.events if e not in known] for m in plan.metrics}
    bad = {name: events for name, events in bad.items() if events}
    return {"metrics": bad} if bad else None


def _deprecated_dependencies(plan: TrackingPlan) -> dict[str, Any] | None:
    deprecated = {e.name for e in plan.events if e.status == "deprecated"}
    bad = {m.name: [e for e in m.events if e in deprecated] for m in plan.metrics}
    bad = {name: events for name, events in bad.items() if events}
    return {"metrics": bad} if bad else None


def _planned_dependencies(plan: TrackingPlan) -> dict[str, Any] | None:
    planned = {e.name for e in plan.events if e.status == "planned"}
    bad = {m.name: [e for e in m.events if e in planned] for m in plan.metrics}
    bad = {name: events for name, events in bad.items() if events}
    return {"metrics": bad} if bad else None


def _unused_events(plan: TrackingPlan) -> dict[str, Any] | None:
    if not plan.metrics:
        return None
    used = {event for metric in plan.metrics for event in metric.events}
    bad = [e.name for e in plan.events if e.status == "active" and e.name not in used]
    return {"events": bad} if bad else None


COV_001 = Rule(
    id="COV-001",
    severity="blocker",
    title="Metric depends on an event the plan does not define",
    fires_when="A metric lists an event name that is not declared in events.",
    why_it_matters=(
        "A metric built on an event nobody tracks will read zero or stay empty, and the gap "
        "looks like a business result instead of a tracking hole."
    ),
    remediation="Define the event in events, or correct the name in the metric.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_undefined_events,
)

COV_002 = Rule(
    id="COV-002",
    severity="blocker",
    title="Metric depends on a deprecated event",
    fires_when="A metric lists an event whose status is deprecated.",
    why_it_matters=(
        "A deprecated event stops arriving. A metric still reading it will decay toward zero "
        "and be mistaken for a real decline."
    ),
    remediation="Point the metric at the replacement event, then retire the old one.",
    references=(KOHAVI_TANG_XU_2020,),
    check=_deprecated_dependencies,
)

COV_003 = Rule(
    id="COV-003",
    severity="warning",
    title="Metric depends on an event that is only planned",
    fires_when="A metric lists an event whose status is planned.",
    why_it_matters=(
        "Until the event ships, the metric computes on partial or no data, and its history "
        "will have a break at the release date."
    ),
    remediation=(
        "Mark the metric as not ready until the event is active, or document the start date "
        "in the metric definition."
    ),
    references=(KOHAVI_TANG_XU_2020,),
    check=_planned_dependencies,
)

COV_004 = Rule(
    id="COV-004",
    severity="info",
    title="Active event is used by no metric",
    fires_when="The plan declares metrics and an active event appears in none of them.",
    why_it_matters=(
        "An event nobody reads still costs volume, maintenance and privacy exposure. It is "
        "either missing from a metric that should use it, or not worth collecting."
    ),
    remediation="Connect the event to a metric, or deprecate it.",
    references=(GDPR_2016_679,),
    check=_unused_events,
)

ALL_RULES: tuple[Rule, ...] = (
    NAM_001, NAM_002, SCH_001, SCH_002, SCH_003, DOC_001, DOC_002,
    GOV_001, COV_001, COV_002, COV_003, COV_004,
)
