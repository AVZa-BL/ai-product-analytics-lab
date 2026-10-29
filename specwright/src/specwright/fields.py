"""The claims a draft may make, and how they become a spec.

A draft is a list of claims. Each names one leaf of the experiment spec by its path
(`primary_metric.baseline`, `arms[1].allocation`) and says where its value comes from. This table
is the closed list of paths. `arms`, `guardrails` and `secondary_metrics` are lists, so their
paths carry an index that starts at 0 and has no gaps. Two paths, `stated.required_total_players`
and `stated.required_days`, are not spec fields: they carry a sample size or a duration that a
document states, so that it can be compared with the one Referee works out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

UNITS = ("player", "user", "device", "session", "cluster")
KINDS = ("binary", "continuous", "ratio")
FAMILIES = ("revenue_like", "count", "binary", "other")


@dataclass(frozen=True, kw_only=True)
class Field:
    kind: str  # text | enum | integer | number | boolean
    required: bool = False
    options: tuple[str, ...] = ()


def _text(required: bool = False) -> Field:
    return Field(kind="text", required=required)


def _enum(*options: str, required: bool = False) -> Field:
    return Field(kind="enum", required=required, options=options)


# Static paths, in the order a spec lists them.
STATIC: dict[str, Field] = {
    "id": _text(True),
    "title": _text(True),
    "owner": _text(True),
    "hypothesis.null": _text(True),
    "hypothesis.alternative": _text(True),
    "hypothesis.direction": _enum("increase", "decrease", "two_sided", required=True),
    "population.randomization_unit": _enum(*UNITS, required=True),
    "population.analysis_unit": _enum(*UNITS, required=True),
    "population.eligibility": _text(True),
    "population.daily_eligible_units": Field(kind="integer", required=True),
    "population.exposure_trigger": _text(True),
    "population.exposure_timing": _enum("pre_treatment", "post_treatment"),
    "population.interference": _enum("none_expected", "possible"),
    "population.kind": _enum("new_users", "existing_users", "mixed"),
    "primary_metric.name": _text(True),
    "primary_metric.kind": _enum(*KINDS, required=True),
    "primary_metric.baseline": Field(kind="number", required=True),
    "primary_metric.baseline_std": Field(kind="number"),  # required unless the metric is binary
    "primary_metric.column": _text(),
    "primary_metric.family": _enum(*FAMILIES),
    "primary_metric.governed_reference": _text(),
    "design.mde_relative": Field(kind="number", required=True),
    "design.alpha": Field(kind="number", required=True),
    "design.power": Field(kind="number", required=True),
    "design.sided": _enum("two_sided", "one_sided", required=True),
    "design.planned_duration_days": Field(kind="integer", required=True),
    "design.min_duration_days": Field(kind="integer", required=True),
    "design.alpha_adjustment": _enum("none", "bonferroni", "dunnett"),
    "design.pre_period_covariate": _text(),
    "design.start_utc": _text(),
    "procedure.stopping_rule": _enum("fixed_horizon", "sequential"),
    "procedure.srm_check_cadence": _enum("daily", "weekly", "none"),
    "procedure.bucketing_salt": _text(),
    "stated.required_total_players": Field(kind="number"),
    "stated.required_days": Field(kind="number"),
}

# Paths of the three lists, by list name and leaf.
LISTS: dict[str, dict[str, Field]] = {
    "arms": {
        "name": _text(True),
        "allocation": Field(kind="number", required=True),
        "is_control": Field(kind="boolean", required=True),
    },
    "guardrails": {
        "name": _text(True),
        "kind": _enum(*KINDS, required=True),
        "baseline": Field(kind="number", required=True),
        "baseline_std": Field(kind="number"),  # required unless the metric is binary
        "column": _text(),
        "family": _enum(*FAMILIES),
        "harmful_direction": _enum("increase", "decrease", required=True),
        "tolerance_relative": Field(kind="number", required=True),
    },
    "secondary_metrics": {
        "name": _text(True),
        "kind": _enum(*KINDS, required=True),
        "column": _text(),
        "family": _enum(*FAMILIES),
    },
}
MIN_ARMS = 2

_INDEXED = re.compile(r"^(arms|guardrails|secondary_metrics)\[(\d+)\]\.([a-z_]+)$")


def parse_path(path: str) -> tuple[Field, str | None, int | None] | None:
    """The field a path names, with its list name and index, or None if no claim may use it."""
    if path in STATIC:
        return STATIC[path], None, None
    found = _INDEXED.match(path)
    if found and found.group(3) in LISTS[found.group(1)]:
        return LISTS[found.group(1)][found.group(3)], found.group(1), int(found.group(2))
    return None


def is_numeric(field: Field) -> bool:
    return field.kind in ("integer", "number")


def indices(paths: set[str], name: str) -> list[int]:
    """The indices of list `name` that have a claim."""
    return sorted(
        {int(m.group(2)) for p in paths if (m := _INDEXED.match(p)) and m.group(1) == name}
    )


def required_paths(claims: dict[str, Any]) -> list[str]:
    """Every path the draft must make a claim about, whatever its value: a spec cannot be built
    without them. `claims` maps a path to its value (None when the claim is missing or
    ambiguous); it is read for the kinds of metric, which decide whether a standard deviation is
    needed, and for which list items exist."""
    needed = [path for path, field in STATIC.items() if field.required]
    if claims.get("primary_metric.kind") != "binary":
        needed.append("primary_metric.baseline_std")
    paths = set(claims)
    for name, leaves in LISTS.items():
        present = indices(paths, name)
        count = max(MIN_ARMS if name == "arms" else 0, present[-1] + 1 if present else 0)
        for i in range(count):
            for leaf, field in leaves.items():
                if field.required:
                    needed.append(f"{name}[{i}].{leaf}")
            if name == "guardrails" and claims.get(f"guardrails[{i}].kind") != "binary":
                needed.append(f"guardrails[{i}].baseline_std")
    return needed


def assemble(values: dict[str, Any]) -> dict[str, Any]:
    """The spec as a plain dict from the claims that carry a value (paths -> values).

    `stated.*` claims are left out: they are not part of the spec.
    """
    spec: dict[str, Any] = {"referee_spec_version": 1}
    lists: dict[str, dict[int, dict[str, Any]]] = {name: {} for name in LISTS}
    for path, value in values.items():
        parsed = parse_path(path)
        if parsed is None or path.startswith("stated."):
            continue
        _, name, index = parsed
        if name is None:
            *parents, leaf = path.split(".")
            node = spec
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = value
        else:
            assert index is not None
            lists[name].setdefault(index, {})[path.rsplit(".", 1)[1]] = value
    for name, items in lists.items():
        if items:
            spec[name] = [items[i] for i in sorted(items)]
    return spec
