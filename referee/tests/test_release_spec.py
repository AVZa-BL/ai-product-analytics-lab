"""The release spec (handoff section 4.2): fully valid or rejected with every violation."""

import copy
import pickle
from pathlib import Path

import pytest

from referee.loader import load_release_spec, parse_release_spec
from referee.release_spec import ReleaseSpec, selected_kpis
from referee.spec import SpecError

EXAMPLE = Path(__file__).parents[1] / "examples" / "season-11-update.yaml"
# Pinned so that no change to the canonical form can alter fingerprints unnoticed.
EXAMPLE_SHA256 = "ea8a01753b9f21151e76b091c33e8a12345751d5281c0e4f4cc10c0435ec1af9"

# The example as the plain dict its YAML loads into.
RAW = {
    "referee_release_spec_version": 1,
    "id": "season_11_update_2026_04",
    "title": "Season 11 update (upgrade costs +28%, event rewards -20%)",
    "owner": "live_ops_analytics",
    "release": {"release_id": "config_002"},
    "pre_period_days": 56,
    "post_period_days": 28,
    "kpis": {"defaults": True, "include": ["event_participation_rate"], "exclude": []},
    "guardrails": [
        {"kpi": "d7_retention", "tolerance_relative": 0.03},
        {"kpi": "dau", "tolerance_relative": 0.05},
        {"kpi": "session_frequency", "tolerance_relative": 0.05},
    ],
    "expectation": {"kpi": "arpdau", "direction": "increase", "size_relative": 0.05},
    "segments": ["platform", "acquisition_channel"],
}
SIX_LINES = {key: RAW[key] for key in ("id", "title", "owner", "release", "pre_period_days")}
SIX_LINES |= {"referee_release_spec_version": 1, "post_period_days": 14}


@pytest.fixture
def raw() -> dict:
    return copy.deepcopy(RAW)


def _put(raw: dict, dotted: str, value: object) -> None:
    *parents, last = dotted.split(".")
    node = raw
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    node[int(last) if last.isdigit() else last] = value


def violations(raw: dict) -> tuple[str, ...]:
    """What from_dict reports for `raw`. Fails the test if the spec is accepted."""
    with pytest.raises(SpecError) as caught:
        ReleaseSpec.from_dict(raw)
    return caught.value.violations


# --- The example, and the shortest spec ------------------------------------------------------


def test_the_example_loads_as_the_dict_above_with_the_pinned_fingerprint() -> None:
    spec = load_release_spec(EXAMPLE)

    assert spec == ReleaseSpec.from_dict(RAW)
    assert spec.sha256() == EXAMPLE_SHA256
    assert ReleaseSpec.from_dict(spec.to_dict()).sha256() == spec.sha256()
    assert spec.to_dict()["kpis"] == {"defaults": True, "include": ["event_participation_rate"]}


def test_a_spec_of_six_fields_takes_the_catalogue_defaults_and_registers_nothing_else() -> None:
    spec = ReleaseSpec.from_dict(SIX_LINES)

    assert (spec.kpis.defaults, spec.kpis.include, spec.kpis.exclude) == (True, (), ())
    assert (spec.guardrails, spec.expectation, spec.segments) == ((), None, None)
    assert selected_kpis(spec, ["dau", "arpdau"]) == ("dau", "arpdau")
    spelt_out = {
        **SIX_LINES,
        "kpis": {"defaults": True, "include": [], "exclude": None},
        "guardrails": None,
        "expectation": None,
        "segments": None,
    }
    assert ReleaseSpec.from_dict(spelt_out).sha256() == spec.sha256()


def test_the_selection_is_the_defaults_then_include_without_exclude_each_once(raw: dict) -> None:
    _put(raw, "kpis.exclude", ["payer_conversion"])
    defaults = ["dau", "payer_conversion", "event_participation_rate"]

    assert selected_kpis(ReleaseSpec.from_dict(raw), defaults) == (
        "dau",
        "event_participation_rate",
    )

    _put(raw, "kpis.defaults", False)  # then the guardrails and the expectation must be included
    _put(raw, "kpis.include", ["arpdau", "d7_retention", "dau", "session_frequency"])
    assert selected_kpis(ReleaseSpec.from_dict(raw), defaults) == (
        "arpdau",
        "d7_retention",
        "dau",
        "session_frequency",
    )


