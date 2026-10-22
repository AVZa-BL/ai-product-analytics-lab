"""The design-review and results-review reports and their renderings."""

import json
import re

import pytest
from results_helpers import Row, at, build_data, crowd, results_spec

from referee.findings import DesignReview, Finding, ResultsReview
from referee.report import design_report, render_json, render_results_text, results_report
from referee.results import ResultsContext
from referee.review import review_context
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


def _context(raw_spec: dict, rows: list[Row], *, exported_at=None, **changes: object):
    return ResultsContext.of(
        results_spec(raw_spec, **changes), build_data(rows, exported_at=exported_at)
    )


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
        "assigned": {"control": 2, "variant_b": 2, "variant_c": 1},
        "analysed": {"control": 2, "variant_b": 1, "variant_c": 1},
        "ignored_before_start": ["early_b", "early_c"],
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


def test_blocking_rules_are_grouped_into_data_validity_and_harm(raw_spec: dict) -> None:
    context = _context(raw_spec, [*crowd("control", 4), *crowd("variant_b", 4)])

    def blocker(rule_id: str) -> Finding:
        return Finding(
            rule_id=rule_id,
            severity="blocker",
            title="t",
            evidence={"summary": {"line": f"{rule_id}: line"}},
            why_it_matters="w",
            remediation="r",
            references=(),
        )

    ids = ("RES-001", "RES-004", "RES-012")
    review = ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=tuple(blocker(rule_id) for rule_id in ids),
    )

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
    assert "behind these sentences are in the JSON report" in text
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
    changed = {
        **UNCHANGED,
        "shifts": [
            {**shift, "same": False, "verdict": "caution", "appear": ["RES-007:warning"]}
            if shift["days_earlier"] in (3, 5)
            else shift
            for shift in UNCHANGED["shifts"]
        ],
    }
    not_run = {"ran": False, "reason": "design.start_utc is registered", "shifts": []}

    held = render_results_text(_report(context))
    differs = render_results_text(_report(context, sensitivity=changed))
    skipped = render_results_text(_report(context, sensitivity=not_run))

    assert "Origin sensitivity: the same findings for origins 1 to 6 days earlier.\n" in held
    assert "Origin sensitivity: the findings change with the origin.\n" in differs
    assert "  3 days earlier: verdict caution; appear RES-007:warning\n" in differs
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


def _blocked(context: ResultsContext, *blocking: str) -> ResultsReview:
    found = tuple(
        Finding(
            rule_id=rule_id,
            severity="blocker",
            title="t",
            evidence={"summary": {"line": f"{rule_id}: line"}},
            why_it_matters="w",
            remediation="r",
            references=(),
        )
        for rule_id in blocking
    )
    return ResultsReview(
        spec_id="s",
        experiment_id="e1",
        rules_run=tuple(rule.id for rule in RESULTS_RULES),
        findings=found,
    )


def test_the_effect_table_is_to_be_read_only_while_the_verdict_is_not_invalid(
    raw_spec: dict,
) -> None:
    context = _revenue_context(raw_spec)

    invalid = _report(context, _blocked(context, "RES-001"))
    caution = _report(context, _blocked(context))

    assert (invalid["effect"]["readable"], caution["effect"]["readable"]) == (False, True)
    assert "NOT TO BE READ: the verdict is invalid" in render_results_text(invalid)
    assert "NOT TO BE READ" not in render_results_text(caution)


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
        (None, "adjusted for 2 comparisons by Bonferroni"),
        ("none", "not adjusted for the number of arms (the spec registers none)"),
    ],
)
def test_the_text_says_how_the_p_values_were_adjusted(raw_spec: dict, registered, said) -> None:
    context = _revenue_context(raw_spec, design__alpha_adjustment=registered)

    text = " ".join(render_results_text(_report(context)).split())

    assert said in text
    assert "does not adjust for guardrails, other metrics or repeated looks" in text


def test_an_arm_without_an_estimate_is_listed_with_its_reason(raw_spec: dict) -> None:
    report = _report(_revenue_context(raw_spec, variant_c=(1.0,)))

    text = " ".join(render_results_text(report).split())

    b, c = report["effect"]["arms"]
    assert "error" in c and "error" not in b
    assert f"variant_c (1 vs 6): not estimated; {' '.join(c['error'].split())}" in text
    assert "variant_b 6 vs 6" in text  # the arm that could be estimated is in the table
