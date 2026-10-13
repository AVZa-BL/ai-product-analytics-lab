"""The design-review report and its two renderings."""

import json

import pytest

from referee import __version__
from referee.findings import DesignReview, Finding
from referee.report import REPORT_VERSION, design_report, render_json, render_text
from referee.review import review_design
from referee.rules import ALL_RULES
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


@pytest.fixture
def mixed_report(raw_spec: dict) -> dict:
    return make_report(
        raw_spec,
        finding("PRO-004", "info"),
        finding("DES-001", "blocker", evidence={"required_total": 389060, "ratio": 0.131}),
        finding("HYP-002", "warning", references=("A paper.", "A book.")),
        finding("PRO-001", "blocker"),
    )


# --- The report ------------------------------------------------------------------------


def test_the_report_names_the_spec_the_version_and_the_verdict(mixed_report: dict) -> None:
    assert mixed_report["report_version"] == REPORT_VERSION == 1
    assert mixed_report["kind"] == "design_review"
    assert mixed_report["referee_version"] == __version__
    assert mixed_report["spec"] == {
        "id": "hybrid_offer_page_2026_10",
        "title": "Subscription offer page variants",
        "sha256": SECTION_6_SHA256,
    }
    assert mixed_report["recommendation"] == "revise"
    assert mixed_report["blocking_rule_ids"] == ["DES-001", "PRO-001"]
    assert mixed_report["counts"] == {"blocker": 2, "warning": 1, "info": 1}


def test_the_report_keeps_its_keys_in_a_fixed_order(mixed_report: dict) -> None:
    assert list(mixed_report) == [
        "report_version",
        "kind",
        "referee_version",
        "spec",
        "recommendation",
        "blocking_rule_ids",
        "counts",
        "findings",
    ]
    assert list(mixed_report["findings"][0]) == [
        "rule_id",
        "severity",
        "title",
        "evidence",
        "why_it_matters",
        "remediation",
        "references",
    ]


def test_findings_come_in_severity_then_rule_order(mixed_report: dict) -> None:
    assert [f["rule_id"] for f in mixed_report["findings"]] == [
        "DES-001",
        "PRO-001",
        "HYP-002",
        "PRO-004",
    ]


def test_a_finding_in_the_report_carries_everything_the_rule_said(mixed_report: dict) -> None:
    assert mixed_report["findings"][0] == {
        "rule_id": "DES-001",
        "severity": "blocker",
        "title": "Title of DES-001",
        "evidence": {"required_total": 389060, "ratio": 0.131},
        "why_it_matters": "Why DES-001 matters.",
        "remediation": "How to fix DES-001.",
        "references": [],
    }
    assert mixed_report["findings"][2]["references"] == ["A paper.", "A book."]


def test_a_review_without_findings_proceeds(raw_spec: dict) -> None:
    report = make_report(raw_spec)

    assert report["recommendation"] == "proceed"
    assert report["blocking_rule_ids"] == []
    assert report["counts"] == {"blocker": 0, "warning": 0, "info": 0}
    assert report["findings"] == []


# --- JSON ------------------------------------------------------------------------------


def test_the_json_is_indented_ends_with_a_newline_and_loads_back_to_the_report(
    mixed_report: dict,
) -> None:
    text = render_json(mixed_report)

    assert text.endswith("}\n")
    assert text.startswith('{\n  "report_version": 1,\n')
    assert json.loads(text) == mixed_report


def test_the_json_is_ascii_even_when_the_spec_is_not(raw_spec: dict) -> None:
    raw_spec["title"] = "Café – offer page"

    text = render_json(make_report(raw_spec))

    assert text.isascii()
    assert json.loads(text)["spec"]["title"] == "Café – offer page"


def test_the_json_refuses_a_non_finite_number(raw_spec: dict) -> None:
    report = make_report(raw_spec, finding("DES-001", "blocker", evidence={"x": float("nan")}))

    with pytest.raises(ValueError, match="not JSON compliant"):
        render_json(report)


def test_the_same_spec_gives_the_same_bytes_however_it_was_laid_out(raw_spec: dict) -> None:
    reordered = {key: raw_spec[key] for key in reversed(raw_spec)}

    first = render_json(design_report(*_review(raw_spec)))
    second = render_json(design_report(*_review(reordered)))

    assert first == second


def _review(raw: dict) -> tuple[ExperimentSpec, DesignReview]:
    spec = ExperimentSpec.from_dict(raw)
    return spec, review_design(spec)


