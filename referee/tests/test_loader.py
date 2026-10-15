"""Reading a spec from YAML: what is accepted, and the traps PyYAML would let through."""

from pathlib import Path

import pytest
import yaml

from referee.loader import LoadError, _problem, _where, load_spec, parse_spec
from referee.spec import SpecError

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


# --- Duplicate keys --------------------------------------------------------------------


# --- Keys that YAML does not read as text ----------------------------------------------


@pytest.mark.parametrize("spelling", ["NULL"])
def test_an_unquoted_null_key_says_to_quote_it(spelling: str) -> None:
    text = SECTION_6_YAML.replace('  "null":', f"  {spelling}:")

    assert _error(text) == (
        f"spec.yaml:6:3: key {spelling!r} is read by YAML as null, not as text; "
        'if you mean the field called null, quote it: "null":'
    )


@pytest.mark.parametrize(("spelling", "reading"), [("off", "false")])
def test_a_key_yaml_reads_as_a_boolean_is_refused(spelling: str, reading: str) -> None:
    text = SECTION_6_YAML.replace("design:", f"{spelling}: 1\ndesign:")

    assert _error(text).endswith(
        f'key {spelling!r} is read by YAML as {reading}, not as text; quote it: "{spelling}":'
    )


def test_a_numeric_key_is_refused() -> None:
    assert _error("1: a\n") == "spec.yaml:1:1: key '1' is not text; quote it: \"1\":"


def test_a_list_used_as_a_key_is_refused() -> None:
    assert _error("? [a, b]\n: 1\n") == "spec.yaml:1:3: a key must be text, not a list or a mapping"


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


# --- Text that is not YAML, or not one document ----------------------------------------


def test_a_syntax_error_names_the_line_and_column() -> None:
    assert _error("a: 1\nb: [1, 2\nc: 3\n") == (
        "spec.yaml:3:2: while parsing a flow sequence: expected ',' or ']', but got ':'"
    )


def test_two_documents_are_refused() -> None:
    assert _error("a: 1\n---\nb: 2\n") == (
        "spec.yaml:2:1: expected a single document in the stream, but found another document"
    )


# --- Valid YAML that is not a spec: the spec's own errors pass through -----------------


def test_a_number_yaml_reads_as_text_is_reported_by_the_spec() -> None:
    """YAML 1.1 needs a dot: `5e-2` is a string, so it must be written 0.05 or 5.0e-2."""
    text = SECTION_6_YAML.replace("mde_relative: 0.05", "mde_relative: 5e-2")

    with pytest.raises(SpecError) as caught:
        parse_spec(text)

    assert caught.value.violations == ("design.mde_relative: must be a finite number, got '5e-2'",)
    assert parse_spec(text.replace("5e-2", "5.0e-2")).design.mde_relative == 0.05


# --- Files -----------------------------------------------------------------------------


def test_a_file_that_is_not_utf_8_is_a_load_error(tmp_path: Path) -> None:
    path = tmp_path / "latin1.yaml"
    path.write_bytes("title: caf\xe9\n".encode("latin-1"))

    with pytest.raises(LoadError, match=rf"^{path}: not valid UTF-8 \(at byte offset 10\)"):
        load_spec(path)


def test_a_spec_error_from_a_file_passes_through_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("a: 1\n", encoding="utf-8")

    with pytest.raises(SpecError) as caught:
        load_spec(path)

    assert any(v.startswith("referee_spec_version") for v in caught.value.violations)


# --- The error type --------------------------------------------------------------------


def test_an_error_without_a_position_is_reported_with_the_source_alone() -> None:
    """PyYAML errors normally carry a mark; the helpers must not assume it."""
    assert _where("spec.yaml", None) == "spec.yaml"
    assert _problem("spec.yaml", yaml.MarkedYAMLError(problem="boom")) == "spec.yaml: boom"
    assert _problem("spec.yaml", yaml.YAMLError("first line\nsecond")) == "spec.yaml: first line"


# --- A timestamp YAML cannot build ---------------------------------------------------------------

IMPOSSIBLE_TIMESTAMPS = [
    "2026-02-30T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-11-02T24:00:00Z",
    "2026-11-02T00:00:00+24:00",
    "2026-11-02T00:00:00+99:00",
    "0000-01-01T00:00:00Z",
]


