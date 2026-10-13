"""The optional fields the review rules read (design sections 17.2 and 21.8).

A spec without them is still valid, and an absent field is what makes the matching rule fire,
so the first job of these tests is to pin "absent" precisely.
"""

import functools
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from referee.spec import ExperimentSpec, Procedure, SpecError

ENUM_FIELDS = {
    "population.exposure_timing": ["pre_treatment", "post_treatment"],
    "population.interference": ["none_expected", "possible"],
    "population.kind": ["new_users", "existing_users", "mixed"],
    "design.alpha_adjustment": ["none", "bonferroni", "dunnett"],
    "procedure.stopping_rule": ["fixed_horizon", "sequential"],
    "procedure.srm_check_cadence": ["daily", "weekly", "none"],
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


def test_a_spec_without_the_new_fields_reads_them_as_absent(raw_spec: dict) -> None:
    spec = ExperimentSpec.from_dict(raw_spec)

    assert all(_read(spec, path) is None for path in ALL_FIELDS)
    assert spec.procedure == Procedure(
        stopping_rule=None, srm_check_cadence=None, bucketing_salt=None
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [(path, value) for path, values in ENUM_FIELDS.items() for value in values],
)
def test_every_documented_value_is_accepted(raw_spec: dict, path: str, value: str) -> None:
    _put(raw_spec, path, value)

    assert _read(ExperimentSpec.from_dict(raw_spec), path) == value


@pytest.mark.parametrize("path", TEXT_FIELDS)
def test_text_fields_take_any_non_empty_string(raw_spec: dict, path: str) -> None:
    _put(raw_spec, path, "pre_period_sessions_28d")

    assert _read(ExperimentSpec.from_dict(raw_spec), path) == "pre_period_sessions_28d"


@pytest.mark.parametrize("path", list(ENUM_FIELDS))
@pytest.mark.parametrize(
    "value", ["sometimes", 5, True, ["daily"]], ids=["word", "int", "bool", "list"]
)
def test_an_undocumented_value_is_rejected_once(raw_spec: dict, path: str, value: object) -> None:
    _put(raw_spec, path, value)

    found = _violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith(f"{path}: must be one of ")


@pytest.mark.parametrize("path", TEXT_FIELDS)
@pytest.mark.parametrize("value", ["", "   ", 5, True], ids=["empty", "blank", "int", "bool"])
def test_a_text_field_that_is_present_must_be_a_non_empty_string(
    raw_spec: dict, path: str, value: object
) -> None:
    _put(raw_spec, path, value)

    found = _violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith(f"{path}: must be a non-empty string")


@pytest.mark.parametrize("path", ALL_FIELDS)
def test_an_explicit_null_means_absent(raw_spec: dict, path: str) -> None:
    """An empty `key:` in YAML loads as None; it must read the same as leaving the key out."""
    _put(raw_spec, path, None)

    assert _read(ExperimentSpec.from_dict(raw_spec), path) is None


def test_a_null_procedure_section_means_none_was_declared(raw_spec: dict) -> None:
    raw_spec["procedure"] = None

    assert ExperimentSpec.from_dict(raw_spec).procedure == Procedure(
        stopping_rule=None, srm_check_cadence=None, bucketing_salt=None
    )


@pytest.mark.parametrize("section", ["oops", [], 5], ids=["string", "list", "int"])
def test_the_procedure_section_must_be_a_mapping(raw_spec: dict, section: object) -> None:
    raw_spec["procedure"] = section

    found = _violations(raw_spec)

    assert len(found) == 1
    assert found[0].startswith("procedure: must be a mapping")


def test_a_misspelt_procedure_key_names_its_likely_target(raw_spec: dict) -> None:
    _put(raw_spec, "procedure.stopping_rul", "fixed_horizon")

    assert _violations(raw_spec) == (
        "procedure: unknown key 'stopping_rul' (did you mean 'stopping_rule'?)",
    )


def test_the_procedure_may_be_declared_in_part(raw_spec: dict) -> None:
    _put(raw_spec, "procedure.srm_check_cadence", "daily")

    assert ExperimentSpec.from_dict(raw_spec).procedure == Procedure(
        stopping_rule=None, srm_check_cadence="daily", bucketing_salt=None
    )


def test_violations_follow_schema_order_with_procedure_last(raw_spec: dict) -> None:
    _put(raw_spec, "procedure.stopping_rule", "whenever")
    _put(raw_spec, "design.alpha_adjustment", "holm")
    _put(raw_spec, "population.interference", "maybe")

    found = _violations(raw_spec)

    assert [violation.split(":")[0] for violation in found] == [
        "population.interference",
        "design.alpha_adjustment",
        "procedure.stopping_rule",
    ]


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

_START = "2026-11-02T00:00:00Z"


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-02T00:00:00Z",
        "2026-11-02T00:00:00+00:00",
        "2026-11-02T00:00:00+00",
        "2026-11-02 00:00:00Z",
        "2026-11-02T00:00:00.000Z",
        datetime(2026, 11, 2, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=timezone(timedelta(0))),
    ],
    ids=[
        "z",
        "numeric",
        "short-numeric",
        "space",
        "fraction-zero",
        "datetime-utc",
        "datetime-zero",
    ],
)
def test_every_spelling_of_the_same_utc_instant_reads_as_one_text(
    raw_spec: dict, value: object
) -> None:
    _put(raw_spec, "design.start_utc", value)

    assert ExperimentSpec.from_dict(raw_spec).design.start_utc == _START


def test_a_fraction_of_a_second_is_kept(raw_spec: dict) -> None:
    _put(raw_spec, "design.start_utc", "2026-11-02T00:00:00.5Z")

    assert ExperimentSpec.from_dict(raw_spec).design.start_utc == "2026-11-02T00:00:00.500000Z"


@pytest.mark.parametrize(
    ("value", "complaint"),
    [
        ("2026-11-02", "must carry a UTC offset"),
        ("2026-11-02T00:00:00", "must carry a UTC offset"),
        (datetime(2026, 11, 2), "must carry a UTC offset"),
        ("2026-11-02T01:00:00+01:00", "must be in UTC (offset 0)"),
        (datetime(2026, 11, 2, tzinfo=timezone(timedelta(hours=-5))), "must be in UTC (offset 0)"),
        (date(2026, 11, 2), "must be an ISO 8601 timestamp"),
        ("tomorrow", "must be an ISO 8601 timestamp"),
        (" 2026-11-02T00:00:00Z", "must be an ISO 8601 timestamp"),
        ("", "must be an ISO 8601 timestamp"),
        (20261102, "must be an ISO 8601 timestamp"),
        (True, "must be an ISO 8601 timestamp"),
        ([_START], "must be an ISO 8601 timestamp"),
    ],
    ids=[
        "date-text",
        "naive-text",
        "naive-datetime",
        "plus-one-hour",
        "minus-five-hours",
        "date",
        "word",
        "padded",
        "empty",
        "int",
        "bool",
        "list",
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
