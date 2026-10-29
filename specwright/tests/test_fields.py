"""The closed table of claims stays in step with Referee's spec."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from referee.loader import load_spec
from referee.spec import ExperimentSpec, SpecError

from specwright.fields import LISTS, STATIC, assemble, parse_path, required_paths
from tests.helpers import ROOT

POWERED = ROOT.parent / "referee" / "examples" / "offer-page-powered.yaml"


def flatten(spec: dict[str, Any]) -> dict[str, Any]:
    """A spec dict as claim paths and values."""
    flat: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "referee_spec_version":
            continue
        if isinstance(value, list):
            for i, item in enumerate(value):
                flat.update({f"{key}[{i}].{leaf}": v for leaf, v in item.items()})
        elif isinstance(value, dict):
            flat.update({f"{key}.{leaf}": v for leaf, v in value.items()})
        else:
            flat[key] = value
    return flat


def test_every_field_of_referees_powered_example_has_a_path_and_assembles_back() -> None:
    spec = load_spec(POWERED)
    flat = flatten(spec.to_dict())

    assert [path for path in flat if parse_path(path) is None] == []
    assert ExperimentSpec.from_dict(assemble(flat)).sha256() == spec.sha256()


def enum_cases() -> list[tuple[str, str]]:
    cases = [(p, o) for p, f in STATIC.items() for o in f.options if p != "design.start_utc"]
    for name, leaves in LISTS.items():
        cases += [(f"{name}[0].{leaf}", o) for leaf, f in leaves.items() for o in f.options]
    return cases


@pytest.mark.parametrize(("path", "option"), enum_cases())
def test_every_option_the_table_offers_is_one_referee_accepts(path: str, option: str) -> None:
    base = flatten(load_spec(POWERED).to_dict())
    base.update(
        {
            "guardrails[0].name": "g",
            "guardrails[0].kind": "binary",
            "guardrails[0].baseline": 0.1,
            "guardrails[0].harmful_direction": "decrease",
            "guardrails[0].tolerance_relative": 0.1,
            "secondary_metrics[0].name": "s",
            "secondary_metrics[0].kind": "binary",
        }
    )
    base[path] = option
    try:
        ExperimentSpec.from_dict(assemble(base))
    except SpecError as error:
        # other violations are possible (a ratio metric needs a deviation); a refused option is not
        assert [v for v in error.violations if path.split(".")[-1] in v and "one of" in v] == []


@pytest.mark.parametrize(
    ("claims", "needed", "not_needed"),
    [
        ({"primary_metric.kind": "binary"}, [], ["primary_metric.baseline_std"]),
        ({"primary_metric.kind": "continuous"}, ["primary_metric.baseline_std"], []),
        ({"primary_metric.kind": None}, ["primary_metric.baseline_std"], []),
        ({}, ["arms[0].name", "arms[1].is_control", "design.alpha"], ["arms[2].name"]),
        ({"arms[2].name": "c"}, ["arms[2].allocation"], []),
        (
            {"guardrails[0].kind": "continuous"},
            ["guardrails[0].tolerance_relative", "guardrails[0].baseline_std"],
            [],
        ),
        ({"guardrails[0].kind": "binary"}, [], ["guardrails[0].baseline_std"]),
        ({"secondary_metrics[0].name": "s"}, ["secondary_metrics[0].kind"], []),
    ],
)
def test_the_required_paths_follow_the_metric_kinds_and_the_items_present(
    claims: dict, needed: list[str], not_needed: list[str]
) -> None:
    paths = required_paths(copy.deepcopy(claims))

    assert set(needed) <= set(paths) and not set(not_needed) & set(paths)
