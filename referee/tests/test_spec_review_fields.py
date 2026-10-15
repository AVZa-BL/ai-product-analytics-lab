"""The optional fields the review rules read (design sections 17.2 and 21.8).

A spec without them is still valid, and an absent field is what makes the matching rule fire,
so the first job of these tests is to pin "absent" precisely.
"""

import functools
from datetime import datetime, timedelta, timezone

import pytest

from referee.spec import ExperimentSpec, SpecError

ENUM_FIELDS = {
    "procedure.stopping_rule": ["sequential"],
    "procedure.srm_check_cadence": ["weekly"],
}
TEXT_FIELDS = ["design.pre_period_covariate", "procedure.bucketing_salt"]
TIMESTAMP_FIELDS = ["design.start_utc"]
ALL_FIELDS = [*ENUM_FIELDS, *TEXT_FIELDS, *TIMESTAMP_FIELDS]


def _put(raw: dict, dotted: str, value: object) -> None:
    """Set a dotted path, creating the optional `procedure` section when it is missing."""
    *parents, leaf = dotted.split(".")
    node = raw
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def _read(spec: ExperimentSpec, dotted: str) -> object:
    return functools.reduce(getattr, dotted.split("."), spec)


def _violations(raw: dict) -> tuple[str, ...]:
    with pytest.raises(SpecError) as caught:
        ExperimentSpec.from_dict(raw)
    return caught.value.violations


@pytest.mark.parametrize(
    ("path", "value"),
    [(path, value) for path, values in ENUM_FIELDS.items() for value in values],
)
def test_every_documented_value_is_accepted(raw_spec: dict, path: str, value: str) -> None:
    _put(raw_spec, path, value)

    assert _read(ExperimentSpec.from_dict(raw_spec), path) == value


@pytest.mark.parametrize("path", TEXT_FIELDS)
@pytest.mark.parametrize("value", ["", "   ", 5, True], ids=["empty", "blank", "int", "bool"])
def test_a_text_field_that_is_present_must_be_a_non_empty_string(
    raw_spec: dict, path: str, value: object
) -> None:
    _put(raw_spec, path, value)

    found = _violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith(f"{path}: must be a non-empty string")


def test_a_misspelt_procedure_key_names_its_likely_target(raw_spec: dict) -> None:
    _put(raw_spec, "procedure.stopping_rul", "fixed_horizon")

    assert _violations(raw_spec) == (
        "procedure: unknown key 'stopping_rul' (did you mean 'stopping_rule'?)",
    )


def test_a_fully_declared_spec_round_trips_and_stays_hashable(raw_spec: dict) -> None:
    declared = {
        "population.exposure_timing": "pre_treatment",
        "population.interference": "none_expected",
        "population.kind": "new_users",
        "design.alpha_adjustment": "bonferroni",
        "design.pre_period_covariate": "sessions_28d",
        "design.start_utc": "2026-11-02T00:00:00Z",
        "procedure.stopping_rule": "fixed_horizon",
        "procedure.srm_check_cadence": "daily",
        "procedure.bucketing_salt": "offer_page_2026_10",
    }
    for path, value in declared.items():
        _put(raw_spec, path, value)

    spec = ExperimentSpec.from_dict(raw_spec)

    assert {path: _read(spec, path) for path in declared} == declared
    assert spec == ExperimentSpec.from_dict(raw_spec)
    assert hash(spec) == hash(ExperimentSpec.from_dict(raw_spec))


# --- design.start_utc: an instant in UTC, kept as one text -------------------------------


@pytest.mark.parametrize(
    ("value", "complaint"),
    [
        ("2026-11-02", "must carry a UTC offset"),
        (datetime(2026, 11, 2, tzinfo=timezone(timedelta(hours=-5))), "must be in UTC (offset 0)"),
        (True, "must be an ISO 8601 timestamp"),
    ],
    ids=[
        "date-text",
        "minus-five-hours",
        "bool",
    ],
)
def test_a_start_that_does_not_name_one_instant_in_utc_is_rejected_once(
    raw_spec: dict, value: object, complaint: str
) -> None:
    _put(raw_spec, "design.start_utc", value)

    found = _violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith("design.start_utc: ") and complaint in found[0]


def test_the_population_kind_names_exactly_the_three_documented_values(raw_spec: dict) -> None:
    _put(raw_spec, "population.kind", "other")

    assert _violations(raw_spec) == (
        "population.kind: must be one of new_users, existing_users, mixed; got 'other'",
    )