# --- Text ------------------------------------------------------------------------------


def test_text_of_a_review_with_nothing_to_say_is_exact(raw_spec: dict) -> None:
    assert render_text(make_report(raw_spec)) == (
        "Referee design review\n"
        "Spec:      hybrid_offer_page_2026_10 - Subscription offer page variants\n"
        f"Spec hash: sha256:{SECTION_6_SHA256}\n"
        f"Referee:   {__version__}\n"
        "\n"
        "Recommendation: PROCEED\n"
        "Findings: none\n"
        "\n"
        "Referee is advisory: it recommends, and does not approve or stop an experiment.\n"
    )


def test_text_of_findings_is_exact(raw_spec: dict) -> None:
    report = make_report(
        raw_spec,
        finding(
            "DES-001",
            "blocker",
            evidence={"n": 5, "name": "x", "nothing": None, "nested": {"a": 1.5}},
            references=("A paper.", "A book."),
        ),
        finding("PRO-004", "info"),
    )

    assert render_text(report) == (
        "Referee design review\n"
        "Spec:      hybrid_offer_page_2026_10 - Subscription offer page variants\n"
        f"Spec hash: sha256:{SECTION_6_SHA256}\n"
        f"Referee:   {__version__}\n"
        "\n"
        "Recommendation: REVISE\n"
        "Blocking rules: DES-001\n"
        "Findings: blockers 1, warnings 0, info 1\n"
        "\n"
        "[BLOCKER] DES-001: Title of DES-001\n"
        "    Evidence:\n"
        "      n: 5\n"
        '      name: "x"\n'
        "      nothing: null\n"
        '      nested: {"a": 1.5}\n'
        "    Why it matters:\n"
        "      Why DES-001 matters.\n"
        "    What to do:\n"
        "      How to fix DES-001.\n"
        "    References:\n"
        "      - A paper.\n"
        "      - A book.\n"
        "\n"
        "[INFO] PRO-004: Title of PRO-004\n"
        "    Why it matters:\n"
        "      Why PRO-004 matters.\n"
        "    What to do:\n"
        "      How to fix PRO-004.\n"
        "\n"
        "Referee is advisory: it recommends, and does not approve or stop an experiment.\n"
    )


def test_long_paragraphs_wrap_at_88_columns_without_losing_a_word(raw_spec: dict) -> None:
    long_text = " ".join(f"word{i}" for i in range(60))
    reference = "Author. " + long_text
    report = make_report(
        raw_spec,
        finding("DES-001", "blocker", why_it_matters=long_text, references=(reference,)),
    )

    lines = render_text(report).splitlines()
    why = lines[lines.index("    Why it matters:") + 1 : lines.index("    What to do:")]
    refs = lines[lines.index("    References:") + 1 : -2]

    assert len(why) > 1 and all(len(line) <= 88 and line.startswith("      ") for line in why)
    assert " ".join(line.strip() for line in why) == long_text
    assert refs[0].startswith("      - ") and all(line.startswith("        ") for line in refs[1:])
    assert " ".join(line.strip(" -") for line in refs) == reference


def test_text_keeps_non_ascii_as_it_is(raw_spec: dict) -> None:
    raw_spec["title"] = "Café – offer page"

    assert "hybrid_offer_page_2026_10 - Café – offer page" in render_text(make_report(raw_spec))


def test_a_saved_json_report_renders_to_the_same_text(mixed_report: dict) -> None:
    assert render_text(json.loads(render_json(mixed_report))) == render_text(mixed_report)


# --- All 17 rules ----------------------------------------------------------------------


def test_a_spec_that_breaks_every_rule_reports_all_seventeen(worst_raw_spec: dict) -> None:
    spec, review = _review(worst_raw_spec)

    assert sorted(f.rule_id for f in review.findings) == sorted(rule.id for rule in ALL_RULES)
    assert len(review.findings) == 17


def test_every_kind_of_evidence_renders_in_both_formats(worst_raw_spec: dict) -> None:
    spec, review = _review(worst_raw_spec)
    report = design_report(spec, review)

    from_json = json.loads(render_json(report))
    text = render_text(report)

    assert from_json == json.loads(json.dumps(report))
    assert [f["rule_id"] for f in from_json["findings"]] == [f.rule_id for f in review.findings]
    assert all(f"{f.rule_id}: {f.title}" in text for f in review.findings)
    assert from_json["counts"] == {"blocker": 4, "warning": 11, "info": 2}
