"""The design-review and results-review reports and their renderings."""

import json
import re
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, crowd, results_spec

from referee import __version__
from referee.findings import DesignReview, Finding, ResultsReview
from referee.report import (
    MEMO_HEADINGS,
    _md_code,
    _md_text,
    design_report,
    render_json,
    render_results_memo,
    render_results_text,
    render_text,
    results_report,
)
from referee.results import ResultsContext
from referee.review import origin_sensitivity, review_context
from referee.rules import RESULTS_RULES
from referee.spec import ExperimentSpec

SECTION_6_SHA256 = "b0332774feccd582db109bfffff10e1330ce418ab28471ccb625fe0b00af10e8"


def finding(rule_id: str, severity: str, **overrides: object) -> Finding:
    fields: dict = {
        "rule_id": rule_id,
        "severity": severity,
        "title": f"Title of {rule_id}",
        "evidence": {},
        "why_it_matters": f"Why {rule_id} matters.",
        "remediation": f"How to fix {rule_id}.",
        "references": (),
    }
    return Finding(**{**fields, **overrides})


def make_report(raw_spec: dict, *findings: Finding) -> dict:
    spec = ExperimentSpec.from_dict(raw_spec)
    return design_report(spec, DesignReview(spec_id=spec.id, findings=findings))


# --- The report ------------------------------------------------------------------------


# --- JSON ------------------------------------------------------------------------------


def test_the_json_is_ascii_even_when_the_spec_is_not(raw_spec: dict) -> None:
    raw_spec["title"] = "Café – offer page"

    text = render_json(make_report(raw_spec))

    assert text.isascii()
    assert json.loads(text)["spec"]["title"] == "Café – offer page"


def test_the_json_refuses_a_non_finite_number(raw_spec: dict) -> None:
    report = make_report(raw_spec, finding("DES-001", "blocker", evidence={"x": float("nan")}))

    with pytest.raises(ValueError, match="not JSON compliant"):
        render_json(report)


# --- Text ------------------------------------------------------------------------------


# --- The results report ----------------------------------------------------------------

HASHES = {"experiment_assignments.csv": "a" * 64}


def _context(
    raw_spec: dict, rows: list[Row], *, exported_at=None, window_column=True, **changes: object
):
    data = build_data(rows, exported_at=exported_at, window_column=window_column)
    return ResultsContext.of(results_spec(raw_spec, **changes), data)


UNCHANGED = {
    "ran": True,
    "reason": None,
    "shifts": [
        {"days_earlier": d, "same": True, "verdict": "clear", "appear": [], "disappear": []}
        for d in range(1, 7)
    ],
}


def _report(
    context: ResultsContext,
    review: ResultsReview | None = None,
    source=None,
    sensitivity: dict | None = None,
) -> dict:
    review = review or review_context(context)
    return results_report(
        review,
        context,
        file_hashes=HASHES,
        as_of_source=source,
        sensitivity=sensitivity or UNCHANGED,
    )


def test_the_report_states_the_origin_the_first_and_last_assignment_and_who_was_left_out(
    raw_spec: dict,
) -> None:
    rows = [
        *crowd("control", 2, assigned_at=at(1)),
        Row("never_exposed", "variant_b", assigned_at=at(3), exposed_at=None),
        Row("variant_b_0", "variant_b", assigned_at=at(2)),
        Row("early_b", "variant_b", assigned_at=at(-2)),
        Row("early_c", "variant_c", assigned_at=at(-1)),
        Row("variant_c_0", "variant_c", assigned_at=at(5)),
    ]

    registered = _report(_context(raw_spec, rows, design__start_utc="2026-04-11T00:00:00Z"))
    unregistered = _report(_context(raw_spec, rows))

    assert registered["population"] == {
        "origin": "2026-04-11T00:00:00Z",
        "origin_source": "design.start_utc",
        "first_assignment": "2026-04-12T00:00:00Z",
        "last_assignment": "2026-04-16T00:00:00Z",
        "observed_days": 4,
        "planned_duration_days": 14,
        "assigned": {"control": 2, "variant_b": 2, "variant_c": 1},
        "analysed": {"control": 2, "variant_b": 1, "variant_c": 1},
        "ignored_before_start": ["early_b", "early_c"],
        "kind_declared": None,
        "first_seen": None,
    }
    assert registered["data"] == {"files": {"experiment_assignments.csv": {"sha256": "a" * 64}}}
    assert unregistered["population"]["origin"] == "2026-04-09T00:00:00Z"
    assert unregistered["population"]["origin_source"] == "first assignment"
    assert unregistered["population"]["ignored_before_start"] == []


@pytest.mark.parametrize(
    ("taken", "interim"),
    [(None, None), (at(20, 23.99), True), (at(21), False), (at(40), False)],
)
def test_a_run_is_interim_until_the_planned_end_and_unknown_without_a_time(
    raw_spec: dict, taken, interim: bool | None
) -> None:
    """14 planned days of assignment from the origin, then the 7 days of the last outcomes."""
    rows = [*crowd("control", 2), *crowd("variant_b", 2), *crowd("variant_c", 2)]

    as_of = _report(_context(raw_spec, rows, exported_at=taken), source="manifest")["as_of"]

    assert as_of["interim"] is interim
    assert as_of["source"] == (None if taken is None else "manifest")
    assert as_of["planned_end"] == (None if taken is None else "2026-05-02T00:00:00Z")


def test_the_planned_end_counts_from_the_registered_start_not_from_the_first_assignment(
    raw_spec: dict,
) -> None:
    rows = [*crowd("control", 2, assigned_at=at(3)), *crowd("variant_b", 2, assigned_at=at(3))]
    context = _context(raw_spec, rows, exported_at=at(22), design__start_utc="2026-04-11T00:00:00Z")

    as_of = _report(context, source="command line")["as_of"]

    assert (as_of["planned_end"], as_of["interim"]) == ("2026-05-02T00:00:00Z", False)


def test_the_report_always_carries_the_line_of_each_effect_rule_that_ran(raw_spec: dict) -> None:
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])
    fired = Finding(
        rule_id="RES-007",
        severity="warning",
        title="t",
        evidence={"summary": {"line": "RES-007: its own line"}},
        why_it_matters="w",
        remediation="r",
        references=(),
    )
    review = ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=(fired,),
    )
    only_sample_ratio = review_context(context, rules=RESULTS_RULES[:1])

    lines = _report(context, review)["summary_lines"]

    assert [line.split(":")[0] for line in lines] == ["RES-004", "RES-007", "RES-008"]
    assert lines[1] == "RES-007: its own line"
    assert lines[0].startswith("RES-004: ") and lines[2].startswith("RES-008: ")
    assert _report(context, only_sample_ratio)["summary_lines"] == []


def _short(*arms: str, required: int = 2_000, analysed: int = 1_234) -> dict:
    """The evidence of a sized RES-002: the arms that fall short, with their numbers."""
    every = ("control", "variant_b", "variant_c")
    return {
        "required": {arm: required for arm in every},
        "analysed": {arm: analysed if arm in arms else required for arm in every},
        "assigned": {arm: 2 * required for arm in every},
        "short_arms": list(arms),
        "missing": {arm: required - analysed for arm in arms},
    }


def _blocked(
    context: ResultsContext,
    *blocking: str,
    warnings: tuple[str, ...] = (),
    evidence: dict[str, dict] | None = None,
) -> ResultsReview:
    """A review of `context` whose findings are blockers for `blocking` and warnings for
    `warnings`, each with a one-line summary of its own (RES-002 has the evidence of a sized
    one, with `variant_b` short); `evidence` replaces the evidence of the rules it names."""
    own = {"RES-002": _short("variant_b"), **(evidence or {})}
    found = tuple(
        Finding(
            rule_id=rule_id,
            severity=severity,
            title="t",
            evidence={**own.get(rule_id, {}), "summary": {"line": f"{rule_id}: line"}},
            why_it_matters="w",
            remediation="r",
            references=(),
        )
        for severity, rule_ids in (("blocker", blocking), ("warning", warnings))
        for rule_id in rule_ids
    )
    return ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=found,
    )


def test_blocking_rules_are_grouped_into_data_validity_and_harm(raw_spec: dict) -> None:
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])
    review = _blocked(context, "RES-001", "RES-004", "RES-012")

    report = _report(context, review)

    assert report["blocking_rule_ids"] == ["RES-001", "RES-004", "RES-012"]
    assert report["blocking_groups"] == {
        "data_validity": ["RES-001", "RES-012"],
        "harm": ["RES-004"],
    }
    assert "Blocking rules: data validity RES-001, RES-012; harm RES-004\n" in (
        render_results_text(report)
    )


def _finding_with(rule_id: str, evidence: dict, **overrides: object) -> Finding:
    return finding(rule_id, "warning", evidence=evidence, **overrides)


