"""The spec's plain-data form, canonical JSON and fingerprint (design section 17.4)."""

import copy
import dataclasses
import functools
import hashlib
import json

import pytest

from referee.spec import ExperimentSpec

# Typed by hand from the schema, not produced by the code under test.
SECTION_6_CANONICAL = (
    '{"arms":[{"allocation":0.5,"is_control":true,"name":"control"},'
    '{"allocation":0.5,"is_control":false,"name":"variant_b"}],'
    '"design":{"alpha":0.05,"mde_relative":0.05,"min_duration_days":14,'
    '"planned_duration_days":14,"power":0.8,"sided":"two_sided"},'
    '"guardrails":[{"baseline":0.018,"harmful_direction":"increase","kind":"binary",'
    '"name":"refund_rate_14d","tolerance_relative":0.1}],'
    '"hypothesis":{"alternative":"Variant B increases 7-day subscription conversion.",'
    '"direction":"increase",'
    '"null":"The offer page variant does not change 7-day subscription conversion."},'
    '"id":"hybrid_offer_page_2026_10","owner":"analytics",'
    '"population":{"analysis_unit":"player","daily_eligible_units":4200,'
    '"eligibility":"Players who open the offer page and are not subscribed at exposure.",'
    '"exposure_trigger":"offer_page_view","randomization_unit":"player"},'
    '"primary_metric":{"baseline":0.032,'
    '"governed_reference":"docs/metrics/hybrid_subscription.md","kind":"binary",'
    '"name":"subscription_conversion_7d"},'
    '"referee_spec_version":1,"title":"Subscription offer page variants"}'
)
# Pinned so that no change to the canonical form can alter fingerprints unnoticed.
SECTION_6_SHA256 = "b0332774feccd582db109bfffff10e1330ce418ab28471ccb625fe0b00af10e8"

OPTIONAL_FIELDS = [
    "population.exposure_timing",
    "population.interference",
    "design.alpha_adjustment",
    "design.pre_period_covariate",
    "procedure.stopping_rule",
    "procedure.srm_check_cadence",
    "procedure.bucketing_salt",
]


def _set(raw: dict, dotted: str, value: object) -> None:
    *parents, leaf = dotted.split(".")
    node = functools.reduce(lambda part, key: part.setdefault(key, {}), parents, raw)
    node[leaf] = value


def _spec(raw: dict) -> ExperimentSpec:
    return ExperimentSpec.from_dict(raw)


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _walk(item)


@pytest.fixture
def full_raw_spec(clean_raw_spec: dict) -> dict:
    """Three arms, a continuous primary metric, and every optional field declared."""
    clean_raw_spec["arms"] = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "b", "allocation": 0.3},
        {"name": "c", "allocation": 0.3},
    ]
    clean_raw_spec["primary_metric"].update(kind="continuous", baseline=12.5, baseline_std=4.0)
    clean_raw_spec["design"]["alpha_adjustment"] = "dunnett"
    return clean_raw_spec


# --- to_dict ---------------------------------------------------------------------------


def test_to_dict_of_the_section_6_example_is_the_schema_without_what_was_not_given(
    raw_spec: dict,
) -> None:
    expected = copy.deepcopy(raw_spec)
    del expected["primary_metric"]["baseline_std"]  # given as null
    expected["arms"][1]["is_control"] = False  # the default, now explicit

    assert _spec(raw_spec).to_dict() == expected


def test_to_dict_follows_schema_order(raw_spec: dict) -> None:
    assert list(_spec(raw_spec).to_dict()) == [
        "referee_spec_version",
        "id",
        "title",
        "owner",
        "hypothesis",
        "population",
        "arms",
        "primary_metric",
        "guardrails",
        "design",
    ]


def test_a_declared_procedure_comes_last(clean_raw_spec: dict) -> None:
    assert list(_spec(clean_raw_spec).to_dict())[-1] == "procedure"


