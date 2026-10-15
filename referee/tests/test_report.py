"""The design-review report and its two renderings."""

import json

import pytest

from referee.findings import DesignReview, Finding
from referee.report import design_report, render_json
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


# --- All 17 rules ----------------------------------------------------------------------