def _text_of(raw_spec: dict, *found: Finding, **options: int) -> str:
    raw_spec = {**raw_spec, "title": "A spec title that is much too long for one line " * 3}
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])
    review = ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=found,
    )
    return render_results_text(_report(context, review), **options)


def test_the_evidence_of_a_finding_is_printed_in_full_as_indented_lines(raw_spec: dict) -> None:
    evidence = {
        "alpha": 0.001,
        "p_value": 6.7296123e-10,
        "assigned": {"control": 997, "variant_b": 12345},
        "used": True,
        "missing": None,
        "ids": ["a", "b"],
        "weeks": [{"week": 0, "n": 3}, {"week": 1, "n": 4}],
        "none_yet": [],
    }

    long_title = "A title that runs on and on " * 5
    text = _text_of(raw_spec, _finding_with("RES-001", evidence, title=long_title))

    lines = text.splitlines()
    spec_line = next(i for i, line in enumerate(lines) if line.startswith("Spec:"))
    assert lines[spec_line + 1].startswith(" " * 12) and lines[spec_line + 1][12] != " "
    heading = text.split("[WARNING] RES-001: ")[1].split("\n    Why it matters")[0]
    assert " ".join(heading.split()) == long_title.strip()  # all of it, wrapped
    assert all(len(line) <= 100 for line in text.splitlines())
    assert (
        "    Evidence:\n"
        + "\n".join(
            [
                "      alpha: 0.001",
                "      p_value: 6.72961e-10",
                "      assigned:",
                "        control: 997",
                "        variant_b: 12,345",
                "      used: yes",
                "      missing: none",
                "      ids: a, b",
                "      weeks:",
                "        - week: 0",
                "          n: 3",
                "        - week: 1",
                "          n: 4",
                "      none_yet: []",
            ]
        )
        + "\n"
        in text
    )


def test_an_effect_rule_prints_its_sentences_and_leaves_its_tables_to_the_json(
    raw_spec: dict,
) -> None:
    evidence = {
        "summary": {"line": "RES-007: 1 tests"},
        "settings": {},
        "plans": {},
        "tests": [{"secret": "ONLY-IN-THE-JSON"}],
        "notes": ["The first sentence.", "The second sentence " + "that goes on " * 12 + "ends."],
    }

    text = _text_of(raw_spec, _finding_with("RES-007", evidence))

    block = text.split("    Evidence:\n")[1].split("\n\n")[0].splitlines()
    assert block[0] == "      - The first sentence."
    assert sum(line.startswith("      - ") for line in block) == 2  # one bullet a sentence
    assert all(len(line) <= 88 for line in block)  # a long sentence is wrapped under its bullet
    assert len(block) > 4
    assert any(line.startswith(" " * 8) and line[8] != " " for line in block[1:])  # the hang
    assert "JSON report" in text
    assert "ONLY-IN-THE-JSON" not in text


def test_a_long_list_is_cut_when_shown_and_nothing_else_changes(raw_spec: dict) -> None:
    ids = [f"p{i:04d}" for i in range(2_500)]
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])
    review = ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=(
            _finding_with(
                "RES-001", {"players": ids[:1_500], "rows": [{"n": i} for i in range(1_200)]}
            ),
        ),
    )
    report = _report(context, review)
    report["population"]["ignored_before_start"] = ids
    saved = json.dumps(report)

    cut = render_results_text(report)
    whole = render_results_text(report, limit=10_000)

    assert json.dumps(report) == saved  # the report holds every row, whatever is shown
    assert "p0999" in cut and "p1000" not in cut
    assert "n: 999\n" in cut and "n: 1000\n" not in cut and "n: 1,000\n" not in cut
    assert cut.count("(showing 1,000 of 1,200; the full list is in the JSON report)") == 1
    assert cut.count("(showing 1,000 of 2,500; the full list is in the JSON report)") == 1
    assert cut.count("(showing 1,000 of 1,500; the full list is in the JSON report)") == 1
    assert "p2499" in whole and "p1499" in whole and "n: 1,199\n" in whole
    assert "showing" not in whole

    def facts(text: str) -> list[str]:
        keys = ("Verdict:", "Blocking rules:", "Findings:", "Ignored:", "Assigned:", "  control:")
        return [line for line in text.splitlines() if line.startswith(keys)]

    assert facts(cut) == facts(whole)


def test_the_report_says_whether_the_findings_hold_for_earlier_origins(raw_spec: dict) -> None:
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])
    differences = {
        1: {"verdict": "clear", "appear": [], "disappear": ["RES-008:warning"]},
        2: {"verdict": "caution", "appear": ["RES-007:warning"], "disappear": []},
        5: {"verdict": "caution", "appear": ["RES-007:warning"], "disappear": []},
    }
    changed = {
        **UNCHANGED,
        "shifts": [
            {**shift, "same": False, **differences[shift["days_earlier"]]}
            if shift["days_earlier"] in differences
            else shift
            for shift in UNCHANGED["shifts"]
        ],
    }
    not_run = {"ran": False, "reason": "design.start_utc is registered", "shifts": []}

    held = " ".join(render_results_text(_report(context)).split())
    differs = render_results_text(_report(context, sensitivity=changed))
    skipped = render_results_text(_report(context, sensitivity=not_run))

    assert "Origin sensitivity: the same rules fire at the same severity for origins 1 to 6" in held
    assert "Origin sensitivity: the rules that fire change with the origin.\n" in differs
    assert "  1 day earlier: verdict clear; disappear RES-008:warning\n" in differs
    assert "  2 days earlier: verdict caution; appear RES-007:warning\n" in differs
    assert "  5 days earlier: verdict caution; appear RES-007:warning\n" in differs
    assert "  4 days earlier" not in differs
    assert "Origin sensitivity: not run; design.start_utc is registered.\n" in skipped
    assert _report(context, sensitivity=changed)["origin_sensitivity"] == changed


REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 5.0,
}


def _revenue_context(raw_spec: dict, *, variant_c=(0.0, 2.0, 1.0, 3.5, 0.0, 0.5), **changes):
    values = {
        "control": (0.0, 0.0, 1.5, 0.0, 4.0, 2.5),
        "variant_b": (0.0, 3.0, 5.5, 0.0, 6.0, 2.0),
        "variant_c": variant_c,
    }
    rows = [
        Row(f"{arm}_{i}", arm, revenue=v) for arm, vs in values.items() for i, v in enumerate(vs)
    ]
    return _context(raw_spec, rows, **REVENUE, **changes)


@pytest.mark.parametrize(
    ("blocking", "warnings", "unreadable", "underpowered"),
    [
        ((), ("RES-001", "RES-002"), [], False),  # a warning from these rules blocks nothing
        (("RES-001",), (), ["RES-001"], False),
        (("RES-003", "RES-012"), (), ["RES-003", "RES-012"], False),
        (("RES-002",), (), [], True),
        (("RES-004",), (), [], False),
        (("RES-001", "RES-002"), (), ["RES-001"], True),
    ],
)
def test_the_effect_table_is_labelled_by_the_rules_that_block_the_review(
    raw_spec: dict,
    blocking: tuple[str, ...],
    warnings: tuple[str, ...],
    unreadable: list[str],
    underpowered: bool,
) -> None:
    context = _revenue_context(raw_spec)

    report = _report(context, _blocked(context, *blocking, warnings=warnings))
    text = " ".join(render_results_text(report).split())

    effect = report["effect"]
    assert (effect["readable"], effect["unreadable_because"], effect["underpowered"]) == (
        not unreadable,
        unreadable,
        underpowered,
    )
    not_to_be_read = "NOT TO BE READ: blocked by " + " and ".join(unreadable)
    assert (not_to_be_read in text) == bool(unreadable)
    assert "NOT TO BE READ" not in text or unreadable
    assert ("UNDERPOWERED: RES-002 blocks this review" in text) == underpowered


@pytest.mark.parametrize(
    ("blocking", "decision", "label"),
    [
        (
            ("RES-001",),
            "RES-001 blocks this review, and its remediation says to settle what it found",
            "blocked by RES-001, whose remediation says to settle this",
        ),
        (
            ("RES-003", "RES-012"),
            "RES-003 and RES-012 block this review, and the remediation of each says to settle "
            "what it found",
            "blocked by RES-003 and RES-012, whose remediations say to settle this",
        ),
        (
            ("RES-001", "RES-003", "RES-012"),
            "RES-001, RES-003 and RES-012 block this review, and the remediation of each says "
            "to settle what it found",
            "blocked by RES-001, RES-003 and RES-012, whose remediations say to settle this",
        ),
    ],
)
def test_the_rules_that_make_the_effect_unreadable_are_named_in_good_grammar(
    raw_spec: dict, blocking: tuple[str, ...], decision: str, label: str
) -> None:
    context = _revenue_context(raw_spec)

    report = _report(context, _blocked(context, *blocking))

    memo = render_results_memo(report)
    assert f"Do not read the effect. {decision} before the effect is read." in _flat(
        memo.split("\n## ")[1]
    )
    for shown in (_flat(memo), " ".join(render_results_text(report).split())):
        assert f"NOT TO BE READ: {label} before the effect is read." in shown


