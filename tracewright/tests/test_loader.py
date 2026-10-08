import pytest

from tracewright.loader import LoadError, load_plan, parse_plan
from tracewright.plan import PlanError

MINIMAL = """\
tracewright_plan_version: 1
id: p
title: P
identity_keys: [user_id]
events:
  - name: a_b
"""


def test_minimal_plan_parses():
    assert parse_plan(MINIMAL).events[0].name == "a_b"


def test_duplicate_keys_are_refused_with_a_line():
    with pytest.raises(LoadError, match=r"<string>:\d+:\d+: duplicate key 'id'"):
        parse_plan(MINIMAL + "id: q\n")


def test_aliases_are_refused():
    text = MINIMAL.replace("[user_id]", "&k [user_id]") + "x: *k\n"
    with pytest.raises(LoadError, match="alias"):
        parse_plan(text)


def test_merge_keys_are_refused():
    with pytest.raises(LoadError, match="merge keys"):
        parse_plan("<<: {a: 1}\n")


def test_a_key_yaml_reads_as_a_boolean_is_refused():
    with pytest.raises(LoadError, match="quote it"):
        parse_plan("on: 1\n")


def test_broken_yaml_is_a_load_error():
    with pytest.raises(LoadError):
        parse_plan("a: [unclosed\n")


def test_a_mapping_that_is_not_a_plan_is_a_plan_error():
    with pytest.raises(PlanError):
        parse_plan("id: p\n")


def test_missing_and_binary_files(tmp_path):
    with pytest.raises(LoadError, match="cannot be read"):
        load_plan(tmp_path / "nope.yaml")
    binary = tmp_path / "b.yaml"
    binary.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(LoadError, match="not valid UTF-8"):
        load_plan(binary)
