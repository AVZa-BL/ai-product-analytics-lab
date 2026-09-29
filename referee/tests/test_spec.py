"""Milestone 1 contract: a spec is either fully valid or rejected with every violation."""

import dataclasses
import math
import pickle

import pytest

from referee.spec import ExperimentSpec, SpecError


@pytest.fixture
def raw_spec() -> dict:
    """A valid spec as the plain dict a YAML file would load into. Fresh for every test."""
    return {
        "referee_spec_version": 1,
        "id": "hybrid_offer_page_2026_10",
        "title": "Subscription offer page variants",
        "owner": "analytics",
        "hypothesis": {
            "null": "The offer page variant does not change 7-day subscription conversion.",
            "alternative": "Variant B increases 7-day subscription conversion.",
            "direction": "increase",
        },
        "population": {
            "randomization_unit": "player",
            "analysis_unit": "player",
            "eligibility": "Players who open the offer page and are not subscribed at exposure.",
            "daily_eligible_units": 4200,
            "exposure_trigger": "offer_page_view",
        },
        "arms": [
            {"name": "control", "allocation": 0.5, "is_control": True},
            {"name": "variant_b", "allocation": 0.5},
        ],
        "primary_metric": {
            "name": "subscription_conversion_7d",
            "kind": "binary",
            "baseline": 0.032,
            "baseline_std": None,
            "governed_reference": "docs/metrics/hybrid_subscription.md",
        },
        "guardrails": [
            {
                "name": "refund_rate_14d",
                "kind": "binary",
                "baseline": 0.018,
                "harmful_direction": "increase",
                "tolerance_relative": 0.10,
            }
        ],
        "design": {
            "mde_relative": 0.05,
            "alpha": 0.05,
            "power": 0.80,
            "sided": "two_sided",
            "planned_duration_days": 14,
            "min_duration_days": 14,
        },
    }


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