@pytest.mark.parametrize(
    ("warnings", "said"),
    [
        (
            ("RES-012",),
            "found no blocker and 1 warning (RES-012). Read the effect with it in view; it is "
            "qualified under Data-quality qualification.",
        ),
        (
            ("RES-007", "RES-008"),
            "found no blocker and 2 warnings (RES-007, RES-008). Read the effect with them in "
            "view; each is qualified under Data-quality qualification.",
        ),
    ],
)
def test_a_caution_counts_its_warnings_in_good_grammar(
    raw_spec: dict, warnings: tuple[str, ...], said: str
) -> None:
    context = _revenue_context(raw_spec)

    memo = render_results_memo(_report(context, _blocked(context, warnings=warnings)))

    assert f"The rules that ran {said}" in _flat(memo.split("\n## ")[1])


def test_the_effect_table_prints_each_arm_under_its_columns(raw_spec: dict) -> None:
    context = _revenue_context(raw_spec)
    report = _report(context)

    block = render_results_text(report).split("\n  arm ")[1].split("\n\n")[0].splitlines()
    table = [re.split(r" {2,}", ("arm " + block[0]).strip())]
    table += [re.split(r" {2,}", line.strip()) for line in block[1:]]

    expected = [["arm", "players", "difference", "95% interval", "relative", "p", "adjusted p"]]
    for row in report["effect"]["arms"]:
        expected.append(
            [
                row["arm"],
                f"{row['n_treatment']} vs {row['n_control']}",
                f"{row['difference']:+.4g}",
                f"{row['ci_low']:.4g} to {row['ci_high']:.4g}",
                f"{100 * row['relative_difference']:+.1f}%",
                f"{row['p_value']:.3g}",
                f"{row['adjusted_p_value']:.3g}",
            ]
        )
    assert table == expected


@pytest.mark.parametrize(
    ("registered", "said"),
    [
        (None, "adjusted for 2 comparisons (the arms against control) by Bonferroni"),
        ("none", "not adjusted for the number of arms"),
    ],
)
def test_the_text_says_how_the_p_values_were_adjusted(raw_spec: dict, registered, said) -> None:
    context = _revenue_context(raw_spec, design__alpha_adjustment=registered)

    text = " ".join(render_results_text(_report(context)).split())

    assert said in text
    assert "two-sided tests and 95% intervals" in text
    assert ("and for nothing else: not for guardrails" in text) == (registered is None)


def test_one_comparison_is_not_pluralised(raw_spec: dict) -> None:
    rows = [*crowd("control", 4), *crowd("variant_b", 4)]
    context = _context(raw_spec, rows, arms=TWO_ARMS)

    text = " ".join(render_results_text(_report(context)).split())

    assert "adjusted for 1 comparison (" in text


def test_an_arm_without_an_estimate_is_listed_with_its_reason(raw_spec: dict) -> None:
    report = _report(_revenue_context(raw_spec, variant_c=(1.0,)))

    text = " ".join(render_results_text(report).split())

    b, c = report["effect"]["arms"]
    assert "error" in c and "error" not in b
    assert f"variant_c (1 vs 6): not estimated; {' '.join(c['error'].split())}" in text
    assert "variant_b 6 vs 6" in text  # the arm that could be estimated is in the table


def test_when_no_arm_has_an_estimate_the_reasons_are_listed_in_arm_order_without_a_table(
    raw_spec: dict,
) -> None:
    report = _report(_revenue_context(raw_spec))
    for row in report["effect"]["arms"]:
        for key in ("difference", "ci_low", "ci_high", "relative_difference"):
            del row[key]
        row["error"] = f"no estimate for {row['arm']}"

    text = render_results_text(report)

    assert "adjusted p" not in text
    assert text.index("variant_b (6 vs 6): not estimated") < text.index("variant_c (6 vs 6): not")
    assert "\n\nEffect on revenue_usd_7d" in text


def test_the_text_opens_with_the_spec_the_files_the_time_and_the_population(raw_spec: dict) -> None:
    rows = [
        *crowd("control", 2),
        Row("control_never", "control", exposed_at=None),
        *crowd("variant_b", 3, assigned_at=at(2), exposed_at=at(2, 0.1)),
        Row("variant_c_0", "variant_c", assigned_at=at(1), exposed_at=at(1, 0.1)),
        Row("early", "variant_c", assigned_at=at(-2)),
    ]
    context = _context(raw_spec, rows, exported_at=at(40), design__start_utc="2026-04-11T00:00:00Z")
    review = _blocked(context, "RES-001", warnings=("RES-007", "RES-008"))
    report = _report(context, review, source="manifest")

    head = render_results_text(report).split("\n\nAlways checked")[0].splitlines()

    sensitivity = next(i for i, line in enumerate(head) if line.startswith("Origin sensitivity: "))
    version = head.index(f"Referee:    {__version__}")
    assert all(line.startswith("  ") for line in head[sensitivity + 1 : version])  # its wrapped end
    assert head[:sensitivity] == [
        "Referee results review",
        "Spec:       hybrid_offer_page_2026_10 - Subscription offer page variants",
        f"Spec hash:  sha256:{report['spec']['sha256']}",
        "Experiment: e1",
        "Data files (SHA-256 of the bytes):",
        f"  experiment_assignments.csv  {'a' * 64}",
        "As of:      2026-05-21T00:00:00Z (manifest)",
        "Origin:     2026-04-11T00:00:00Z (design.start_utc)",
        "Assigned:   from 2026-04-11T00:00:00Z to 2026-04-13T00:00:00Z",
        "  control: 3 assigned, 2 analysed",
        "  variant_b: 3 assigned, 3 analysed",
        "  variant_c: 1 assigned, 1 analysed",
        "Ignored:    1 assigned before design.start_utc, in no count",
        "    players: early",
    ]
    assert head[version:] == [
        f"Referee:    {__version__}",
        "",
        "Verdict: INVALID",
        "Blocking rules: data validity RES-001",
        "Findings: blockers 1, warnings 2, info 0",
    ]


def test_an_interim_run_is_said_under_the_time_it_qualifies(raw_spec: dict) -> None:
    rows = [*crowd("control", 2), *crowd("variant_b", 2)]
    report = _report(_context(raw_spec, rows, exported_at=at(20)), source="command line")

    head = render_results_text(report).splitlines()

    start = head.index("As of:      2026-05-01T00:00:00Z (command line)")
    assert head[start + 1].startswith(" " * 12 + "INTERIM RUN")
    assert "(2026-05-02T00:00:00Z)" in " ".join(head[start + 1 : start + 4])


def test_the_effect_table_lines_are_aligned_and_a_missing_relative_difference_is_n_a(
    raw_spec: dict,
) -> None:
    report = _report(_revenue_context(raw_spec))
    report["effect"]["arms"] = [
        {
            "arm": "variant_b",
            "n_treatment": 1200,
            "n_control": 998,
            "difference": 0.5,
            "ci_low": -1.25,
            "ci_high": 2.0,
            "relative_difference": None,
            "p_value": 0.00012,
            "adjusted_p_value": 0.00024,
        },
        {
            "arm": "b",
            "n_treatment": 7,
            "n_control": 8,
            "difference": -0.25,
            "ci_low": -3.0,
            "ci_high": 2.5,
            "relative_difference": -0.0413,
            "p_value": 0.5,
            "adjusted_p_value": 1.0,
        },
        {
            "arm": "c",
            "n_treatment": 1,
            "n_control": 1,
            "difference": 0.0,
            "ci_low": -1.0,
            "ci_high": 1.0,
            "relative_difference": 0.0,
            "p_value": 1.0,
            "adjusted_p_value": 1.0,
        },
    ]

    lines = render_results_text(report).splitlines()

    start = lines.index(
        "  arm        players       difference  95% interval  relative  p        adjusted p"
    )
    assert lines[start : start + 4] == [
        "  arm        players       difference  95% interval  relative  p        adjusted p",
        "  variant_b  1,200 vs 998  +0.5        -1.25 to 2    n/a       0.00012  0.00024",
        "  b          7 vs 8        -0.25       -3 to 2.5     -4.1%     0.5      1",
        "  c          1 vs 1        +0          -1 to 1       +0.0%     1        1",
    ]


