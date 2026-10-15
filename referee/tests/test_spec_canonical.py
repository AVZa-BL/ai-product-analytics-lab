"""The spec's plain-data form, canonical JSON and fingerprint (design section 17.4)."""

import dataclasses
import functools

import pytest

from referee.spec import ExperimentSpec

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


@pytest.mark.parametrize("section", [None], ids=["null"])
def test_a_missing_empty_or_null_procedure_have_the_same_fingerprint(
    raw_spec: dict, section: object
) -> None:
    raw_spec["procedure"] = section

    assert _spec(raw_spec).sha256() == SECTION_6_SHA256