def test_nothing_unset_leaves_a_trace(raw_spec: dict) -> None:
    for path in OPTIONAL_FIELDS:
        _set(raw_spec, path, None)  # explicit nulls, as an empty `key:` in YAML would load

    produced = _spec(raw_spec).to_dict()

    assert None not in list(_walk(produced))
    assert "procedure" not in produced
    assert not any(key in produced["population"] for key in ("exposure_timing", "interference"))


def test_a_declared_optional_field_is_written(clean_raw_spec: dict) -> None:
    produced = _spec(clean_raw_spec).to_dict()

    assert produced["population"]["exposure_timing"] == "pre_treatment"
    assert produced["design"]["pre_period_covariate"] == "subscription_conversion_7d_pre_exposure"
    assert produced["procedure"] == clean_raw_spec["procedure"]


def test_a_partly_declared_procedure_keeps_only_what_was_declared(raw_spec: dict) -> None:
    _set(raw_spec, "procedure.srm_check_cadence", "daily")

    assert _spec(raw_spec).to_dict()["procedure"] == {"srm_check_cadence": "daily"}


def test_a_guardrail_list_that_is_empty_is_kept(raw_spec: dict) -> None:
    raw_spec["guardrails"] = []

    assert _spec(raw_spec).to_dict()["guardrails"] == []


@pytest.mark.parametrize("which", ["raw_spec", "clean_raw_spec", "full_raw_spec"])
def test_to_dict_round_trips_through_from_dict(which: str, request: pytest.FixtureRequest) -> None:
    spec = _spec(request.getfixturevalue(which))

    again = ExperimentSpec.from_dict(spec.to_dict())

    assert again == spec
    assert again.to_dict() == spec.to_dict()
    assert again.sha256() == spec.sha256()


def test_to_dict_returns_fresh_plain_containers(clean_raw_spec: dict) -> None:
    spec = _spec(clean_raw_spec)
    produced = spec.to_dict()
    snapshot = copy.deepcopy(produced)

    produced["arms"].append({"name": "x"})
    produced["procedure"]["stopping_rule"] = "sequential"

    assert spec.to_dict() == snapshot
    assert not any(isinstance(node, tuple) for node in _walk(spec.to_dict()))


# --- canonical_json --------------------------------------------------------------------


def test_canonical_json_of_the_section_6_example_is_the_hand_written_text(raw_spec: dict) -> None:
    assert _spec(raw_spec).canonical_json() == SECTION_6_CANONICAL


def test_canonical_json_is_compact_and_sorted(full_raw_spec: dict) -> None:
    text = _spec(full_raw_spec).canonical_json()

    assert ": " not in text and ", " not in text and "\n" not in text
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


def test_canonical_json_writes_non_ascii_as_it_is(raw_spec: dict) -> None:
    raw_spec["title"] = "Café – offer page"

    assert '"title":"Café – offer page"' in _spec(raw_spec).canonical_json()


def test_canonical_json_refuses_a_non_finite_number(raw_spec: dict) -> None:
    """Only a hand-built spec can hold NaN, because validation rejects it."""
    spec = _spec(raw_spec)
    broken = dataclasses.replace(spec, design=dataclasses.replace(spec.design, alpha=float("nan")))

    with pytest.raises(ValueError, match="not JSON compliant"):
        broken.canonical_json()


# --- sha256 ----------------------------------------------------------------------------


def test_sha256_of_the_section_6_example_is_pinned(raw_spec: dict) -> None:
    assert _spec(raw_spec).sha256() == SECTION_6_SHA256


def test_sha256_is_the_hash_of_the_utf_8_canonical_json(raw_spec: dict) -> None:
    raw_spec["title"] = "Café"
    spec = _spec(raw_spec)

    expected = hashlib.sha256(spec.canonical_json().encode("utf-8")).hexdigest()

    assert spec.sha256() == expected
    assert len(expected) == 64 and expected == expected.lower()


def test_the_fingerprint_ignores_how_the_input_was_laid_out(raw_spec: dict) -> None:
    reversed_layout = {key: raw_spec[key] for key in reversed(raw_spec)}
    reversed_layout["design"] = dict(reversed(list(raw_spec["design"].items())))

    assert _spec(reversed_layout).sha256() == _spec(raw_spec).sha256()