@pytest.mark.parametrize("window_column", [True, False], ids=["window column", "no window column"])
def test_data_from_the_last_days_of_the_calendar_still_gives_a_report(
    raw_spec: dict, window_column: bool
) -> None:
    """Without the column a window is seven days from the assignment, and that is after the end
    of the calendar."""
    first = datetime(9999, 12, 28, tzinfo=UTC)
    moments = {"assigned_at": first, "exposed_at": first + timedelta(minutes=5)}
    if window_column:
        moments["window_end"] = first + timedelta(days=3)
    taken = datetime(9999, 12, 31, tzinfo=UTC)
    spec = results_spec(raw_spec)
    rows = [
        *crowd("control", 3, **moments),
        *crowd("variant_b", 3, **moments),
        *crowd("variant_c", 3, **moments),
    ]
    data = build_data(rows, exported_at=taken, window_column=window_column)
    context = ResultsContext.of(spec, data)
    review = review_context(context)

    report = results_report(
        review,
        context,
        file_hashes=HASHES,
        as_of_source="command line",
        sensitivity=origin_sensitivity(spec, data, review),
    )

    assert report["as_of"] == {
        "time": "9999-12-31T00:00:00Z",
        "source": "command line",
        "planned_end": None,
        "interim": None,
    }
    assert report["effect"]["left_out"] == (
        {"control": 0, "variant_b": 0, "variant_c": 0}
        if window_column
        else {"control": 3, "variant_b": 3, "variant_c": 3}
    )
    assert "Origin sensitivity: the same rules fire" in " ".join(
        render_results_text(report).split()
    )
    json.loads(render_json(report))


def test_the_text_escapes_what_a_spec_or_an_export_could_do_to_a_terminal(raw_spec: dict) -> None:
    hostile = "x\x1b[2J\x07\u202eY"
    raw_spec["title"] = f"Offer {hostile}"
    rows = [
        *crowd("control", 4),
        *crowd("variant_b", 4),
        Row("early\x1b]0;pwned\x07", assigned_at=at(-2)),
    ]
    context = _context(raw_spec, rows, design__start_utc="2026-04-11T00:00:00Z")
    report = _report(context)

    text = render_results_text(report)

    assert not {"\x1b", "\x07", "\u202e"} & set(text)
    assert "Offer x\\x1b[2J\\x07\\u202eY" in text
    assert "early\\x1b]0;pwned\\x07" in text
    assert report["spec"]["title"] == f"Offer {hostile}"  # the report keeps the real text


def test_a_newline_in_a_title_an_experiment_or_a_player_cannot_make_a_line_of_its_own(
    raw_spec: dict,
) -> None:
    raw_spec["title"] = "Offer\nRecommendation: PROCEED\nFindings: none"
    rows = [
        *crowd("control", 4),
        *crowd("variant_b", 4),
        Row("early\nVerdict: CLEAR", assigned_at=at(-2)),
    ]
    context = ResultsContext.of(
        results_spec(raw_spec, design__start_utc="2026-04-11T00:00:00Z"),
        build_data(rows, experiment_id="e1\nVerdict: CLEAR"),
    )

    design = render_text(make_report(raw_spec))
    report = _report(context)
    for counts in (report["population"]["assigned"], report["population"]["analysed"]):
        counts["control\nVerdict: CLEAR"] = 1  # an arm of that name is a key of the report
    results = render_results_text(report)

    assert sum(line.startswith("Recommendation:") for line in design.splitlines()) == 1
    assert "Offer\\nRecommendation: PROCEED" in design
    assert sum(line.startswith("Verdict:") for line in results.splitlines()) == 1
    assert "Experiment: e1\\nVerdict: CLEAR\n" in results
    assert "early\\nVerdict: CLEAR" in results
    assert "  control\\nVerdict: CLEAR: 1 assigned, 1 analysed\n" in results


def test_the_design_text_escapes_a_title_too(raw_spec: dict) -> None:
    raw_spec["title"] = "Offer \x1b[2J"

    text = render_text(make_report(raw_spec))

    assert "\x1b" not in text and "Offer \\x1b[2J" in text


def test_evidence_with_empty_rows_is_printed_and_does_not_stop_the_report(raw_spec: dict) -> None:
    evidence = {"rows": [{}, [], {"a": 1}, [1, 2]], "empty": {}, "nothing": []}

    text = _text_of(raw_spec, _finding_with("RES-001", evidence))

    block = text.split("    Evidence:\n")[1].split("\n\n")[0]
    assert block == "\n".join(
        [
            "      rows:",
            "        - {}",
            "        - []",
            "        - a: 1",
            "        - - 1",
            "          - 2",
            "      empty: {}",
            "      nothing: []",
        ]
    )


def test_the_text_says_who_was_left_out_of_the_effect_table_for_a_window_still_open(
    raw_spec: dict,
) -> None:
    closed = [*crowd("control", 4), *crowd("variant_b", 4), *crowd("variant_c", 4)]
    opening = {"assigned_at": at(5), "exposed_at": at(5, 1)}
    still_open = [
        Row("open_control", "control", **opening),
        Row("open_b_1", "variant_b", **opening),
        Row("open_b_2", "variant_b", **opening),
    ]

    report = _report(_context(raw_spec, [*closed, *still_open], exported_at=at(8)))
    quiet = _report(_context(raw_spec, closed, exported_at=at(8)))

    said = " ".join(render_results_text(report).split())
    assert "export time: control 1, variant_b 2." in said
    assert "Left out" not in render_results_text(quiet)
    report["effect"]["left_out"]["control"] = 1_200
    assert "control 1,200, variant_b 2." in " ".join(render_results_text(report).split())


def test_the_effect_says_what_it_read_when_the_export_has_no_time(raw_spec: dict) -> None:
    rows = [*crowd("control", 4), *crowd("variant_b", 4), *crowd("variant_c", 4)]

    timed = _report(_context(raw_spec, rows, exported_at=at(30)))
    untimed = _report(_context(raw_spec, rows))

    assert "among the analysed players with a closed outcome window:" in " ".join(
        render_results_text(timed).split()
    )
    said = " ".join(render_results_text(untimed).split())
    assert "closed outcome window" not in said
    assert "the export has no time, so no outcome window was checked" in said


def test_a_design_that_cannot_be_sized_is_not_called_underpowered(raw_spec: dict) -> None:
    context = _revenue_context(raw_spec)
    sized = _blocked(context, "RES-002")
    unsized = replace(
        sized,
        findings=tuple(
            replace(f, evidence={"unattainable": True, "reason": "r"}) for f in sized.findings
        ),
    )

    assert _report(context, sized)["effect"]["underpowered"] is True
    report = _report(context, unsized)
    assert report["effect"]["underpowered"] is False
    assert "UNDERPOWERED" not in render_results_text(report)


# --- The kind of players, from the first-seen column -----------------------------------


def test_the_population_states_what_the_first_seen_column_shows_of_the_declared_kind(
    raw_spec: dict,
) -> None:
    rows = [
        *crowd("control", 3, first_seen_at=at(-100)),
        *crowd("variant_b", 2, first_seen_at=at(-100)),
        Row("newcomer", "variant_b", assigned_at=at(2), first_seen_at=at(1)),
    ]

    without = _report(_context(raw_spec, [Row("p", "control"), Row("q", "variant_b")]))
    mostly_existing = _report(_context(raw_spec, rows, population__kind="new_users"))

    assert without["population"]["kind_declared"] is None
    assert without["population"]["first_seen"] is None
    assert mostly_existing["population"]["kind_declared"] == "new_users"
    assert mostly_existing["population"]["first_seen"] == {
        "before_origin": 5,
        "from_origin": 1,
        "days_before_assignment": {"min": 1.0, "median": 100.0, "max": 100.0},
        "observed": "existing_users",
        "agrees": False,
    }


# --- The memo --------------------------------------------------------------------------

GOLDEN_RESULTS = Path(__file__).parent / "golden" / "offer-page-results.json"


def _memo_headings(memo: str) -> list[str]:
    return [line[3:] for line in memo.splitlines() if line.startswith("## ")]


def _flat(text: str) -> str:
    """`text` as one line, so a sentence can be looked for across the memo's wrapping."""
    return " ".join(text.split())


def test_the_effect_sentences_say_the_intervals_are_not_adjusted_for_the_number_of_arms() -> None:
    """The p values are adjusted for the arms and the intervals are not, so an interval can
    exclude 0 beside an adjusted p value above 0.05."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    sentence = "The 95% intervals are not adjusted for the number of arms."

    for adjustment in ("bonferroni", "none"):
        report["effect"]["adjustment"] = adjustment
        assert sentence in _flat(render_results_memo(report))
        assert sentence in _flat(render_results_text(report))


@pytest.mark.parametrize(
    ("rules", "said"),
    [
        (["RES-001"], "while RES-001 blocks (see the Decision)"),
        (["RES-001", "RES-003"], "while RES-001 and RES-003 block (see the Decision)"),
        ([], None),
    ],
)
def test_the_quality_section_says_that_its_advice_waits_for_the_blocking_rules(
    rules: list[str], said: str | None
) -> None:
    """The rules' What to do lines are written for a reader who may read the effect."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["effect"].update(readable=not rules, unreadable_because=rules)

    quality = render_results_memo(report).split("\n## ")[4]

    if said is None:
        assert "The effect is not to be read" not in quality
        return
    settled = "it is" if len(rules) == 1 else "they are"
    assert quality.startswith(
        f"Data-quality qualification\n\nThe effect is not to be read {said}, so a What to do "
        "line below that tells you to read, compare or report the effect applies once "
        f"{settled} settled.\n\n**["
    )