def test_valid_spec_round_trips_into_frozen_dataclasses(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)

    assert spec.referee_spec_version == 1
    assert spec.id == "hybrid_offer_page_2026_10"
    assert spec.hypothesis.direction == "increase"
    assert spec.population.randomization_unit == "player"
    assert spec.population.daily_eligible_units == 4200
    assert [(arm.name, arm.allocation, arm.is_control) for arm in spec.arms] == [
        ("control", 0.5, True),
        ("variant_b", 0.5, False),
    ]
    assert spec.primary_metric.kind == "binary"
    assert spec.primary_metric.baseline == 0.032
    assert spec.primary_metric.baseline_std is None
    assert spec.primary_metric.governed_reference == "docs/metrics/hybrid_subscription.md"
    assert spec.guardrails[0].harmful_direction == "increase"
    assert spec.guardrails[0].tolerance_relative == 0.10
    assert spec.design.alpha == 0.05
    assert spec.design.min_duration_days == 14

    # A frozen dataclass holding a list would only be shallowly frozen.
    assert isinstance(spec.arms, tuple)
    assert isinstance(spec.guardrails, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.title = "changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.design.alpha = 0.10


def test_analysis_unit_defaults_to_the_randomization_unit(raw_spec: dict) -> None:
    _put(raw_spec, "population.randomization_unit", "device")
    _drop(raw_spec, "population.analysis_unit")

    assert ExperimentSpec.from_dict(raw_spec).population.analysis_unit == "device"


def test_allocations_summing_to_less_than_one_are_rejected(raw_spec: dict) -> None:
    _put(raw_spec, "arms.1.allocation", 0.4)

    with pytest.raises(SpecError, match="allocation"):
        ExperimentSpec.from_dict(raw_spec)


@pytest.mark.parametrize("controls", [[False, False], [True, True]], ids=["none", "two"])
def test_exactly_one_control_arm_is_required(raw_spec: dict, controls: list[bool]) -> None:
    for index, is_control in enumerate(controls):
        _put(raw_spec, f"arms.{index}.is_control", is_control)

    with pytest.raises(SpecError, match="is_control"):
        ExperimentSpec.from_dict(raw_spec)


def test_binary_baseline_above_one_is_rejected(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.baseline", 1.2)

    with pytest.raises(SpecError, match="baseline"):
        ExperimentSpec.from_dict(raw_spec)


def test_continuous_metric_without_baseline_std_is_rejected(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.kind", "continuous")
    _put(raw_spec, "primary_metric.baseline", 12.5)  # a mean, not a rate

    with pytest.raises(SpecError, match="baseline_std"):
        ExperimentSpec.from_dict(raw_spec)


@pytest.mark.parametrize(
    ("field", "value"),
    [("alpha", 1.0), ("power", 0), ("mde_relative", -0.1)],
    ids=["alpha_is_one", "power_is_zero", "mde_is_negative"],
)
def test_design_values_outside_their_bounds_are_rejected(
    raw_spec: dict, field: str, value: float
) -> None:
    _put(raw_spec, f"design.{field}", value)

    with pytest.raises(SpecError, match=f"design.{field}"):
        ExperimentSpec.from_dict(raw_spec)


def test_an_unknown_top_level_key_is_named(raw_spec: dict) -> None:
    raw_spec["mde_relativ"] = 0.05

    with pytest.raises(SpecError, match="mde_relativ"):
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


def test_a_different_analysis_unit_is_valid_but_reviewable(raw_spec: dict) -> None:
    """Well-formedness is not design quality: rule HYP-003 will warn about this later."""
    _put(raw_spec, "population.analysis_unit", "session")

    assert ExperimentSpec.from_dict(raw_spec).population.analysis_unit == "session"


def test_analysis_unit_must_be_a_known_unit(raw_spec: dict) -> None:
    _put(raw_spec, "population.analysis_unit", "event")

    assert any("population.analysis_unit" in violation for violation in violations(raw_spec))


def test_omitted_optional_fields_take_their_defaults(raw_spec: dict) -> None:
    _drop(raw_spec, "guardrails")
    _drop(raw_spec, "primary_metric.baseline_std")
    _drop(raw_spec, "primary_metric.governed_reference")

    spec = ExperimentSpec.from_dict(raw_spec)

    assert spec.guardrails == ()
    assert spec.primary_metric.baseline_std is None
    assert spec.primary_metric.governed_reference is None
    assert spec.arms[1].is_control is False


def test_a_null_guardrails_list_means_none(raw_spec: dict) -> None:
    """An empty `guardrails:` in YAML loads as None."""
    raw_spec["guardrails"] = None

    assert ExperimentSpec.from_dict(raw_spec).guardrails == ()


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("title", "title"),
        ("owner", "owner"),
        ("hypothesis.null", "hypothesis.null"),
        ("hypothesis.alternative", "hypothesis.alternative"),
        ("population.eligibility", "population.eligibility"),
        ("population.exposure_trigger", "population.exposure_trigger"),
        ("arms.0.name", "arms[0].name"),
        ("primary_metric.name", "primary_metric.name"),
    ],
)
@pytest.mark.parametrize("value", ["", "   ", None, 5], ids=["empty", "blank", "null", "number"])
def test_every_string_field_must_be_a_non_empty_string(
    raw_spec: dict, path: str, needle: str, value: object
) -> None:
    _put(raw_spec, path, value)

    assert any(violation.startswith(f"{needle}:") for violation in violations(raw_spec))


@pytest.mark.parametrize("bad_id", ["Bad Id", "abc\n", "", "has-dash", "UPPER"])
def test_id_must_be_lowercase_letters_digits_and_underscores(raw_spec: dict, bad_id: str) -> None:
    """ "abc\\n" matters: `$` in a regex accepts a trailing newline unless fullmatch is used."""
    _put(raw_spec, "id", bad_id)

    assert any(violation.startswith("id:") for violation in violations(raw_spec))


@pytest.mark.parametrize("version", [2, 0, True, 1.0, "1"])
def test_only_version_one_is_accepted(raw_spec: dict, version: object) -> None:
    _put(raw_spec, "referee_spec_version", version)

    assert any(v.startswith("referee_spec_version:") for v in violations(raw_spec))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("population.daily_eligible_units", True),
        ("population.daily_eligible_units", 4200.0),
        ("population.daily_eligible_units", "4200"),
        ("population.daily_eligible_units", 0),
        ("design.planned_duration_days", 14.0),
        ("design.min_duration_days", 0),
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
        ("design.power", True),
        ("primary_metric.baseline", math.nan),
        ("arms.0.allocation", math.nan),
    ],
)
def test_numbers_must_be_finite_and_not_booleans(raw_spec: dict, path: str, value: object) -> None:
    """NaN fails every comparison, so a check written as `x <= 0` would let it through."""
    _put(raw_spec, path, value)

    assert violations(raw_spec)


