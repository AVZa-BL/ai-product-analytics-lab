"""The proposal a model returns, as a strict schema and a validated, typed object.

The JSON schema is what the model is asked to produce. It is deliberately plain (every field
required, no nulls, no length or pattern keywords) because structured-output schemas support a
subset of JSON Schema; everything the schema cannot say is checked here instead.

Each proposed event and property carries a `rationale`, the reason it should be tracked. An
event also carries `evidence`: either a verbatim quote from one of the documents (which
`check.py` searches for) or the explicit marker `inferred`, meaning the analyst's judgement and
not something the documents say.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from tracewright.plan import PropertyType
from tracewright.reader import Node

PROPOSAL_VERSION = 1

Priority = Literal["must", "should", "could"]
EvidenceKind = Literal["document", "inferred"]

MAX_EVENTS = 100
MAX_PROPERTIES = 60
MAX_TEXT = 2000
MAX_LIST = 100


class ProposalError(ValueError):
    """The model's output is not a valid proposal. Carries every violation found."""

    def __init__(self, violations: list[str] | tuple[str, ...]) -> None:
        self.violations = tuple(violations)
        super().__init__(self.violations)

    def __str__(self) -> str:
        return "invalid proposal:\n" + "\n".join(f"  - {v}" for v in self.violations)


@dataclass(frozen=True, kw_only=True)
class Evidence:
    kind: EvidenceKind
    document: str
    quote: str


@dataclass(frozen=True, kw_only=True)
class ProposedProperty:
    name: str
    type: PropertyType
    required: bool
    pii: bool
    allowed_values: tuple[str, ...]
    description: str
    rationale: str
    reuses_existing: bool


@dataclass(frozen=True, kw_only=True)
class NewEvent:
    name: str
    description: str
    trigger: str
    priority: Priority
    rationale: str
    evidence: Evidence
    properties: tuple[ProposedProperty, ...]


@dataclass(frozen=True, kw_only=True)
class ExtendedEvent:
    name: str
    rationale: str
    evidence: Evidence
    add_properties: tuple[ProposedProperty, ...]


@dataclass(frozen=True, kw_only=True)
class ReusedEvent:
    name: str
    rationale: str


@dataclass(frozen=True, kw_only=True)
class ProposedMetric:
    name: str
    definition: str
    events: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, kw_only=True)
class Exclusion:
    what: str
    why: str


@dataclass(frozen=True, kw_only=True)
class Feature:
    id: str
    name: str
    summary: str


@dataclass(frozen=True, kw_only=True)
class Proposal:
    feature: Feature
    identity_keys: tuple[str, ...]
    new_events: tuple[NewEvent, ...]
    extended_events: tuple[ExtendedEvent, ...]
    reused_events: tuple[ReusedEvent, ...]
    metrics: tuple[ProposedMetric, ...]
    not_tracked: tuple[Exclusion, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: object) -> Proposal:
        """Validate a plain mapping. Raises ProposalError listing every violation."""
        violations: list[str] = []
        if not isinstance(data, Mapping):
            raise ProposalError(["the proposal must be a JSON object"])
        proposal = _proposal(Node(data, "", violations))
        if violations:
            raise ProposalError(violations)
        return proposal

    def to_dict(self) -> dict[str, Any]:
        """The proposal as a plain mapping, in the schema's own shape."""
        return _jsonable(asdict(self))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


# --- The JSON schema the model is asked to produce -----------------------------------------


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TEXT = {"type": "string"}
_BOOL = {"type": "boolean"}
_TEXTS = {"type": "array", "items": _TEXT}

_PROPERTY = _obj(
    {
        "name": _TEXT,
        "type": {"type": "string", "enum": list(get_args(PropertyType))},
        "required": _BOOL,
        "pii": _BOOL,
        "allowed_values": _TEXTS,
        "description": _TEXT,
        "rationale": _TEXT,
        "reuses_existing": _BOOL,
    }
)
_EVIDENCE = _obj(
    {
        "kind": {"type": "string", "enum": list(get_args(EvidenceKind))},
        "document": _TEXT,
        "quote": _TEXT,
    }
)

PROPOSAL_SCHEMA: dict[str, Any] = _obj(
    {
        "feature": _obj({"id": _TEXT, "name": _TEXT, "summary": _TEXT}),
        "identity_keys": _TEXTS,
        "new_events": {
            "type": "array",
            "items": _obj(
                {
                    "name": _TEXT,
                    "description": _TEXT,
                    "trigger": _TEXT,
                    "priority": {"type": "string", "enum": list(get_args(Priority))},
                    "rationale": _TEXT,
                    "evidence": _EVIDENCE,
                    "properties": {"type": "array", "items": _PROPERTY},
                }
            ),
        },
        "extended_events": {
            "type": "array",
            "items": _obj(
                {
                    "name": _TEXT,
                    "rationale": _TEXT,
                    "evidence": _EVIDENCE,
                    "add_properties": {"type": "array", "items": _PROPERTY},
                }
            ),
        },
        "reused_events": {
            "type": "array",
            "items": _obj({"name": _TEXT, "rationale": _TEXT}),
        },
        "metrics": {
            "type": "array",
            "items": _obj(
                {"name": _TEXT, "definition": _TEXT, "events": _TEXTS, "rationale": _TEXT}
            ),
        },
        "not_tracked": {"type": "array", "items": _obj({"what": _TEXT, "why": _TEXT})},
        "assumptions": _TEXTS,
        "open_questions": _TEXTS,
    }
)


