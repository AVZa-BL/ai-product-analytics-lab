"""Milestone 1 contract: a spec is either fully valid or rejected with every violation."""

import math
import pickle

import pytest

from referee.display import for_line
from referee.spec import ExperimentSpec, SpecError


def _container(raw: dict, dotted: str) -> tuple:
    """Resolve a dotted path such as "arms.1.allocation" to (container, last key)."""
    *parents, last = dotted.split(".")
    node = raw
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    return node, int(last) if last.isdigit() else last


def _put(raw: dict, dotted: str, value: object) -> None:
    node, key = _container(raw, dotted)
    node[key] = value


def _drop(raw: dict, dotted: str) -> None:
    node, key = _container(raw, dotted)
    del node[key]


def violations(raw: dict) -> tuple[str, ...]:
    """What from_dict reports for `raw`. Fails the test if the spec is accepted."""
    with pytest.raises(SpecError) as caught:
        ExperimentSpec.from_dict(raw)
    return caught.value.violations


# --- The seven cases section 7 requires ---------------------------------------------------


def test_analysis_unit_defaults_to_the_randomization_unit(raw_spec: dict) -> None:
    _put(raw_spec, "population.randomization_unit", "device")
    _drop(raw_spec, "population.analysis_unit")

    assert ExperimentSpec.from_dict(raw_spec).population.analysis_unit == "device"


@pytest.mark.parametrize("controls", [[False, False]], ids=["none"])
def test_exactly_one_control_arm_is_required(raw_spec: dict, controls: list[bool]) -> None:
    for index, is_control in enumerate(controls):
        _put(raw_spec, f"arms.{index}.is_control", is_control)

    with pytest.raises(SpecError, match="is_control"):
        ExperimentSpec.from_dict(raw_spec)


def test_continuous_metric_without_baseline_std_is_rejected(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.kind", "continuous")
    _put(raw_spec, "primary_metric.baseline", 12.5)  # a mean, not a rate

    with pytest.raises(SpecError, match="baseline_std"):
        ExperimentSpec.from_dict(raw_spec)


@pytest.mark.parametrize(
    ("field", "value"),
    [("mde_relative", -0.1)],
    ids=["mde_is_negative"],
)
def test_design_values_outside_their_bounds_are_rejected(
    raw_spec: dict, field: str, value: float
) -> None:
    _put(raw_spec, f"design.{field}", value)

    with pytest.raises(SpecError, match=f"design.{field}"):
        ExperimentSpec.from_dict(raw_spec)


def test_several_violations_arrive_in_one_error_in_schema_order(raw_spec: dict) -> None:
    _put(raw_spec, "id", "Bad Id")
    _put(raw_spec, "arms.1.allocation", 0.4)
    _put(raw_spec, "primary_metric.baseline", 1.2)
    _put(raw_spec, "design.alpha", 1.0)
    raw_spec["mde_relativ"] = 0.05

    found = violations(raw_spec)

    assert len(found) == 5
    schema_order = ["id:", "arms:", "primary_metric.baseline:", "design.alpha:", "mde_relativ"]
    for needle, violation in zip(schema_order, found, strict=True):
        assert needle in violation
    message = str(SpecError(found))
    assert "5 violations" in message
    assert all(violation in message for violation in found)


# --- Beyond section 7: each test pins a rule of 6.1 or an accepted default ----------------


def test_a_null_guardrails_list_means_none(raw_spec: dict) -> None:
    """An empty `guardrails:` in YAML loads as None."""
    raw_spec["guardrails"] = None

    assert ExperimentSpec.from_dict(raw_spec).guardrails == ()


@pytest.mark.parametrize("version", [2, 0, 1.0])
def test_only_version_one_is_accepted(raw_spec: dict, version: object) -> None:
    _put(raw_spec, "referee_spec_version", version)

    assert any(v.startswith("referee_spec_version:") for v in violations(raw_spec))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("population.daily_eligible_units", True),
        ("population.daily_eligible_units", 0),
    ],
)
def test_integer_fields_take_real_integers_of_at_least_one(
    raw_spec: dict, path: str, value: object
) -> None:
    """`True` is an int in Python, so a bare isinstance check would let it through."""
    _put(raw_spec, path, value)

    assert any(violation.startswith(f"{path}:") for violation in violations(raw_spec))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("design.alpha", math.nan),
        ("design.mde_relative", math.inf),
    ],
)
def test_numbers_must_be_finite_and_not_booleans(raw_spec: dict, path: str, value: object) -> None:
    """NaN fails every comparison, so a check written as `x <= 0` would let it through."""
    _put(raw_spec, path, value)

    assert violations(raw_spec)