def test_the_memo_does_not_say_one_kind_of_players_confirms_a_declared_mixed_population() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["population"]["kind_declared"] = "mixed"

    assumptions = _flat(render_results_memo(report).split("\n## ")[3])

    assert (
        "population.kind is declared as mixed, and the column shows only existing users: that "
        "does not contradict a mixed population, and does not confirm one."
    ) in assumptions


def test_the_memo_carries_the_lab_templates_sections_in_order_filled_from_the_report() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))

    memo = render_results_memo(report)

    assert memo.startswith(f"# Decision memo: `{report['spec']['title']}`\n")
    assert _memo_headings(memo) == list(MEMO_HEADINGS)
    assert MEMO_HEADINGS == (
        "Decision",
        "Observed facts",
        "Assumptions and uncertainty",
        "Data-quality qualification",
        "Reproducibility",
    )
    decision, observed, assumptions, quality, reproducibility = memo.split("\n## ")[1:]
    assert "Do not read the effect. RES-001 blocks this review" in _flat(decision)
    assert (
        "RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 "
        "analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller "
        "than the registered sample size."
    ) in _flat(decision)
    assert "Read the intervals" not in _flat(decision)
    assert "Not decided here: whether to ship, stop or continue" in _flat(decision)
    assert "Verdict: INVALID. Blocking rules: data validity RES-001, RES-002." in _flat(observed)
    for row in report["effect"]["arms"]:
        assert f"| {row['arm']} | " in observed and f"| {row['difference']:+.4g} |" in observed
    assert "NOT TO BE READ: blocked by RES-001," in _flat(observed)
    assert (
        "By first_seen_at_utc, 2,824 of the 2,824 assigned players were first seen before the "
        "origin" in _flat(assumptions)
    )
    assert "population.kind is declared as existing_users, and the column agrees." in (
        _flat(assumptions)
    )
    assert quality.count("\n**[") == len(report["findings"])
    assert "\n    alpha: 0.001\n" in quality  # RES-001's evidence, as an indented code block
    assert f"Rules run: {', '.join(report['rules_run'])}." in _flat(quality)
    for name, file in report["data"]["files"].items():
        assert f"- {name}: {file['sha256']}" in _flat(reproducibility)
    assert "--experiment-id=hybrid_offer_page --as-of 2026-06-30T00:00:00Z --format memo" in (
        _flat(reproducibility)
    )
    assert render_results_memo(report) == memo


def test_the_players_table_says_what_its_columns_count_and_what_analysed_means() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["effect"]["left_out"]["control"] = 3

    observed = render_results_memo(report).split("\n## ")[2]

    assert "| arm | assigned | analysed | window still open (left out of the effect table) |" in (
        observed
    )
    assert "| control | 997 | 926 | 3 |" in observed
    assert "| variant_b | 1,046 | 969 | 0 |" in observed
    assert (
        "Analysed players are those of the assigned players above who were exposed and were not "
        "first exposed after their first purchase; assigned players who were never exposed, or "
        "were first exposed after buying, are not analysed."
    ) in _flat(observed)


def test_the_players_table_does_not_say_no_window_is_open_when_none_was_checked() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["as_of"]["time"] = None

    observed = render_results_memo(report).split("\n## ")[2]

    assert "| control | 997 | 926 | not checked |" in observed


@pytest.mark.parametrize(("weeks", "shown"), [([0], "week 0"), ([0, 1], "weeks 0, 1")])
def test_a_list_of_week_numbers_is_not_printed_as_a_bare_number(weeks, shown: str) -> None:
    """RES-011 holds `failing_weeks` and RES-013 `mixed_weeks`: `failing_weeks: 0` reads as none."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    mixed = next(f for f in report["findings"] if f["rule_id"] == "RES-013")
    mixed["evidence"]["arms"]["variant_b"]["mixed_weeks"] = weeks
    report["findings"].append({**mixed, "rule_id": "RES-011", "evidence": {"failing_weeks": weeks}})

    for rendering in (render_results_memo(report), render_results_text(report)):
        assert f"failing_weeks: {shown}\n" in rendering
        assert f"mixed_weeks: {shown}\n" in rendering


def test_the_pointer_to_the_json_report_names_only_the_tables_the_rule_holds() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))

    for rendering in (render_results_memo(report), render_results_text(report)):
        flat = _flat(rendering)
        assert "The tests, plans and settings behind these sentences are in the JSON report" in flat
        assert "The tests and settings behind these sentences are in the JSON report" in flat


def test_a_title_an_arm_or_a_player_cannot_make_a_heading_a_row_or_a_line_in_the_memo(
    raw_spec: dict,
) -> None:
    """Values from a spec or an export are written as code spans and never start a line; a
    pipe or a backslash in a table cell is escaped. The arm `## Decision` has no estimate, so
    it is named first in a sentence of its own, and the player `## Decision` is listed as
    ignored: the two places a value would otherwise start a line."""
    raw_spec["title"] = "Offer\n## Decision\n| x |"
    arms = [
        {"name": "control", "allocation": 0.5, "is_control": True},
        {"name": "b\\|c", "allocation": 0.3},
        {"name": "## Decision", "allocation": 0.2},
    ]
    rows = [
        *crowd("control", 2),
        *crowd("b\\|c", 2, prefix="bc"),
        *crowd("## Decision", 2, prefix="heading"),
        Row("## Decision", "control", assigned_at=at(-1)),
    ]
    context = _context(raw_spec, rows, arms=arms, design__start_utc="2026-04-11T00:00:00Z")

    memo = render_results_memo(_report(context))

    lines = memo.splitlines()
    assert _memo_headings(memo) == list(MEMO_HEADINGS)
    assert [line for line in lines if line.startswith("#")] == [
        "# Decision memo: `Offer\\n## Decision\\n| x |`",
        *(f"## {heading}" for heading in MEMO_HEADINGS),
    ]
    assert "| b\\\\\\|c | 2 | 2 | not checked |" in memo
    assert "\nArm `## Decision` (2 vs 2): not estimated; " in memo
    assert "in no count: 1 (`## Decision`)." in memo
    # Wherever a value appears, the line it is on is one of the memo's own: a sentence, a
    # bullet, a table row or an indented evidence line, never one the value began.
    assert all(
        line.startswith(("| ", "- ", "    ")) or line[0].isalpha()
        for line in lines
        if "## Decision" in line and not line.startswith("#")
    )


def _reproduce_line(memo: str) -> str:
    return next(row for row in memo.splitlines() if row.startswith("Reproduce it from"))


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
@pytest.mark.parametrize(
    "experiment",
    ["hybrid_offer_page", "e 1", "it's", "a;b", "$(echo hacked)", 'a"b', "a b'c", "*", "-x"],
)
def test_a_shell_reads_the_command_that_gives_the_memo_again_with_the_experiment_as_it_is(
    experiment: str,
) -> None:
    """A real shell, not shlex: the id comes from an export and is the one thing in the command
    that a reader did not write. It is one word, --experiment-id=ID, so that an id that starts
    with a dash is not an option and one that holds a space or a ";" is not several words."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["experiment_id"] = experiment

    line = _reproduce_line(render_results_memo(report))
    arguments = line.split("`", 2)[1].removeprefix("python -m referee review-results SPEC DATA ")
    shown = subprocess.run(
        ["sh", "-c", 'printf "[%s]" ' + arguments], capture_output=True, text=True, check=True
    )

    assert shown.stderr == ""
    assert shown.stdout == "".join(
        f"[{word}]"
        for word in (f"--experiment-id={experiment}", "--as-of", "2026-06-30T00:00:00Z")
        + ("--format", "memo")
    )