# --- Each bound and each cross-field rule, one case per violation ---------------------------


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("referee_release_spec_version", 2),
        ("id", "Season 11"),
        ("release.release_id", ""),
        ("pre_period_days", 27),  # under four weeks
        ("pre_period_days", 30),  # not whole weeks
        ("pre_period_days", 28.0),
        ("post_period_days", 6),
        ("kpis.include", ["dau", "dau"]),
        ("kpis.include", ["Bad KPI"]),
        ("kpis.include", "dau"),
        ("kpis.defaults", "yes"),
        ("guardrails.0.tolerance_relative", 0),
        ("guardrails.0.tolerance_relative", 1),
        ("guardrails.0.kpi", "event_participation_rate "),
        ("expectation.direction", "two_sided"),
        ("expectation.size_relative", 0),
        ("expectation.size_relative", 1),
        ("expectation.size_relative", True),
        ("kpis.exclude", ["Bad KPI"]),
        ("segments", []),
        ("segments", ["platform", "platform"]),
        ("segments", ["bad name"]),
    ],
)
def test_a_value_outside_its_bound_is_a_violation_at_its_own_path(
    raw: dict, path: str, value: object
) -> None:
    _put(raw, path, value)

    found = violations(raw)

    assert len(found) == 1 and found[0].startswith(f"{path.replace('.0.', '[0].')}")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("pre_period_days", 28),  # the shortest baseline, and whole weeks
        ("pre_period_days", 35),
        ("post_period_days", 7),
        ("guardrails.0.tolerance_relative", 0.999),
        ("expectation.size_relative", 0.001),
    ],
)
def test_a_value_at_its_bound_is_accepted_and_survives_a_round_trip(
    raw: dict, path: str, value: object
) -> None:
    _put(raw, path, value)

    spec = ReleaseSpec.from_dict(raw)

    assert ReleaseSpec.from_dict(spec.to_dict()) == spec


@pytest.mark.parametrize(
    ("changes", "path", "fragment"),
    [
        ({"kpis.exclude": ["event_participation_rate"]}, "kpis.include", "also in exclude"),
        ({"kpis.defaults": False, "kpis.include": []}, "kpis.include", "at least one KPI"),
        ({"kpis.exclude": ["dau"]}, "guardrails[1].kpi", "kpis.exclude"),
        ({"kpis.defaults": False}, "guardrails[0].kpi", "not in kpis.include"),
        ({"kpis.defaults": False}, "expectation.kpi", "not in kpis.include"),
        ({"guardrails.1.kpi": "d7_retention"}, "guardrails", "duplicate kpi 'd7_retention'"),
    ],
)
def test_a_kpi_the_review_would_not_read_cannot_be_registered(
    raw: dict, changes: dict, path: str, fragment: str
) -> None:
    for dotted, value in changes.items():
        _put(raw, dotted, value)

    found = violations(raw)

    assert any(v.startswith(f"{path}:") and fragment in v for v in found), found


@pytest.mark.parametrize(
    ("changes", "reported"),
    [
        ({"kpis.defaults": False, "kpis.include": ["Bad KPI"]}, "kpis.include[0]:"),
        ({"kpis.exclude": ["Bad KPI", "event_participation_rate"]}, "kpis.exclude[0]:"),
    ],
)
def test_a_kpi_check_waits_for_a_readable_selection(
    raw: dict, changes: dict, reported: str
) -> None:
    """With `include` or `exclude` itself invalid, or the two in conflict, which KPIs are read
    is unknown, so neither the conflict nor the guardrails and the expectation are also
    reported against it: one mistake, one message."""
    for dotted, value in changes.items():
        _put(raw, dotted, value)

    found = violations(raw)

    assert len(found) == 1 and found[0].startswith(reported)


@pytest.mark.parametrize(
    "path",
    [
        "id",
        "release.release_id",
        "pre_period_days",
        "guardrails.0.tolerance_relative",
        "expectation.direction",
    ],
)
def test_a_required_field_left_out_is_reported_as_required(raw: dict, path: str) -> None:
    *parents, last = path.split(".")
    node = raw
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    del node[last]

    assert violations(raw) == (f"{path.replace('.0.', '[0].')}: is required",)


@pytest.mark.parametrize("section", ["release", "kpis", "guardrails.0", "expectation"])
def test_an_unknown_key_is_refused_in_every_section(raw: dict, section: str) -> None:
    _put(raw, f"{section}.unexpected", 1)

    found = violations(raw)

    assert found == (f"{section.replace('.0', '[0]')}: unknown key 'unexpected'",)


# --- Every violation at once, in schema order, under the release header --------------------


def test_several_violations_arrive_in_one_error_in_schema_order(raw: dict) -> None:
    _put(raw, "id", "Bad Id")
    _put(raw, "pre_period_days", 30)
    _put(raw, "guardrails.0.tolerance_relative", 2)
    _put(raw, "expectation.direction", "sideways")
    raw["post_period_day"] = 28

    found = violations(raw)

    assert [v.split(":")[0] for v in found] == [
        "id",
        "pre_period_days",
        "guardrails[0].tolerance_relative",
        "expectation.direction",
        "spec",
    ]
    assert found[-1].endswith("unknown key 'post_period_day' (did you mean 'post_period_days'?)")
    error = SpecError(found, "release spec")
    assert str(error).startswith("invalid release spec: 5 violations\n")
    assert pickle.loads(pickle.dumps(error)).kind == "release spec"


def test_an_experiment_spec_is_not_a_release_spec() -> None:
    text = "referee_spec_version: 1\nid: x\n"

    with pytest.raises(SpecError) as caught:
        parse_release_spec(text)

    assert caught.value.kind == "release spec"
    assert caught.value.violations[0] == "referee_release_spec_version: is required"
    assert "spec: unknown key 'referee_spec_version'" in caught.value.violations[-1]