@pytest.mark.parametrize("baseline", [0, 1])
def test_binary_baseline_is_an_open_interval(raw_spec: dict, baseline: float) -> None:
    _put(raw_spec, "primary_metric.baseline", baseline)

    assert any(v.startswith("primary_metric.baseline:") for v in violations(raw_spec))


def test_binary_metric_must_not_carry_a_baseline_std(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.baseline_std", 0.1)

    assert any(v.startswith("primary_metric.baseline_std:") for v in violations(raw_spec))


@pytest.mark.parametrize("kind", ["continuous"])
def test_continuous_and_ratio_metrics_take_a_positive_baseline_std(
    raw_spec: dict, kind: str
) -> None:
    _put(raw_spec, "primary_metric.kind", kind)
    _put(raw_spec, "primary_metric.baseline", 12.5)
    _put(raw_spec, "primary_metric.baseline_std", 4.0)
    assert ExperimentSpec.from_dict(raw_spec).primary_metric.baseline_std == 4.0

    _put(raw_spec, "primary_metric.baseline_std", 0)
    assert any(v.startswith("primary_metric.baseline_std:") for v in violations(raw_spec))


def test_allocation_sum_tolerance_is_one_billionth(raw_spec: dict) -> None:
    """1e-9 is the documented tolerance: 5e-10 off passes, 2e-9 off does not."""
    _put(raw_spec, "arms.1.allocation", 0.5 + 5e-10)
    ExperimentSpec.from_dict(raw_spec)

    _put(raw_spec, "arms.1.allocation", 0.5 + 2e-9)
    assert any(v.startswith("arms:") and "sum to 1" in v for v in violations(raw_spec))


def test_at_least_two_arms_with_unique_names_are_required(raw_spec: dict) -> None:
    _put(raw_spec, "arms.1.name", "control")
    assert any("duplicate name 'control'" in v for v in violations(raw_spec))

    raw_spec["arms"] = [{"name": "control", "allocation": 1.0, "is_control": True}]
    assert any("at least two arms" in v for v in violations(raw_spec))


def test_min_duration_may_not_exceed_planned_duration(raw_spec: dict) -> None:
    _put(raw_spec, "design.min_duration_days", 21)

    assert any(v.startswith("design.min_duration_days:") for v in violations(raw_spec))


def test_guardrails_follow_the_metric_rules_and_have_unique_names(raw_spec: dict) -> None:
    raw_spec["guardrails"].append(dict(raw_spec["guardrails"][0]))
    assert any("duplicate name 'refund_rate_14d'" in v for v in violations(raw_spec))

    _drop(raw_spec, "guardrails.1")
    _put(raw_spec, "guardrails.0.baseline", 1.5)
    _put(raw_spec, "guardrails.0.harmful_direction", "sideways")
    _put(raw_spec, "guardrails.0.tolerance_relative", 0)
    found = violations(raw_spec)
    assert [v.split(":")[0] for v in found] == [
        "guardrails[0].baseline",
        "guardrails[0].harmful_direction",
        "guardrails[0].tolerance_relative",
    ]


# Two names that a report writes the same ("va" and U+0001, and the text va\x01) are two names to
# the spec and to the JSON report, but the text and memo reports key a table by the written form,
# so one of them would silently disappear from it (design section 23.1).
SAME_WRITTEN = [
    pytest.param("va\x01", "va\\x01", id="control character"),
    pytest.param("va\n", "va\\n", id="newline"),  # `for_terminal` keeps it; `for_line` writes it
]


@pytest.mark.parametrize(("first", "second"), SAME_WRITTEN)
def test_arm_names_that_a_report_writes_the_same_are_refused(
    raw_spec: dict, first: str, second: str
) -> None:
    assert first != second and for_line(first) == for_line(second)
    raw_spec["arms"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": first, "allocation": 0.3},
        {"name": second, "allocation": 0.3},
    ]

    found = [v for v in violations(raw_spec) if "written the same" in v]

    assert found == [
        f"arms: names {first!r}, {second!r} are written the same in a report, as {for_line(first)}"
    ]


@pytest.mark.parametrize(("first", "second"), SAME_WRITTEN)
def test_one_such_name_alone_is_accepted(raw_spec: dict, first: str, second: str) -> None:
    """Refusing the name itself would reject specs whose reports are right."""
    _put(raw_spec, "arms.1.name", first)

    assert ExperimentSpec.from_dict(raw_spec).arms[1].name == first


def test_guardrail_names_that_a_report_writes_the_same_are_refused(raw_spec: dict) -> None:
    guardrail = raw_spec["guardrails"][0]
    raw_spec["guardrails"] = [dict(guardrail, name="va\x01"), dict(guardrail, name="va\\x01")]

    found = [v for v in violations(raw_spec) if "written the same" in v]

    assert len(found) == 1 and found[0].startswith("guardrails: names 'va\\x01', 'va\\\\x01'")


def test_a_repeated_name_is_one_violation_and_not_also_a_collision(raw_spec: dict) -> None:
    _put(raw_spec, "arms.1.name", "control")

    assert not any("written the same" in v for v in violations(raw_spec))


def test_guardrails_do_not_take_a_governed_reference(raw_spec: dict) -> None:
    """It belongs to the primary metric only; rule HYP-002 reads it there."""
    _put(raw_spec, "guardrails.0.governed_reference", "docs/metrics/x.md")

    assert any("guardrails[0]: unknown key 'governed_reference'" in v for v in violations(raw_spec))


def test_a_misspelt_nested_key_gets_a_did_you_mean_hint(raw_spec: dict) -> None:
    raw_spec["design"]["alphaa"] = 0.1

    assert any(
        "design: unknown key 'alphaa' (did you mean 'alpha'?)" in v for v in violations(raw_spec)
    )


# --- One mistake, one message ---------------------------------------------------------------


def test_a_missing_section_is_reported_once(raw_spec: dict) -> None:
    _drop(raw_spec, "design")

    assert violations(raw_spec) == ("design: is required",)


def test_a_bad_allocation_type_does_not_also_report_a_bad_sum(raw_spec: dict) -> None:
    _put(raw_spec, "arms.1.allocation", "half")

    found = violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith("arms[1].allocation:")


def test_arms_of_the_wrong_shape_are_reported(raw_spec: dict) -> None:
    raw_spec["arms"] = "control"
    assert violations(raw_spec) == ("arms: must be a list, got 'control'",)

    raw_spec["arms"] = [{"name": "control", "allocation": 1.0, "is_control": True}, "variant"]
    assert any(v.startswith("arms[1]: must be a mapping") for v in violations(raw_spec))


# --- Properties of the result and of the error ------------------------------------------------


def test_spec_error_is_a_value_error_that_survives_pickling(raw_spec: dict) -> None:
    _put(raw_spec, "design.alpha", 1.0)
    with pytest.raises(ValueError) as caught:
        ExperimentSpec.from_dict(raw_spec)

    error = caught.value
    assert isinstance(error, SpecError)
    assert isinstance(error.violations, tuple)
    assert pickle.loads(pickle.dumps(error)).violations == error.violations
    assert str(error).startswith("invalid experiment spec: 1 violation\n")