@pytest.mark.parametrize("baseline", [0, 1, -0.1])
def test_binary_baseline_is_an_open_interval(raw_spec: dict, baseline: float) -> None:
    _put(raw_spec, "primary_metric.baseline", baseline)

    assert any(v.startswith("primary_metric.baseline:") for v in violations(raw_spec))


def test_binary_metric_must_not_carry_a_baseline_std(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.baseline_std", 0.1)

    assert any(v.startswith("primary_metric.baseline_std:") for v in violations(raw_spec))


@pytest.mark.parametrize("kind", ["continuous", "ratio"])
def test_continuous_and_ratio_metrics_take_a_positive_baseline_std(
    raw_spec: dict, kind: str
) -> None:
    _put(raw_spec, "primary_metric.kind", kind)
    _put(raw_spec, "primary_metric.baseline", 12.5)
    _put(raw_spec, "primary_metric.baseline_std", 4.0)
    assert ExperimentSpec.from_dict(raw_spec).primary_metric.baseline_std == 4.0

    _put(raw_spec, "primary_metric.baseline_std", 0)
    assert any(v.startswith("primary_metric.baseline_std:") for v in violations(raw_spec))


def test_an_unknown_metric_kind_is_rejected_without_further_noise(raw_spec: dict) -> None:
    _put(raw_spec, "primary_metric.kind", "median")

    found = violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith("primary_metric.kind:")


def test_allocation_sum_tolerance_is_one_billionth(raw_spec: dict) -> None:
    """1e-9 is the documented tolerance: 5e-10 off passes, 2e-9 off does not."""
    _put(raw_spec, "arms.1.allocation", 0.5 + 5e-10)
    ExperimentSpec.from_dict(raw_spec)

    _put(raw_spec, "arms.1.allocation", 0.5 + 2e-9)
    assert any(v.startswith("arms:") and "sum to 1" in v for v in violations(raw_spec))


def test_three_equal_arms_are_accepted(raw_spec: dict) -> None:
    """1/3 + 1/3 + 1/3 is not exactly 1.0 in floating point."""
    raw_spec["arms"] = [
        {"name": "control", "allocation": 1 / 3, "is_control": True},
        {"name": "b", "allocation": 1 / 3},
        {"name": "c", "allocation": 1 / 3},
    ]

    assert len(ExperimentSpec.from_dict(raw_spec).arms) == 3


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


def test_a_section_of_the_wrong_type_is_reported_once(raw_spec: dict) -> None:
    _put(raw_spec, "design", "oops")

    assert violations(raw_spec) == ("design: must be a mapping, got 'oops'",)


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


def test_something_that_is_not_a_mapping_is_rejected() -> None:
    with pytest.raises(SpecError, match="spec: must be a mapping"):
        ExperimentSpec.from_dict(None)


# --- Properties of the result and of the error ------------------------------------------------


def test_equal_input_gives_equal_hashable_specs(raw_spec: dict) -> None:
    first = ExperimentSpec.from_dict(raw_spec)
    second = ExperimentSpec.from_dict(raw_spec)

    assert first == second
    assert hash(first) == hash(second)


def test_the_result_does_not_alias_or_mutate_the_input(raw_spec: dict) -> None:
    before = repr(raw_spec)
    spec = ExperimentSpec.from_dict(raw_spec)

    assert repr(raw_spec) == before
    raw_spec["arms"][0]["allocation"] = 0.99
    assert spec.arms[0].allocation == 0.5


def test_spec_error_is_a_value_error_that_survives_pickling(raw_spec: dict) -> None:
    _put(raw_spec, "design.alpha", 1.0)
    with pytest.raises(ValueError) as caught:
        ExperimentSpec.from_dict(raw_spec)

    error = caught.value
    assert isinstance(error, SpecError)
    assert isinstance(error.violations, tuple)
    assert pickle.loads(pickle.dumps(error)).violations == error.violations
    assert str(error).startswith("invalid experiment spec: 1 violation\n")