@pytest.mark.parametrize("path", OPTIONAL_FIELDS)
def test_an_absent_field_and_an_explicit_null_have_the_same_fingerprint(
    raw_spec: dict, path: str
) -> None:
    with_null = copy.deepcopy(raw_spec)
    _set(with_null, path, None)

    assert _spec(with_null).sha256() == _spec(raw_spec).sha256()


@pytest.mark.parametrize("section", [None, {}], ids=["null", "empty"])
def test_a_missing_empty_or_null_procedure_have_the_same_fingerprint(
    raw_spec: dict, section: object
) -> None:
    raw_spec["procedure"] = section

    assert _spec(raw_spec).sha256() == SECTION_6_SHA256


def test_the_fingerprint_ignores_whether_a_number_was_written_as_an_int(
    full_raw_spec: dict,
) -> None:
    as_float = copy.deepcopy(full_raw_spec)
    as_int = copy.deepcopy(full_raw_spec)
    as_float["primary_metric"]["baseline_std"] = 4.0
    as_int["primary_metric"]["baseline_std"] = 4

    assert _spec(as_int).sha256() == _spec(as_float).sha256()


CHANGES = [
    ("id", "another_id"),
    ("title", "Another title"),
    ("owner", "someone_else"),
    ("hypothesis.null", "No change at all."),
    ("hypothesis.alternative", "Variant B decreases conversion."),
    ("hypothesis.direction", "two_sided"),
    ("population.randomization_unit", "user"),
    ("population.analysis_unit", "session"),
    ("population.eligibility", "Everyone."),
    ("population.daily_eligible_units", 4201),
    ("population.exposure_trigger", "offer_page_click"),
    ("population.exposure_timing", "pre_treatment"),
    ("population.interference", "possible"),
    ("primary_metric.name", "another_metric"),
    ("primary_metric.baseline", 0.033),
    ("primary_metric.governed_reference", "docs/metrics/other.md"),
    ("design.mde_relative", 0.06),
    ("design.alpha", 0.01),
    ("design.power", 0.9),
    ("design.sided", "one_sided"),
    ("design.planned_duration_days", 15),
    ("design.min_duration_days", 13),
    ("design.alpha_adjustment", "none"),
    ("design.pre_period_covariate", "sessions_28d"),
    ("procedure.stopping_rule", "fixed_horizon"),
    ("procedure.srm_check_cadence", "weekly"),
    ("procedure.bucketing_salt", "salt_1"),
    ("guardrails.0.tolerance_relative", 0.2),
    ("guardrails.0.harmful_direction", "decrease"),
    ("arms.1.name", "variant_z"),
]


@pytest.mark.parametrize(("path", "value"), CHANGES, ids=[path for path, _ in CHANGES])
def test_changing_any_part_of_the_spec_changes_the_fingerprint(
    raw_spec: dict, path: str, value: object
) -> None:
    changed = copy.deepcopy(raw_spec)
    *parents, leaf = path.split(".")
    node = changed
    for part in parents:
        node = node[int(part)] if isinstance(node, list) else node.setdefault(part, {})
    node[int(leaf) if isinstance(node, list) else leaf] = value

    assert _spec(changed).sha256() != SECTION_6_SHA256


def test_the_allocation_split_is_part_of_the_fingerprint(raw_spec: dict) -> None:
    raw_spec["arms"][0]["allocation"] = 0.6
    raw_spec["arms"][1]["allocation"] = 0.4

    assert _spec(raw_spec).sha256() != SECTION_6_SHA256


def test_the_order_of_the_arms_is_part_of_the_fingerprint(raw_spec: dict) -> None:
    raw_spec["arms"].reverse()

    assert _spec(raw_spec).sha256() != SECTION_6_SHA256


def test_adding_a_guardrail_changes_the_fingerprint(raw_spec: dict) -> None:
    raw_spec["guardrails"].append(
        {
            "name": "churn_30d",
            "kind": "binary",
            "baseline": 0.05,
            "harmful_direction": "increase",
            "tolerance_relative": 0.1,
        }
    )

    assert _spec(raw_spec).sha256() != SECTION_6_SHA256
