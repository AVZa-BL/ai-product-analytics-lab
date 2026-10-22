"""The design-review and results-review reports and their renderings."""

import json

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


def _report(context: ResultsContext, review: ResultsReview | None = None, source=None) -> dict:
    review = review or review_context(context)
    return results_report(review, context, file_hashes=HASHES, as_of_source=source)


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