def test_an_experiment_with_a_control_character_in_its_name_is_not_named_in_the_command() -> None:
    """The report writes the control character as an escape, so a command that named the id as
    shown would name another experiment (one with a backslash and a "u0007" in its name)."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    plain = _reproduce_line(render_results_memo(report))
    report["experiment_id"] = "line\u0007bell"

    line = _reproduce_line(render_results_memo(report))

    command = line.split("`", 2)[1]
    assert command.startswith(
        "python -m referee review-results SPEC DATA --experiment-id=ID --as-of "
    )
    assert "bell" not in command and "u0007" not in command
    assert (
        "carry these hashes. ID is the experiment above, whose name holds control characters "
        "(shown there as escapes): pass it exactly as the export holds it. The memo holds no "
        "timestamp"
    ) in line
    assert "holds control characters" not in plain


def test_a_time_from_the_manifest_is_said_to_come_from_a_file_that_is_not_hashed() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["as_of"]["source"] = "manifest"

    typed = _reproduce_line(render_results_memo(json.loads(GOLDEN_RESULTS.read_text("utf-8"))))
    line = _reproduce_line(render_results_memo(report))

    assert (
        "--as-of" not in line
    )  # the manifest in DATA gives the time, and --as-of would replace it
    assert (
        "carry these hashes. The export time above comes from the manifest.json in DATA "
        "(exported_at_utc), which is not among the hashed files. The memo holds no timestamp"
    ) in line
    assert "manifest.json" not in typed


@pytest.mark.parametrize(
    ("value", "span"),
    [
        ("plain", "`plain`"),
        ("a`b", "``a`b``"),
        ("`a", "`` `a ``"),
        ("a`", "`` a` ``"),
        ("`", "`` ` ``"),
        (" a ", "`  a  `"),
        (" a", "` a`"),
        ("a ", "`a `"),
        (" ", "` `"),
        (" X ", "`  X  `"),
        ("a``b```c", "````a``b```c````"),
    ],
)
def test_a_value_in_a_code_span_is_fenced_and_padded_so_that_it_reads_back_as_it_was(
    value: str, span: str
) -> None:
    assert _md_code(value) == span


@pytest.mark.parametrize("mark", list("\\`*[]<>|&~"))
def test_each_inline_mark_in_a_value_has_a_backslash_before_it(mark: str) -> None:
    assert _md_text(f"a{mark}b") == f"a\\{mark}b"


def test_an_underscore_is_marked_at_the_edge_of_a_word_and_not_inside_one() -> None:
    assert _md_text("variant_b") == "variant_b"
    assert (_md_text("_x_"), _md_text("x_"), _md_text("_x")) == ("\\_x\\_", "x\\_", "\\_x")


HOSTILE_ARM = '[x](http://evil) <img src=x onerror=alert(1) alt="> *em* ~~del~~ _u_ `tick`'
ESCAPED_ARM = (
    '\\[x\\](http://evil) \\<img src=x onerror=alert(1) alt="\\> \\*em\\* \\~\\~del\\~\\~ '
    "\\_u\\_ \\`tick\\`"
)


def _renamed(value: Any, old: str, new: str) -> Any:
    """`value` with `old` replaced by `new` in every text of it, the keys too."""
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {_renamed(k, old, new): _renamed(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return value


def test_the_name_of_an_arm_cannot_make_a_link_an_image_a_tag_or_emphasis_in_the_memo() -> None:
    """The arm is named in a table cell, in the sentence on who was left out, and in the notes
    of the effect rules: three places, three ways of keeping its marks from acting (the
    sentences that name the short arms and write them as code spans are pinned beside them)."""
    golden = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report = _renamed(golden, "variant_b", HOSTILE_ARM)
    report["effect"]["left_out"][HOSTILE_ARM] = 3
    notes = [n for f in report["findings"] for n in f["evidence"].get("notes", [])]
    assert any(HOSTILE_ARM in note for note in notes)

    memo = render_results_memo(report)

    assert f"| {ESCAPED_ARM} | " in memo
    assert f"closed at the export time: `` {HOSTILE_ARM} `` 3." in memo
    assert f"- arm {ESCAPED_ARM}, metric " in memo
    for line in memo.splitlines():
        if "evil" in line and not line.startswith("    "):  # not the evidence code block
            outside = re.sub(r"\\.|(`+).+?\1", "", line)  # without escapes and code spans
            assert not re.search(r"[<\[*~&]", outside), line


@pytest.mark.parametrize(
    ("blocking", "warnings", "said"),
    [
        ((), (), "found nothing that blocks or warns"),
        ((), ("RES-007", "RES-008"), "found no blocker and 2 warnings (RES-007, RES-008)"),
        (("RES-004",), (), "Do not decide on the primary metric alone: RES-004 found a guardrail"),
        (
            ("RES-003", "RES-012"),
            (),
            "Do not read the effect. RES-003 and RES-012 block this review",
        ),
        (("RES-002",), (), "Report the result as underpowered"),
    ],
)
def test_the_memos_decision_follows_the_verdict_and_what_the_blocking_rules_advise(
    raw_spec: dict, blocking: tuple[str, ...], warnings: tuple[str, ...], said: str
) -> None:
    context = _revenue_context(raw_spec)

    memo = render_results_memo(_report(context, _blocked(context, *blocking, warnings=warnings)))

    decision = _flat(memo.split("\n## ")[1])
    assert said in decision
    assert "Not decided here: whether to ship, stop or continue the experiment." in decision


ONE_SHORT = (
    ("variant_b",),
    "`variant_b` (1,234 analysed, 2,000 required) is",
    "variant_b (1,234 analysed, 2,000 required) is",
    "it is",
)
TWO_SHORT = (
    ("variant_b", "variant_c"),
    "`variant_b` (1,234 analysed, 2,000 required) and `variant_c` (1,234 analysed, 2,000 "
    "required) are",
    "variant_b (1,234 analysed, 2,000 required) and variant_c (1,234 analysed, 2,000 required) are",
    "they are",
)
SHORT_ARMS = [pytest.param(*ONE_SHORT, id="one arm"), pytest.param(*TWO_SHORT, id="two arms")]


@pytest.mark.parametrize(("short", "memo_arms", "text_arms", "still"), SHORT_ARMS)
def test_an_underpowered_review_whose_effect_can_be_read_names_the_short_arms(
    raw_spec: dict, short: tuple[str, ...], memo_arms: str, text_arms: str, still: str
) -> None:
    context = _revenue_context(raw_spec)

    report = _report(context, _blocked(context, "RES-002", evidence={"RES-002": _short(*short)}))

    memo = render_results_memo(report)
    advice = "Read the intervals; a small difference is not evidence of no effect."
    assert (
        f"Report the result as underpowered: {memo_arms} smaller than the registered sample size "
        f"(RES-002). {advice}"
    ) in _flat(memo.split("\n## ")[1])
    label = "UNDERPOWERED: RES-002 blocks this review, {} smaller than registered. " + advice
    assert label.format(memo_arms) in _flat(memo)
    assert label.format(text_arms) in " ".join(render_results_text(report).split())


@pytest.mark.parametrize(
    ("blocking", "short", "memo_arms", "text_arms", "still"),
    [
        pytest.param(("RES-001", "RES-002"), *ONE_SHORT, id="RES-001, one arm"),
        pytest.param(("RES-003", "RES-002"), *TWO_SHORT, id="RES-003, two arms"),
    ],
)
def test_a_review_that_is_unreadable_and_underpowered_does_not_say_to_read_the_intervals(
    raw_spec: dict,
    blocking: tuple[str, ...],
    short: tuple[str, ...],
    memo_arms: str,
    text_arms: str,
    still: str,
) -> None:
    """The effect must not be read while RES-001, RES-003 or RES-012 blocks, so the advice to
    read its intervals, for RES-002, waits until it can be."""
    context = _revenue_context(raw_spec)

    report = _report(context, _blocked(context, *blocking, evidence={"RES-002": _short(*short)}))

    memo = render_results_memo(report)
    assert "Read the intervals" not in _flat(memo)
    assert "Read the intervals" not in " ".join(render_results_text(report).split())
    assert (
        f"RES-002 also blocks: {memo_arms} smaller than the registered sample size. Once the "
        f"effect can be read, and if {still} still smaller, report the result as "
        "underpowered: a small difference is not evidence of no effect."
    ) in _flat(memo.split("\n## ")[1])
    label = (
        "UNDERPOWERED: RES-002 blocks this review, {} smaller than registered. Do not read the "
        "intervals yet: once the effect can be read, a small difference is still not evidence "
        "of no effect."
    )
    assert label.format(memo_arms) in _flat(memo)
    assert label.format(text_arms) in " ".join(render_results_text(report).split())


def test_a_report_that_says_underpowered_without_a_res_002_finding_is_refused() -> None:
    """The sentence names the arms from the finding's evidence; with no finding it has no words,
    and a memo that guessed would be a wrong one."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["findings"] = [f for f in report["findings"] if f["rule_id"] != "RES-002"]
    assert report["effect"]["underpowered"]

    with pytest.raises(
        ValueError, match="^the effect is underpowered but the report holds no RES-002 finding$"
    ):
        render_results_memo(report)


CALENDAR_END = datetime(9999, 12, 28, tzinfo=UTC)


