"""The spec's plain-data form, canonical JSON and fingerprint (design section 17.4)."""

import dataclasses
import functools

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
    "population.kind",
    "design.alpha_adjustment",
    "design.pre_period_covariate",
    "design.start_utc",
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


def test_nothing_unset_leaves_a_trace(raw_spec: dict) -> None:
    for path in OPTIONAL_FIELDS:
        _set(raw_spec, path, None)  # explicit nulls, as an empty `key:` in YAML would load

    produced = _spec(raw_spec).to_dict()

    assert None not in list(_walk(produced))
    assert "procedure" not in produced
    assert not any(
        key in produced["population"] for key in ("exposure_timing", "interference", "kind")
    )
    assert "start_utc" not in produced["design"]


# --- canonical_json --------------------------------------------------------------------


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


@pytest.mark.parametrize("section", [None, {}], ids=["null", "empty"])
def test_a_missing_empty_or_null_procedure_have_the_same_fingerprint(
    raw_spec: dict, section: object
) -> None:
    raw_spec["procedure"] = section

    assert _spec(raw_spec).sha256() == SECTION_6_SHA256


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


