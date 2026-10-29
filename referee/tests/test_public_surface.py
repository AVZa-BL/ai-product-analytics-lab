"""The names another package builds on: the design-review path of a spec written by someone else.

A separate package (Specwright, planned) drafts a spec with a model and uses Referee as the
deterministic checker, through these names and nothing else. Its own tests run in its own CI job,
which a change under `referee/` does not trigger, so a renamed function or a changed return shape
would break it unseen. These tests fail in Referee's own suite first. They pin what that package
reads, not how Referee computes it.
"""

import inspect
import re
from pathlib import Path

import pytest

from referee.findings import DesignReview, Finding
from referee.loader import LoadError, load_spec, parse_spec
from referee.power import PowerPlan, plan_power
from referee.review import review_design
from referee.rules import ALL_RULES, CATALOGUE
from referee.spec import ExperimentSpec, SpecError

POWERED = Path(__file__).parents[1] / "examples" / "offer-page-powered.yaml"
UNDERPOWERED = Path(__file__).parents[1] / "examples" / "offer-page-underpowered.yaml"


def parameters(function) -> list[tuple[str, str, bool]]:
    """Each parameter's name, kind and whether it has a default."""
    return [
        (p.name, p.kind.name, p.default is not inspect.Parameter.empty)
        for p in inspect.signature(function).parameters.values()
    ]


def test_the_signatures_are_the_ones_a_caller_writes() -> None:
    assert parameters(parse_spec) == [
        ("text", "POSITIONAL_OR_KEYWORD", False),
        ("source", "KEYWORD_ONLY", True),
    ]
    assert parameters(review_design) == [
        ("spec", "POSITIONAL_OR_KEYWORD", False),
        ("rules", "KEYWORD_ONLY", True),
    ]
    assert parameters(plan_power) == [
        ("spec", "POSITIONAL_OR_KEYWORD", False),
        ("alpha_adjustment", "KEYWORD_ONLY", True),
    ]
    assert parameters(ExperimentSpec.from_dict) == [("data", "POSITIONAL_OR_KEYWORD", False)]


def test_the_powered_example_is_a_spec_with_a_fingerprint_that_survives_a_round_trip() -> None:
    spec = parse_spec(POWERED.read_text(encoding="utf-8"), source=str(POWERED))

    assert isinstance(spec, ExperimentSpec)
    assert re.fullmatch(r"[0-9a-f]{64}", spec.sha256())
    assert spec.sha256() == load_spec(POWERED).sha256()
    assert ExperimentSpec.from_dict(spec.to_dict()).sha256() == spec.sha256()


def test_a_design_review_gives_findings_with_the_fields_a_repair_message_is_built_from() -> None:
    assert review_design(load_spec(POWERED)).findings == ()  # the powered example raises nothing

    review = review_design(load_spec(UNDERPOWERED))

    assert isinstance(review, DesignReview)
    assert review.recommendation == "revise" and "DES-001" in review.blocking_rule_ids
    assert review.findings and all(isinstance(f, Finding) for f in review.findings)
    first = review.findings[0]
    assert (first.rule_id, first.severity) == ("DES-001", "blocker")
    assert isinstance(first.title, str) and isinstance(first.evidence, dict)
    assert isinstance(first.remediation, str) and isinstance(first.references, tuple)


def test_a_power_plan_gives_the_numbers_a_draft_must_take_from_code() -> None:
    plan = plan_power(load_spec(POWERED))

    assert isinstance(plan, PowerPlan)
    assert [type(plan.required_total), type(plan.required_days), type(plan.achievable_total)] == [
        int
    ] * 3
    assert plan.is_powered is True
    assert plan.achievable_mde_relative is None or isinstance(plan.achievable_mde_relative, float)
    names = [arm.name for arm in load_spec(POWERED).arms]
    assert [name for name, units in plan.required_per_arm] == names
    assert all(isinstance(units, int) for _, units in plan.required_per_arm)


def test_the_catalogue_lists_every_rule_by_a_stable_id() -> None:
    ids = [rule.id for rule in CATALOGUE]

    assert len(ids) == len(set(ids)) and set(ALL_RULES) <= set(CATALOGUE)
    assert {"HYP-001", "DES-001", "PRO-001", "RES-001"} <= set(ids)
    assert all(
        isinstance(r.title, str) and r.severity in ("blocker", "warning", "info") for r in CATALOGUE
    )


@pytest.mark.parametrize("text", ["referee_spec_version: 1\n", "a: [unclosed\n"])
def test_a_spec_that_cannot_be_read_raises_an_error_that_lists_what_is_wrong(text: str) -> None:
    with pytest.raises((SpecError, LoadError)) as raised:
        parse_spec(text)

    if isinstance(raised.value, SpecError):
        assert raised.value.violations and all(isinstance(v, str) for v in raised.value.violations)
    else:
        assert str(raised.value)
