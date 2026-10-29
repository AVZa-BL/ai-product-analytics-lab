"""The draft a model returns: claims about the spec, each with where its value comes from.

Parsing is strict. A response that is not JSON, names a path no claim may use, gives a value of
the wrong type, or has evidence that does not fit its kind is not a draft; every violation is
listed, and they go back to the model with the same weight as any other problem.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from specwright.fields import LISTS, Field, indices, is_numeric, parse_path

EVIDENCE_KINDS = ("document", "inferred", "missing", "ambiguous")
MAX_CLAIMS = 200
MAX_TEXT = 1000


class DraftError(ValueError):
    """The response is not a valid draft. Carries every violation found."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = tuple(violations)
        super().__init__("; ".join(self.violations))


@dataclass(frozen=True, kw_only=True)
class Evidence:
    kind: str  # document | inferred | missing | ambiguous
    document: str
    quote: str
    note: str


@dataclass(frozen=True, kw_only=True)
class Claim:
    path: str
    value: Any  # None for a missing or ambiguous claim
    evidence: Evidence

    @property
    def field(self) -> Field:
        parsed = parse_path(self.path)
        assert parsed is not None
        return parsed[0]

    @property
    def stated(self) -> bool:
        """Whether the claim gives a value to the spec (as opposed to leaving a question)."""
        return self.evidence.kind in ("document", "inferred")


@dataclass(frozen=True, kw_only=True)
class Draft:
    claims: tuple[Claim, ...]
    open_questions: tuple[str, ...]
    assumptions: tuple[str, ...]

    def by_path(self) -> dict[str, Claim]:
        return {claim.path: claim for claim in self.claims}

    @classmethod
    def from_json(cls, text: str) -> Draft:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise DraftError([f"the response is not valid JSON ({error})"]) from error
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Any) -> Draft:
        violations: list[str] = []
        if not isinstance(data, dict):
            raise DraftError(["the response must be a JSON object"])
        for key in sorted(set(data) - {"claims", "open_questions", "assumptions"}):
            violations.append(f"unknown key {key!r}")
        raw_claims = data.get("claims")
        if not isinstance(raw_claims, list):
            raise DraftError(violations + ["claims: must be a list"])
        if len(raw_claims) > MAX_CLAIMS:
            violations.append(f"claims: {len(raw_claims)} given; the limit is {MAX_CLAIMS}")
            raw_claims = raw_claims[:MAX_CLAIMS]
        claims, seen = [], set()
        for position, raw in enumerate(raw_claims):
            claim = _claim(raw, position, violations)
            if claim is None:
                continue
            if claim.path in seen:
                violations.append(f"claims[{position}] {claim.path}: stated twice")
            seen.add(claim.path)
            claims.append(claim)
        for name in LISTS:
            present = indices({c.path for c in claims}, name)
            if present != list(range(len(present))):
                violations.append(
                    f"{name}: indices must run 0, 1, 2... without gaps, got {present}"
                )
        lists = {}
        for key in ("open_questions", "assumptions"):
            items = data.get(key, [])
            if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
                violations.append(f"{key}: must be a list of strings")
                items = []
            lists[key] = tuple(item[:MAX_TEXT] for item in items)
        if violations:
            raise DraftError(violations)
        return cls(claims=tuple(claims), **lists)


def _claim(raw: Any, position: int, violations: list[str]) -> Claim | None:
    where = f"claims[{position}]"
    if not isinstance(raw, dict) or set(raw) != {"path", "value", "evidence"}:
        violations.append(f"{where}: must be an object with exactly path, value and evidence")
        return None
    path = raw["path"]
    parsed = parse_path(path) if isinstance(path, str) else None
    if parsed is None:
        violations.append(f"{where}: {path!r} is not a path a claim may use")
        return None
    where = f"{where} {path}"
    evidence = _evidence(raw["evidence"], where, violations)
    if evidence is None:
        return None
    field = parsed[0]
    value = raw["value"]
    if evidence.kind in ("missing", "ambiguous"):
        if value is not None:
            violations.append(
                f"{where}: a {evidence.kind} claim has no value (null), got {value!r}"
            )
            return None
        if not evidence.note:
            violations.append(f"{where}: a {evidence.kind} claim needs a note saying what to ask")
    else:
        value = _typed(value, field, where, violations)
        if value is None:
            return None
    return Claim(path=path, value=value, evidence=evidence)


def _evidence(raw: Any, where: str, violations: list[str]) -> Evidence | None:
    keys = {"kind", "document", "quote", "note"}
    if not isinstance(raw, dict) or set(raw) != keys:
        violations.append(f"{where}: evidence must be an object with exactly {sorted(keys)}")
        return None
    if raw["kind"] not in EVIDENCE_KINDS:
        violations.append(f"{where}: evidence.kind must be one of {list(EVIDENCE_KINDS)}")
        return None
    if not all(isinstance(raw[k], str) and len(raw[k]) <= MAX_TEXT for k in keys - {"kind"}):
        violations.append(
            f"{where}: document, quote and note must be strings of at most {MAX_TEXT}"
        )
        return None
    evidence = Evidence(**raw)
    if evidence.kind == "document" and not (evidence.document and evidence.quote):
        violations.append(f"{where}: document evidence needs the document's name and a quote")
        return None
    if evidence.kind != "document" and (evidence.document or evidence.quote):
        violations.append(f"{where}: only document evidence has a document and a quote")
        return None
    return evidence


def _typed(value: Any, field: Field, where: str, violations: list[str]) -> Any:
    """`value` as the field's type, or None after recording why it is not."""
    kind = field.kind
    if kind == "boolean" and isinstance(value, bool):
        return value
    if kind in ("text", "enum") and isinstance(value, str) and value.strip():
        if len(value) > MAX_TEXT:
            violations.append(f"{where}: longer than {MAX_TEXT} characters")
            return None
        if kind == "enum" and value not in field.options:
            violations.append(f"{where}: must be one of {list(field.options)}, got {value!r}")
            return None
        return value
    if is_numeric(field) and isinstance(value, int | float) and not isinstance(value, bool):
        if not math.isfinite(value):
            violations.append(f"{where}: must be a finite number")
            return None
        if kind == "integer":
            if float(value) != int(value):
                violations.append(f"{where}: must be a whole number, got {value!r}")
                return None
            return int(value)
        return value
    violations.append(f"{where}: must be a {kind} value, got {value!r}")
    return None
