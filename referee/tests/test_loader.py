"""Reading a spec from YAML: what is accepted, and the traps PyYAML would let through."""

import pickle
from pathlib import Path

import pytest
import yaml

from referee.loader import LoadError, _problem, _where, load_spec, parse_spec
from referee.spec import ExperimentSpec, SpecError

# The design's section 6 example as a person would write it. `null` is quoted because an
# unquoted one is not text to YAML.
SECTION_6_YAML = """\
referee_spec_version: 1
id: hybrid_offer_page_2026_10
title: Subscription offer page variants
owner: analytics
hypothesis:
  "null": The offer page variant does not change 7-day subscription conversion.
  alternative: Variant B increases 7-day subscription conversion.
  direction: increase
population:
  randomization_unit: player
  analysis_unit: player
  eligibility: Players who open the offer page and are not subscribed at exposure.
  daily_eligible_units: 4200
  exposure_trigger: offer_page_view
arms:
  - {name: control, allocation: 0.5, is_control: true}
  - {name: variant_b, allocation: 0.5}
primary_metric:
  name: subscription_conversion_7d
  kind: binary
  baseline: 0.032
  baseline_std: null
  governed_reference: docs/metrics/hybrid_subscription.md
guardrails:
  - name: refund_rate_14d
    kind: binary
    baseline: 0.018
    harmful_direction: increase
    tolerance_relative: 0.10
design:
  mde_relative: 0.05
  alpha: 0.05
  power: 0.80
  sided: two_sided
  planned_duration_days: 14
  min_duration_days: 14
"""


def _error(text: str) -> str:
    with pytest.raises(LoadError) as caught:
        parse_spec(text, source="spec.yaml")
    return str(caught.value)


# --- Reading a good file ---------------------------------------------------------------


def test_the_section_6_example_in_yaml_is_the_same_spec_as_its_dict(raw_spec: dict) -> None:
    from_yaml = parse_spec(SECTION_6_YAML)

    assert from_yaml == ExperimentSpec.from_dict(raw_spec)
    assert from_yaml.sha256() == ExperimentSpec.from_dict(raw_spec).sha256()


def test_how_the_yaml_is_laid_out_does_not_change_the_spec() -> None:
    commented = "# pre-registered\n" + SECTION_6_YAML.replace("alpha: 0.05", "alpha: 0.05  # 5%")
    flow_style = SECTION_6_YAML.replace(
        "design:\n  mde_relative: 0.05\n  alpha: 0.05\n  power: 0.80\n  sided: two_sided\n"
        "  planned_duration_days: 14\n  min_duration_days: 14\n",
        "design: {sided: two_sided, power: 0.80, alpha: 0.05, mde_relative: 0.05,\n"
        "  min_duration_days: 14, planned_duration_days: 14}\n",
    )

    assert flow_style != SECTION_6_YAML
    assert parse_spec(commented).sha256() == parse_spec(SECTION_6_YAML).sha256()
    assert parse_spec(flow_style).sha256() == parse_spec(SECTION_6_YAML).sha256()


def test_the_same_key_in_different_mappings_is_not_a_duplicate() -> None:
    """Every arm has a `name`, and so does the primary metric."""
    assert parse_spec(SECTION_6_YAML).arms[0].name == "control"


def test_an_unused_anchor_is_harmless() -> None:
    assert parse_spec(SECTION_6_YAML.replace("owner: analytics", "owner: &o analytics")).owner == (
        "analytics"
    )


# --- Duplicate keys --------------------------------------------------------------------


def test_a_repeated_key_is_refused_with_both_lines() -> None:
    text = SECTION_6_YAML.replace("owner: analytics\n", "owner: analytics\ntitle: Another\n")

    assert _error(text) == "spec.yaml:5:1: duplicate key 'title' (first given on line 3)"


def test_a_repeated_key_inside_a_section_is_refused() -> None:
    text = SECTION_6_YAML.replace("  alpha: 0.05\n", "  alpha: 0.05\n  alpha: 0.01\n")

    assert _error(text) == "spec.yaml:33:3: duplicate key 'alpha' (first given on line 32)"


def test_a_repeated_key_in_a_flow_mapping_is_refused() -> None:
    text = SECTION_6_YAML.replace("{name: variant_b, allocation: 0.5}", "{name: b, name: c}")

    assert "duplicate key 'name'" in _error(text)


def test_pyyaml_alone_would_have_kept_the_last_value() -> None:
    """The reason this module exists."""
    assert yaml.safe_load("title: first\ntitle: second\n") == {"title": "second"}


# --- Keys that YAML does not read as text ----------------------------------------------


@pytest.mark.parametrize("spelling", ["null", "Null", "NULL", "~"])
def test_an_unquoted_null_key_says_to_quote_it(spelling: str) -> None:
    text = SECTION_6_YAML.replace('  "null":', f"  {spelling}:")

    assert _error(text) == (
        f"spec.yaml:6:3: key {spelling!r} is read by YAML as null, not as text; "
        'if you mean the field called null, quote it: "null":'
    )