@pytest.mark.parametrize(
    ("span", "taken", "observed", "export", "assumption", "cohort"),
    [
        (
            14,
            None,
            "The assignments span 14 of the 14 planned days.",
            "Export taken: not known (no manifest time and no --as-of); completeness of the "
            "outcome windows was not checked.",
            "No time of the export is known, so no outcome window was checked: the effect table "
            "reads every analysed player, a window still open included. Whether the export was "
            "taken before the planned end of the experiment cannot be said.",
            False,
        ),
        (
            14,
            at(10),
            "The assignments span 14 of the 14 planned days.",
            "Export taken: 2026-04-21T00:00:00Z (command line). That is before the planned end "
            "of the experiment (2026-05-02T00:00:00Z).",
            "The export was taken before the planned end of the experiment (2026-05-02T00:00:00Z).",
            False,
        ),
        (
            14,
            at(21),
            "The assignments span 14 of the 14 planned days.",
            "Export taken: 2026-05-02T00:00:00Z (command line). That is at or after the planned "
            "end of the experiment (2026-05-02T00:00:00Z).",
            "The export was taken at or after the planned end of the experiment "
            "(2026-05-02T00:00:00Z).",
            False,
        ),
        (
            6,
            at(40),
            "The assignments span 6 of the 14 planned days.",
            "Export taken: 2026-05-21T00:00:00Z (command line). That is at or after the planned "
            "end of the experiment (2026-05-02T00:00:00Z).",
            "The export was taken at or after the planned end of the experiment "
            "(2026-05-02T00:00:00Z).",
            True,
        ),
        (
            21,
            at(40),
            "The assignments span 21 days; 14 were planned.",
            "Export taken: 2026-05-21T00:00:00Z (command line). That is at or after the planned "
            "end of the experiment (2026-05-02T00:00:00Z).",
            "The export was taken at or after the planned end of the experiment "
            "(2026-05-02T00:00:00Z).",
            False,
        ),
    ],
    ids=[
        "no time",
        "before the planned end",
        "at the planned end",
        "short span, export later",
        "long span",
    ],
)
def test_the_memo_states_the_export_time_and_the_assignment_span_as_two_facts(
    raw_spec: dict,
    span: int,
    taken: datetime | None,
    observed: str,
    export: str,
    assumption: str,
    cohort: bool,
) -> None:
    """The export is before or after the planned end; the assignments cover the planned days
    or fewer. RES-007 calls the second an interim look, so the memo does not call the first one."""
    rows = [*crowd("control", 2, assigned_at=at(0)), *crowd("variant_b", 2, assigned_at=at(span))]

    sections = render_results_memo(
        _report(_context(raw_spec, rows, exported_at=taken), source="command line")
    ).split("\n## ")
    memo, facts, assumptions = _flat(" ".join(sections)), sections[2].split("\n\n"), sections[3]
    assumptions = assumptions.split("\n\n")

    assert any(paragraph.endswith(observed) for paragraph in facts)
    assert export in facts and assumption in assumptions
    assert "INTERIM RUN" not in memo and "interim run" not in memo
    cohort_sentence = (
        f"The assignments span {span} of the 14 planned days, fewer than planned, so the cohort "
        "test of RES-007 is an interim look: it belongs at the planned end, and run repeatedly "
        "on accumulating data it flags 11% to 13% of experiments with no change (design "
        "section 21.6)."
    )
    assert (cohort_sentence in assumptions) == cohort  # a whole paragraph of Assumptions


def test_an_export_before_a_planned_end_beyond_the_calendar_is_said_to_be_before_it(
    raw_spec: dict,
) -> None:
    rows = [
        *crowd("control", 2, assigned_at=CALENDAR_END),
        *crowd("variant_b", 2, assigned_at=CALENDAR_END),
    ]
    exported_at = datetime(9999, 12, 31, tzinfo=UTC)
    # the default window end, seven days on, would run past the last date the calendar holds
    context = _context(raw_spec, rows, exported_at=exported_at, window_column=False)

    paragraphs = render_results_memo(_report(context, source="command line")).split("\n\n")

    assert (
        "Export taken: 9999-12-31T00:00:00Z (command line). That is before the planned end of "
        "the experiment, which falls beyond the calendar."
    ) in paragraphs
    assert (
        "The planned end of the experiment falls beyond the calendar, so the export was taken "
        "before it."
    ) in paragraphs


def _finding(rule_id: str, severity: str, **evidence: object) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "title": f"{rule_id} title",
        "evidence": evidence,
        "why_it_matters": "why",
        "remediation": "what",
        "references": [],
    }


def _decision_report(
    verdict: str,
    *,
    unreadable: tuple[str, ...] = (),
    harm: tuple[str, ...] = (),
    short: tuple[str, ...] = (),
    unattainable: bool = False,
    warnings: tuple[str, ...] = (),
    infos: tuple[str, ...] = (),
) -> dict:
    """The lab report with the findings, the verdict and the effect's labels this decision
    reads replaced: the memo is built from the report alone (23.1)."""
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    arms = ("control", "variant_b", "variant_c")
    findings = [_finding(rule, "blocker") for rule in (*unreadable, *harm)]
    if short:
        findings.append(
            _finding(
                "RES-002",
                "blocker",
                required={arm: 2000 for arm in arms},
                analysed={arm: 1234 if arm in short else 2000 for arm in arms},
                assigned={arm: 4000 for arm in arms},
                short_arms=list(short),
            )
        )
    if unattainable:
        findings.append(_finding("RES-002", "blocker", unattainable=True))
    findings += [_finding(rule, "warning") for rule in warnings]
    findings += [_finding(rule, "info") for rule in infos]
    blocking = [f["rule_id"] for f in findings if f["severity"] == "blocker"]
    report |= {
        "findings": findings,
        "verdict": verdict,
        "blocking_rule_ids": blocking,
        "blocking_groups": {
            "data_validity": [rule for rule in blocking if rule not in harm],
            "harm": list(harm),
        },
    }
    report["effect"] |= {
        "unreadable_because": list(unreadable),
        "readable": not unreadable,
        "underpowered": bool(short),
    }
    return report


DECIDED = (
    "Decided here: whether the rules object to reading this experiment's result as it stands. "
    "Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, "
    "and that decision rests with the experiment's owner."
)
NOT_READ_ONE = (
    "Do not read the effect. {} blocks this review, and its remediation says to settle what it "
    "found before the effect is read."
)
HARM = (
    "Do not decide on the primary metric alone: RES-004 found a guardrail worse than its "
    "tolerance allows."
)
ONE_SHORT_PAIR = "`variant_b` (1,234 analysed, 2,000 required)"
CANNOT_BE_SIZED = (
    "The design cannot be sized (RES-002): correct the spec's baseline and target effect and "
    "register the experiment again. More data will not clear this."
)
CAUTION = (
    "The rules that ran found no blocker and {} Read the effect with {} in view; {} qualified "
    "under Data-quality qualification."
)
CLEAR = (
    "The rules that ran found nothing that blocks or warns. That does not say the effect is "
    "real: it says that none of the checks Referee makes objected."
)


@pytest.mark.parametrize(
    ("report", "paragraphs"),
    [
        pytest.param(_decision_report("clear"), [CLEAR], id="clear"),
        pytest.param(_decision_report("clear", infos=("RES-008",)), [CLEAR], id="clear, an info"),
        pytest.param(
            _decision_report("caution", warnings=("RES-007",)),
            [CAUTION.format("1 warning (RES-007).", "it", "it is")],
            id="one warning",
        ),
        pytest.param(
            _decision_report("caution", warnings=("RES-007",), infos=("RES-008",)),
            [CAUTION.format("1 warning (RES-007).", "it", "it is")],
            id="a warning and an info",
        ),
        pytest.param(
            _decision_report("caution", warnings=("RES-007", "RES-013")),
            [CAUTION.format("2 warnings (RES-007, RES-013).", "them", "each is")],
            id="two warnings",
        ),
        pytest.param(
            _decision_report("caution", warnings=("RES-007", "RES-008", "RES-013")),
            [CAUTION.format("3 warnings (RES-007, RES-008, RES-013).", "them", "each is")],
            id="three warnings",
        ),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-001",)),
            [NOT_READ_ONE.format("RES-001")],
            id="RES-001",
        ),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-001", "RES-003")),
            [
                "Do not read the effect. RES-001 and RES-003 block this review, and the "
                "remediation of each says to settle what it found before the effect is read."
            ],
            id="RES-001 and RES-003",
        ),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-001", "RES-003", "RES-012")),
            [
                "Do not read the effect. RES-001, RES-003 and RES-012 block this review, and "
                "the remediation of each says to settle what it found before the effect is read."
            ],
            id="RES-001, RES-003 and RES-012",
        ),
        pytest.param(
            _decision_report("invalid", short=("variant_b",)),
            [
                f"Report the result as underpowered: {ONE_SHORT_PAIR} is smaller than the "
                "registered sample size (RES-002). Read the intervals; a small difference is not "
                "evidence of no effect."
            ],
            id="one short arm",
        ),
        pytest.param(
            _decision_report("invalid", short=("variant_b", "variant_c")),
            [
                f"Report the result as underpowered: {ONE_SHORT_PAIR} and `variant_c` (1,234 "
                "analysed, 2,000 required) are smaller than the registered sample size "
                "(RES-002). Read the intervals; a small difference is not evidence of no effect."
            ],
            id="two short arms",
        ),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-003",), short=("variant_b",)),
            [
                NOT_READ_ONE.format("RES-003"),
                f"RES-002 also blocks: {ONE_SHORT_PAIR} is smaller than the registered sample "
                "size. Once the effect can be read, and if it is still smaller, report the "
                "result as underpowered: a small difference is not evidence of no effect.",
            ],
            id="RES-003 and one short arm",
        ),
        pytest.param(
            _decision_report("invalid", unattainable=True),
            [CANNOT_BE_SIZED],
            id="a design that cannot be sized",
        ),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-001",), unattainable=True),
            [NOT_READ_ONE.format("RES-001"), CANNOT_BE_SIZED],
            id="RES-001 and a design that cannot be sized",
        ),
        pytest.param(_decision_report("invalid", harm=("RES-004",)), [HARM], id="a guardrail"),
        pytest.param(
            _decision_report("invalid", unreadable=("RES-001",), harm=("RES-004",)),
            [NOT_READ_ONE.format("RES-001"), HARM],
            id="RES-001 and a guardrail",
        ),
        pytest.param(
            _decision_report("invalid", harm=("RES-004",), short=("variant_c",)),
            [
                HARM,
                "Report the result as underpowered: `variant_c` (1,234 analysed, 2,000 required) "
                "is smaller than the registered sample size (RES-002). Read the intervals; a "
                "small difference is not evidence of no effect.",
            ],
            id="a guardrail and one short arm",
        ),
    ],
)
def test_the_decision_is_this_exact_text_for_each_verdict_and_blocking_group(
    report: dict, paragraphs: list[str]
) -> None:
    decision = render_results_memo(report).split("\n## ")[1]

    assert decision == "Decision\n\n" + "\n\n".join([*paragraphs, DECIDED]) + "\n"