# --- Validation -----------------------------------------------------------------------------


def _text(node: Node, key: str, *, allow_empty: bool = False) -> str:
    value = node.text(key, allow_empty=allow_empty)
    if value is not None and len(value) > MAX_TEXT:
        node.fail(key, f"is longer than {MAX_TEXT} characters")
    return value or ""


def _texts(node: Node, key: str) -> tuple[str, ...]:
    values = node.strings(key, required=True, allow_empty=True) or ()
    if len(values) > MAX_LIST:
        node.fail(key, f"has more than {MAX_LIST} entries")
    if any(len(value) > MAX_TEXT for value in values):
        node.fail(key, f"has an entry longer than {MAX_TEXT} characters")
    return values


def _evidence(parent: Node) -> Evidence:
    node = parent.mapping("evidence")
    if node is None:
        return Evidence(kind="inferred", document="", quote="")
    node.require_keys("kind")
    kind = node.choice("kind", get_args(EvidenceKind), default="inferred")
    document = _text(node, "document", allow_empty=True)
    quote = _text(node, "quote", allow_empty=True)
    if kind == "document" and not (document and quote):
        node.fail("quote", "evidence of kind document needs both a document name and a quote")
    node.reject_unknown()
    return Evidence(kind=kind, document=document, quote=quote)  # type: ignore[arg-type]


def _property(node: Node) -> ProposedProperty | None:
    node.require_keys("type")
    name = _text(node, "name")
    prop = ProposedProperty(
        name=name,
        type=node.choice("type", get_args(PropertyType), default="string"),  # type: ignore[arg-type]
        required=_flag(node, "required"),
        pii=_flag(node, "pii"),
        allowed_values=_texts(node, "allowed_values"),
        description=_text(node, "description"),
        rationale=_text(node, "rationale"),
        reuses_existing=_flag(node, "reuses_existing"),
    )
    node.reject_unknown()
    return prop if name else None


def _flag(node: Node, key: str) -> bool:
    node.require_keys(key)
    return node.boolean(key, default=False)


def _properties(node: Node, key: str) -> tuple[ProposedProperty, ...]:
    props = [p for child in node.items(key, required=False) if (p := _property(child))]
    if len(props) > MAX_PROPERTIES:
        node.fail(key, f"has more than {MAX_PROPERTIES} properties")
    return tuple(props)


def _new_event(node: Node) -> NewEvent | None:
    node.require_keys("priority")
    name = _text(node, "name")
    event = NewEvent(
        name=name,
        description=_text(node, "description"),
        trigger=_text(node, "trigger"),
        priority=node.choice("priority", get_args(Priority), default="should"),  # type: ignore[arg-type]
        rationale=_text(node, "rationale"),
        evidence=_evidence(node),
        properties=_properties(node, "properties"),
    )
    node.reject_unknown()
    return event if name else None


def _extended_event(node: Node) -> ExtendedEvent | None:
    name = _text(node, "name")
    event = ExtendedEvent(
        name=name,
        rationale=_text(node, "rationale"),
        evidence=_evidence(node),
        add_properties=_properties(node, "add_properties"),
    )
    if not event.add_properties:
        node.fail("add_properties", "an extended event must add at least one property")
    node.reject_unknown()
    return event if name else None


def _reused_event(node: Node) -> ReusedEvent | None:
    name = _text(node, "name")
    event = ReusedEvent(name=name, rationale=_text(node, "rationale"))
    node.reject_unknown()
    return event if name else None


def _metric(node: Node) -> ProposedMetric | None:
    name = _text(node, "name")
    events = node.strings("events", required=True)
    metric = ProposedMetric(
        name=name,
        definition=_text(node, "definition"),
        events=events or (),
        rationale=_text(node, "rationale"),
    )
    node.reject_unknown()
    return metric if name and events else None


def _exclusion(node: Node) -> Exclusion | None:
    what, why = _text(node, "what"), _text(node, "why")
    node.reject_unknown()
    return Exclusion(what=what, why=why) if what and why else None


def _list(node: Node, key: str, build: Callable[[Node], Any]) -> tuple[Any, ...]:
    items = [x for child in node.items(key, required=False) if (x := build(child))]
    if len(items) > MAX_EVENTS:
        node.fail(key, f"has more than {MAX_EVENTS} entries")
    return tuple(items)


def _feature(node: Node) -> Feature:
    child = node.mapping("feature")
    if child is None:
        return Feature(id="", name="", summary="")
    feature = Feature(
        id=child.identifier("id") or "",
        name=_text(child, "name"),
        summary=_text(child, "summary"),
    )
    child.reject_unknown()
    return feature


def _proposal(node: Node) -> Proposal:
    proposal = Proposal(
        feature=_feature(node),
        identity_keys=_texts(node, "identity_keys"),
        new_events=_list(node, "new_events", _new_event),
        extended_events=_list(node, "extended_events", _extended_event),
        reused_events=_list(node, "reused_events", _reused_event),
        metrics=_list(node, "metrics", _metric),
        not_tracked=_list(node, "not_tracked", _exclusion),
        assumptions=_texts(node, "assumptions"),
        open_questions=_texts(node, "open_questions"),
    )
    node.reject_unknown()
    return proposal