@pytest.mark.parametrize(
    ("spelling", "reading"), [("on", "true"), ("yes", "true"), ("off", "false")]
)
def test_a_key_yaml_reads_as_a_boolean_is_refused(spelling: str, reading: str) -> None:
    text = SECTION_6_YAML.replace("design:", f"{spelling}: 1\ndesign:")

    assert _error(text).endswith(
        f'key {spelling!r} is read by YAML as {reading}, not as text; quote it: "{spelling}":'
    )


def test_a_numeric_key_is_refused() -> None:
    assert _error("1: a\n") == "spec.yaml:1:1: key '1' is not text; quote it: \"1\":"


def test_a_list_used_as_a_key_is_refused() -> None:
    assert _error("? [a, b]\n: 1\n") == "spec.yaml:1:3: a key must be text, not a list or a mapping"


def test_a_quoted_null_key_is_text() -> None:
    assert parse_spec(SECTION_6_YAML).hypothesis.null.startswith("The offer page variant")


# --- Aliases, merge keys, tags ---------------------------------------------------------


def test_an_alias_is_refused() -> None:
    text = SECTION_6_YAML.replace("owner: analytics", "owner: &o analytics").replace(
        "title: Subscription offer page variants", "title: *o"
    )

    assert _error(text) == (
        "spec.yaml:3:8: alias *o is not allowed in a spec; write the value out where it is used"
    )


def test_a_merge_key_is_refused() -> None:
    text = SECTION_6_YAML.replace("design:\n", "design:\n  <<: {alpha: 0.01}\n")

    assert _error(text) == "spec.yaml:31:3: merge keys (<<) are not allowed in a spec"


