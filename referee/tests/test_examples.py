r"""The example specs in examples/ and their golden outputs in tests/golden/.

A golden file is the command's exact output. To regenerate one after a change you meant to
make, from the referee/ folder:

    python -m referee review-design examples/NAME.yaml > tests/golden/NAME.txt
    python -m referee review-design examples/NAME.yaml --format json > tests/golden/NAME.json

then read the diff: the checks below also say what the output must mean, so a regenerated
golden file that is wrong still fails.

The results example is read against the committed lab export; regenerate its golden with

    python -m referee review-results examples/offer-page-results.yaml \
        tests/data/hybrid_offer_page_5000 --experiment-id hybrid_offer_page \
        --as-of 2026-06-30T00:00:00Z --format json > tests/golden/offer-page-results.json

Its test compares the numbers and the layout. A float may differ in its last digits between
machines, and the sentences (titles, explanations, advice, notes, summary lines and the
description of the effect's population) are not compared: reading them is a person's job.

The decision memo and the text report of the same review are pinned byte for byte, because
their sentences are what a reader acts on; regenerate them with the same command and
`--format memo`, to `tests/golden/offer-page-results.md`, and with no `--format`, to
`tests/golden/offer-page-results.txt`, and read the diff before keeping either.
"""

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from referee.cli import main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"

EXIT_STATUS = {"offer-page-underpowered": 1, "offer-page-powered": 0}
NAMES = sorted(EXIT_STATUS)


def _paths(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        flat: dict[str, object] = {}
        for key, item in value.items():
            flat.update(_paths(item, f"{prefix}{key}."))
        return flat
    return {prefix.rstrip("."): value}


PROSE = frozenset(
    {
        "title",
        "why_it_matters",
        "remediation",
        "references",
        "notes",
        "line",
        "summary_lines",
        "population",
    }
)


def _differences(actual: Any, expected: Any, path: str = "$") -> list[str]:
    """Where two reports differ: floats to nine digits, sentences (`PROSE` keys) not at all.

    The layout is compared with the numbers: the keys of every dict and their order, the length
    of every list outside the sentences. A `PROSE` key holding a dict (the population of the
    report) is compared like any other.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or list(actual) != list(expected):
            return [f"{path}: the keys differ"]
        return [
            found
            for key in expected
            for found in (
                []
                if key in PROSE and not isinstance(expected[key], dict)
                else _differences(actual[key], expected[key], f"{path}.{key}")
            )
        ]
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [f"{path}: the lengths differ"]
        return [
            found
            for i, (a, e) in enumerate(zip(actual, expected, strict=True))
            for found in _differences(a, e, f"{path}[{i}]")
        ]
    if isinstance(expected, float):
        same = isinstance(actual, int | float) and math.isclose(
            actual, expected, rel_tol=1e-9, abs_tol=1e-12
        )
    else:
        same = type(actual) is type(expected) and actual == expected
    return [] if same else [f"{path}: {actual!r} is not {expected!r}"]


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- The folders agree -----------------------------------------------------------------


# --- Golden output ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["offer-page-powered"])
def test_the_json_output_is_the_golden_file(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "review-design", str(EXAMPLES / f"{name}.yaml"), "--format", "json")

    assert code == EXIT_STATUS[name]
    assert out == (GOLDEN / f"{name}.json").read_text(encoding="utf-8")


def test_the_results_json_is_the_golden_file_in_its_numbers_and_layout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = _run(
        capsys,
        "review-results",
        str(EXAMPLES / "offer-page-results.yaml"),
        str(ROOT / "tests" / "data" / "hybrid_offer_page_5000"),
        "--experiment-id",
        "hybrid_offer_page",
        "--as-of",
        "2026-06-30T00:00:00Z",
        "--format",
        "json",
    )

    golden = json.loads((GOLDEN / "offer-page-results.json").read_text(encoding="utf-8"))
    report = json.loads(out)
    assert code == 1
    assert _differences(report, golden) == []
    assert report["blocking_rule_ids"] == ["RES-001", "RES-002"]
    assert [f["rule_id"] for f in report["findings"]] == [
        "RES-001",
        "RES-002",
        "RES-007",
        "RES-008",
        "RES-012",
        "RES-013",
    ]


@pytest.mark.parametrize(("format_", "golden"), [("memo", "md"), ("text", "txt")])
def test_the_results_memo_and_text_are_the_golden_files(
    format_: str, golden: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(
        capsys,
        "review-results",
        str(EXAMPLES / "offer-page-results.yaml"),
        str(ROOT / "tests" / "data" / "hybrid_offer_page_5000"),
        "--experiment-id",
        "hybrid_offer_page",
        "--as-of",
        "2026-06-30T00:00:00Z",
        "--format",
        format_,
    )

    assert code == 1
    assert out == (GOLDEN / f"offer-page-results.{golden}").read_text(encoding="utf-8")


def test_a_difference_in_a_number_is_found_and_one_in_a_sentence_is_not() -> None:
    golden = {"p": 0.5, "n": 3, "findings": [{"rule_id": "A", "remediation": "Do this."}]}

    same = {"p": 0.5 + 1e-12, "n": 3, "findings": [{"rule_id": "A", "remediation": "Do that."}]}

    assert _differences(same, golden) == []
    assert _differences({**same, "p": 0.51}, golden) == ["$.p: 0.51 is not 0.5"]
    assert _differences({**same, "n": 4}, golden) == ["$.n: 4 is not 3"]
    assert _differences({**same, "n": 3.0}, golden) == ["$.n: 3.0 is not 3"]  # a type change
    assert _differences({**same, "extra": 1}, golden) == ["$: the keys differ"]
    assert _differences({"n": 3, "p": 0.5, "findings": same["findings"]}, golden) == [
        "$: the keys differ"
    ]  # the order of the keys is layout


@pytest.mark.parametrize(
    "key", ["title", "line", "population", "summary_lines", "notes", "remediation"]
)
def test_what_is_written_in_a_sentence_field_is_not_compared(key: str) -> None:
    assert _differences({key: "this"}, {key: "that"}) == []
    assert _differences({key: ["this"]}, {key: ["that", "and more"]}) == []


def test_a_field_named_for_a_sentence_that_holds_numbers_is_compared() -> None:
    assert _differences({"population": {"n": 2}}, {"population": {"n": 1}}) == [
        "$.population.n: 2 is not 1"
    ]


# --- What the golden files must mean ---------------------------------------------------


# --- As a user would run it ------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_command_in_each_examples_header_gives_the_golden_text(name: str) -> None:
    """Run from the referee/ folder with a relative path, exactly as the header says."""
    result = subprocess.run(
        [sys.executable, "-m", "referee", "review-design", f"examples/{name}.yaml"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == EXIT_STATUS[name]
    assert result.stdout == (GOLDEN / f"{name}.txt").read_text(encoding="utf-8")
    assert result.stderr == ""