def test_a_blocker_the_memo_has_no_words_for_is_refused() -> None:
    report = _decision_report("invalid")
    report["blocking_rule_ids"] = ["RES-009"]

    with pytest.raises(ValueError, match=r"no advice for the blocking rules \['RES-009'\]"):
        render_results_memo(report)


def _section(memo: str, heading: str) -> str:
    return next(part for part in memo.split("\n## ") if part.startswith(heading))


def test_a_memo_without_findings_says_so_in_the_facts_and_in_the_quality_section() -> None:
    memo = render_results_memo(_decision_report("clear"))

    facts, quality = _section(memo, "Observed facts"), _section(memo, "Data-quality")
    assert facts.startswith("Observed facts\n\nVerdict: CLEAR. Findings: none.\n\n")
    assert quality.startswith(
        "Data-quality qualification\n\nNo finding: the rules that ran found nothing that blocks "
        "or warns.\n\nRules run: "
    )


@pytest.mark.parametrize(
    ("ignored", "limit", "said"),
    [
        (["a", "b"], 5, "2 (`a`, `b`)."),
        (["a", "b", "c"], 2, "3 (`a`, `b`; showing 2 of 3; the full list is in the JSON report)."),
    ],
)
def test_the_players_ignored_before_the_start_are_listed_and_the_list_is_cut_at_the_limit(
    ignored: list[str], limit: int, said: str
) -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["population"]["ignored_before_start"] = ignored

    facts = _section(render_results_memo(report, limit=limit), "Observed facts").split("\n\n")

    assert f"Ignored, assigned before design.start_utc and in no count: {said}" in facts


def test_a_change_of_origin_that_changes_the_rules_is_said_with_the_rules_that_move() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["origin_sensitivity"] = {
        "ran": True,
        "reason": None,
        "shifts": [
            {
                "days_earlier": day,
                "same": day != 3,
                "verdict": "clear",
                "appear": ["RES-007", "RES-013"] if day == 3 else [],
                "disappear": ["RES-012"] if day == 3 else [],
            }
            for day in range(1, 7)
        ],
    }

    assumptions = _section(render_results_memo(report), "Assumptions").split("\n\n")

    assert (
        "Origin sensitivity: the rules that fire change with the origin. 3 days earlier: verdict "
        "clear; appear RES-007, RES-013; disappear RES-012."
    ) in assumptions


def test_a_memo_without_an_export_time_says_in_its_reproducibility_that_it_is_not_known() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["as_of"] |= {"time": None, "source": None, "planned_end": None, "interim": None}

    lines = _section(render_results_memo(report), "Reproducibility").splitlines()

    assert "- Export taken: not known" in lines


def test_evidence_that_is_not_an_effect_rules_is_printed_in_full_and_an_empty_one_not_at_all() -> (
    None
):
    """An effect rule's evidence has `notes` and `tests` (its tables stay in the JSON report);
    anything else is a code block of key and value, a false value written "no"."""
    report = _decision_report("caution", warnings=("RES-007",))

    report["findings"][0]["evidence"] = {"notes": ["a note"], "flag": False}
    memo, text = render_results_memo(report), render_results_text(report)
    assert "Evidence:\n\n    notes: a note\n    flag: no\n" in memo
    assert "behind these sentences" not in memo and "behind these sentences" not in text

    report["findings"][0]["evidence"] = {}
    assert "Evidence:" not in render_results_memo(report)
    assert "Evidence:" not in render_results_text(report)


def test_the_p_values_are_said_not_to_be_adjusted_when_the_spec_registers_no_adjustment() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["effect"]["adjustment"] = "none"

    memo = render_results_memo(report)

    assert (
        "The p values are not adjusted for the number of arms (the spec registers none). The "
        "95% intervals are not adjusted for the number of arms."
    ) in _flat(memo)


def test_a_text_report_without_findings_or_an_export_time_says_so() -> None:
    report = _decision_report("clear")
    report["as_of"] |= {"time": None, "source": None, "planned_end": None, "interim": None}

    lines = render_results_text(report).splitlines()

    assert (
        "As of:      not known (no manifest time and no --as-of); completeness was not checked"
    ) in lines
    assert lines[lines.index("Verdict: CLEAR") + 1] == "Findings: none"


def test_the_text_report_indents_what_it_wraps_and_the_changes_of_origin() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["origin_sensitivity"] = {
        "ran": True,
        "reason": None,
        "shifts": [
            {
                "days_earlier": day,
                "same": day != 3,
                "verdict": "clear",
                "appear": ["RES-007", "RES-013"] if day == 3 else [],
                "disappear": ["RES-012"] if day == 3 else [],
            }
            for day in range(1, 7)
        ],
    }
    report["effect"]["arms"] = [
        {
            "arm": "variant_b",
            "n_treatment": 0,
            "n_control": 926,
            "error": "no player of this arm has a window that closed, so no mean can be taken for "
            "it and this error text is long enough to be wrapped across two lines",
        }
    ]

    lines = render_results_text(report).splitlines()

    at = lines.index("Origin sensitivity: the rules that fire change with the origin.")
    assert lines[at + 1] == (
        "  3 days earlier: verdict clear; appear RES-007, RES-013; disappear RES-012"
    )
    at = lines.index(
        "  variant_b (0 vs 926): not estimated; no player of this arm has a window that closed,"
    )
    assert lines[at + 1 : at + 3] == [
        "    so no mean can be taken for it and this error text is long enough to be wrapped",
        "    across two lines",
    ]


def test_a_long_list_in_the_evidence_wraps_with_a_hanging_indent_in_both_formats() -> None:
    report = _decision_report("caution", warnings=("RES-007",))
    report["findings"][0]["evidence"] = {"players": [f"player_{i:03d}" for i in range(14)]}

    text = render_results_text(report)
    memo = render_results_memo(report)

    assert (
        "      players: player_000, player_001, player_002, player_003, player_004, player_005,\n"
        "        player_006, player_007, player_008, player_009, player_010, player_011,\n"
        "        player_012, player_013"
    ) in text
    assert (
        "    players: player_000, player_001, player_002, player_003, player_004, player_005,\n"
        "      player_006, player_007, player_008, player_009, player_010, player_011,\n"
        "      player_012, player_013"
    ) in memo


def test_a_long_change_of_origin_wraps_under_its_first_line_in_the_text_report() -> None:
    report = json.loads(GOLDEN_RESULTS.read_text(encoding="utf-8"))
    report["origin_sensitivity"] = {
        "ran": True,
        "reason": None,
        "shifts": [
            {
                "days_earlier": day,
                "same": day != 3,
                "verdict": "clear",
                "appear": [f"RES-{n:03d}" for n in range(1, 13)] if day == 3 else [],
                "disappear": [],
            }
            for day in range(1, 7)
        ],
    }

    lines = render_results_text(report).splitlines()

    at = lines.index(
        "  3 days earlier: verdict clear; appear RES-001, RES-002, RES-003, RES-004, RES-005,"
    )
    assert lines[at + 1] == "      RES-006, RES-007, RES-008, RES-009, RES-010, RES-011, RES-012"