def test_a_python_object_tag_is_refused_and_nothing_runs(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    text = f"title: !!python/object/apply:os.system ['touch {marker}']\n"

    message = _error(text)

    assert "could not determine a constructor" in message
    assert not marker.exists()


# --- Text that is not YAML, or not one document ----------------------------------------


def test_a_syntax_error_names_the_line_and_column() -> None:
    assert _error("a: 1\nb: [1, 2\nc: 3\n") == (
        "spec.yaml:3:2: while parsing a flow sequence: expected ',' or ']', but got ':'"
    )


def test_a_tab_in_the_indentation_is_a_located_error() -> None:
    message = _error("design:\n\talpha: 0.05\n")

    assert message.startswith("spec.yaml:2:1: ")


def test_two_documents_are_refused() -> None:
    assert _error("a: 1\n---\nb: 2\n") == (
        "spec.yaml:2:1: expected a single document in the stream, but found another document"
    )


def test_a_control_character_is_refused_without_a_position_crash() -> None:
    assert _error("title: \x07\n").startswith("spec.yaml: ")


# --- Valid YAML that is not a spec: the spec's own errors pass through -----------------


@pytest.mark.parametrize("text", ["", "# only a comment\n", "5\n", "- a\n- b\n"])
def test_valid_yaml_that_is_not_a_mapping_is_a_spec_error(text: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(text)

    assert caught.value.violations[0].startswith("spec: must be a mapping")


def test_a_mapping_with_bad_values_lists_every_violation() -> None:
    text = SECTION_6_YAML.replace("alpha: 0.05", "alpha: 2").replace("power: 0.80", "power: 0")

    with pytest.raises(SpecError) as caught:
        parse_spec(text)

    assert len(caught.value.violations) == 2


def test_a_number_yaml_reads_as_text_is_reported_by_the_spec() -> None:
    """YAML 1.1 needs a dot: `5e-2` is a string, so it must be written 0.05 or 5.0e-2."""
    text = SECTION_6_YAML.replace("mde_relative: 0.05", "mde_relative: 5e-2")

    with pytest.raises(SpecError) as caught:
        parse_spec(text)

    assert caught.value.violations == ("design.mde_relative: must be a finite number, got '5e-2'",)
    assert parse_spec(text.replace("5e-2", "5.0e-2")).design.mde_relative == 0.05


# --- Files -----------------------------------------------------------------------------


def test_a_file_loads_and_errors_name_its_path(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(SECTION_6_YAML, encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: 1\na: 2\n", encoding="utf-8")

    assert load_spec(good) == parse_spec(SECTION_6_YAML)
    with pytest.raises(LoadError, match=rf"^{bad}:2:1: duplicate key 'a'"):
        load_spec(bad)


def test_a_path_may_be_a_string(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(SECTION_6_YAML, encoding="utf-8")

    assert load_spec(str(path)).id == "hybrid_offer_page_2026_10"


def test_a_missing_file_is_a_load_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"

    with pytest.raises(LoadError, match=rf"^{missing}: cannot be read: No such file"):
        load_spec(missing)


def test_a_directory_is_a_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match=r"cannot be read"):
        load_spec(tmp_path)


def test_a_file_that_is_not_utf_8_is_a_load_error(tmp_path: Path) -> None:
    path = tmp_path / "latin1.yaml"
    path.write_bytes("title: caf\xe9\n".encode("latin-1"))

    with pytest.raises(LoadError, match=rf"^{path}: not valid UTF-8 \(at byte offset 10\)"):
        load_spec(path)


def test_a_byte_order_mark_and_windows_line_endings_are_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "windows.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + SECTION_6_YAML.replace("\n", "\r\n").encode("utf-8"))

    assert load_spec(path) == parse_spec(SECTION_6_YAML)


def test_non_ascii_text_survives_the_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "unicode.yaml"
    path.write_text(SECTION_6_YAML.replace("analytics", "analytics – Café"), encoding="utf-8")

    assert load_spec(path).owner == "analytics – Café"


def test_a_spec_error_from_a_file_passes_through_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("a: 1\n", encoding="utf-8")

    with pytest.raises(SpecError) as caught:
        load_spec(path)

    assert any(v.startswith("referee_spec_version") for v in caught.value.violations)


# --- The error type --------------------------------------------------------------------


def test_a_load_error_is_a_value_error_and_survives_pickling() -> None:
    error = LoadError("spec.yaml:3:1: duplicate key 'a' (first given on line 1)")

    assert isinstance(error, ValueError)
    assert str(pickle.loads(pickle.dumps(error))) == str(error)


def test_an_error_without_a_position_is_reported_with_the_source_alone() -> None:
    """PyYAML errors normally carry a mark; the helpers must not assume it."""
    assert _where("spec.yaml", None) == "spec.yaml"
    assert _problem("spec.yaml", yaml.MarkedYAMLError(problem="boom")) == "spec.yaml: boom"
    assert _problem("spec.yaml", yaml.YAMLError("first line\nsecond")) == "spec.yaml: first line"


def test_an_unquoted_utc_start_which_yaml_reads_as_a_datetime_is_accepted() -> None:
    quoted = SECTION_6_YAML + '  start_utc: "2026-11-02T00:00:00Z"\n'
    unquoted = SECTION_6_YAML + "  start_utc: 2026-11-02T00:00:00Z\n"

    assert parse_spec(unquoted).design.start_utc == "2026-11-02T00:00:00Z"
    assert parse_spec(unquoted).sha256() == parse_spec(quoted).sha256()


def test_an_unquoted_date_as_the_start_is_refused_because_it_names_no_instant() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(SECTION_6_YAML + "  start_utc: 2026-11-02\n")

    assert len(caught.value.violations) == 1
    assert caught.value.violations[0].startswith("design.start_utc: must be an ISO 8601 timestamp")


# --- A timestamp YAML cannot build ---------------------------------------------------------------

IMPOSSIBLE_TIMESTAMPS = [
    "2026-02-30T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-11-02T24:00:00Z",
    "2026-11-02T00:00:00+24:00",
    "2026-11-02T00:00:00+99:00",
    "0000-01-01T00:00:00Z",
]


@pytest.mark.parametrize("stamp", IMPOSSIBLE_TIMESTAMPS)
def test_an_unquoted_timestamp_that_cannot_exist_is_a_load_error_not_a_bare_value_error(
    stamp: str,
) -> None:
    text = SECTION_6_YAML.replace("alpha:", f"start_utc: {stamp}\n  alpha:", 1)
    assert stamp in text

    with pytest.raises(LoadError) as caught:
        parse_spec(text, source="spec.yaml")

    assert str(caught.value).startswith("spec.yaml: ")
    assert caught.value.__cause__ is not None
    assert "if this is meant as text, quote it" in str(caught.value)


def test_the_same_impossible_timestamp_quoted_is_still_a_spec_error_naming_the_field() -> None:
    from referee.spec import SpecError

    text = SECTION_6_YAML.replace("alpha:", 'start_utc: "2026-02-30T00:00:00Z"\n  alpha:', 1)

    with pytest.raises(SpecError, match=r"design\.start_utc"):
        parse_spec(text)


def test_a_valid_unquoted_timestamp_is_still_accepted() -> None:
    text = SECTION_6_YAML.replace("alpha:", "start_utc: 2026-11-02T00:00:00Z\n  alpha:", 1)

    assert parse_spec(text).design.start_utc == "2026-11-02T00:00:00Z"


def test_the_load_errors_the_loader_raises_itself_are_not_wrapped_again() -> None:
    with pytest.raises(LoadError) as caught:
        parse_spec("a: 1\na: 2\n", source="spec.yaml")

    assert str(caught.value) == "spec.yaml:2:1: duplicate key 'a' (first given on line 1)"
