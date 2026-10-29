"""The deterministic checks: what a draft may not get away with."""

from __future__ import annotations

from typing import Any

import pytest
from referee.loader import load_spec
from referee.power import plan_power, power_alpha_adjustment
from referee.spec import ExperimentSpec
from tracewright.propose.documents import Document

from specwright.check import CheckResult, check_draft, power_adjustment, repair_feedback
from specwright.draft import Draft
from tests.helpers import ROOT, SHOP, claim, documents, replay, shop_draft, text_document, without

POWERED = ROOT.parent / "referee" / "examples" / "offer-page-powered.yaml"


def check(data: dict, *docs: Document, brief: str = SHOP, owner: str | None = None) -> CheckResult:
    return check_draft(Draft.from_dict(data), (*documents(brief), *docs), owner=owner)


def codes(result: CheckResult, severity: str | None = None) -> list[str]:
    return [p.code for p in result.problems if severity in (None, p.severity)]


def stated(path: str, value: float) -> dict:
    evidence = {"kind": "inferred", "document": "", "quote": "", "note": ""}
    return {"path": path, "value": value, "evidence": evidence}


def label(data: dict, path: str, kind: str, value: Any = None, note: str = "") -> dict:
    c = claim(data, path)
    c["value"] = value
    c["evidence"] = {"kind": kind, "document": "", "quote": "", "note": note}
    return data


def test_the_shop_banner_draft_is_ok_and_its_warnings_are_findings_not_repairs() -> None:
    result = check(shop_draft())

    assert (result.status, result.blockers, result.questions) == ("ok", (), ())
    assert {"RULE:DES-008", "RULE:HYP-002"} <= set(codes(result, "warning"))
    assert result.to_repair == () and repair_feedback(result) == []
    assert result.spec is not None and result.values["design.alpha"] == 0.05


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            lambda d: claim(d, "design.mde_relative")["evidence"].update(
                quote="A big lift please."
            ),
            "QUOTE_NOT_FOUND",
        ),
        (
            lambda d: claim(d, "design.mde_relative")["evidence"].update(document="other.md"),
            "QUOTE_DOCUMENT",
        ),
        (lambda d: claim(d, "primary_metric.baseline").update(value=0.05), "NUMBER_NOT_IN_QUOTE"),
        (lambda d: claim(d, "design.mde_relative").update(value=0.12), "NUMBER_NOT_IN_QUOTE"),
        (lambda d: claim(d, "design.min_duration_days").update(value=10), "NUMBER_NOT_IN_QUOTE"),
    ],
    ids=[
        "quote-not-found",
        "document-not-provided",
        "baseline-not-in-quote",
        "lift-not-in-quote",
        "days-not-in-quote",
    ],
)
def test_a_quote_that_is_not_in_the_document_or_a_number_not_in_its_quote_is_a_repairable_blocker(
    change, code: str
) -> None:
    data = shop_draft()
    change(data)

    result = check(data)

    assert code in codes(result, "blocker") and result.status == "unresolved"
    assert any(p.code == code and p.repairable for p in result.to_repair)
    assert any(line.startswith(f"[{code}]") for line in repair_feedback(result))


@pytest.mark.parametrize(
    "wording",
    [
        "roughly 12,000 players a day open the shop",
        "approximately 12,000 players a day open the shop",
        "up to 12,000 players a day open the shop",
        "12,000 or so players a day open the shop",
    ],
)
def test_approximate_wording_is_never_accepted_as_a_number(wording: str) -> None:
    data = shop_draft()
    c = claim(data, "population.daily_eligible_units")
    c["evidence"].update(document="hedge.md", quote=wording)
    hedged = text_document("hedge.md", f"The brief says {wording}.")

    result = check(data, hedged)

    assert "AMBIGUOUS_WORDING" in codes(result, "blocker")
    assert "NUMBER_NOT_IN_QUOTE" not in codes(
        result
    )  # the number is there; the wording is the fault


def test_a_number_the_model_labels_inferred_is_accepted_and_listed_for_the_analyst() -> None:
    result = check(label(shop_draft(), "design.alpha", "inferred", 0.05, "the usual 5%"))

    assert result.status == "ok"
    assert [c.path for c in result.inferred if c.path == "design.alpha"] == ["design.alpha"]


@pytest.mark.parametrize("path", ["primary_metric.baseline", "design.planned_duration_days"])
@pytest.mark.parametrize("kind", ["missing", "ambiguous"])
def test_a_required_field_the_documents_do_not_give_makes_a_needs_answers_not_an_invented_spec(
    path: str, kind: str
) -> None:
    result = check(label(shop_draft(), path, kind, None, "What is it?"))

    assert result.status == "needs_answers"
    assert [(q.path, q.kind, q.note) for q in result.questions] == [(path, kind, "What is it?")]
    assert result.spec is None and result.spec_dict is None and result.plan is None
    assert result.blockers == () and result.to_repair == ()  # nothing to repair: it must be asked


def test_a_required_field_left_out_is_a_repairable_blocker_not_a_silent_gap() -> None:
    result = check(without(shop_draft(), "primary_metric.baseline"))

    assert result.status == "unresolved"
    assert [(q.path, q.kind) for q in result.questions] == [("primary_metric.baseline", "omitted")]
    assert any(p.code == "FIELD_OMITTED" and p.repairable for p in result.to_repair)


def test_an_optional_field_marked_missing_is_listed_and_does_not_stop_the_spec() -> None:
    data = shop_draft()
    data["claims"].append(
        {
            "path": "design.pre_period_covariate",
            "value": None,
            "evidence": {
                "kind": "missing",
                "document": "",
                "quote": "",
                "note": "Is there a covariate?",
            },
        }
    )

    result = check(data)

    assert result.status == "ok" and [q.path for q in result.optional_questions] == [
        "design.pre_period_covariate"
    ]


def test_an_owner_given_on_the_command_line_stands_in_for_the_owner_claim() -> None:
    result = check(without(shop_draft(), "owner"), owner="analytics")

    assert result.status == "ok" and result.spec is not None and result.spec.owner == "analytics"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda d: without(d, "procedure.stopping_rule"), "RULE:PRO-001"),
        (
            lambda d: claim(d, "hypothesis.alternative").update(
                value=claim(d, "hypothesis.null")["value"]
            ),
            "RULE:HYP-001",
        ),
        (
            lambda d: label(d, "population.exposure_timing", "inferred", "post_treatment"),
            "RULE:DES-007",
        ),
        (lambda d: label(d, "arms[0].allocation", "inferred", 0.7), "SPEC"),
    ],
    ids=[
        "no-stopping-rule",
        "same-hypothesis",
        "exposure-after-treatment",
        "allocations-do-not-sum-to-one",
    ],
)
def test_a_blocker_of_the_design_rules_or_a_spec_referee_refuses_goes_back_to_the_model(
    change, code: str
) -> None:
    data = shop_draft()
    change(data)

    result = check(data)

    assert code in codes(result, "blocker") and result.status == "unresolved"
    assert any(p.code == code for p in result.to_repair)
    assert any(code in line for line in repair_feedback(result))


def test_only_blockers_go_back_so_a_warning_never_asks_the_model_to_invent() -> None:
    result = check(shop_draft())

    assert codes(result, "warning") and not [p for p in result.to_repair if p.severity != "blocker"]


def test_stated_numbers_that_cannot_reach_the_power_are_infeasible_and_are_not_sent_back() -> None:
    data = replay("02-infeasible-niche-event")
    result = check(data, brief="02-infeasible-niche-event")

    assert result.status == "infeasible" and codes(result, "blocker") == ["RULE:DES-001"]
    assert result.to_repair == () and repair_feedback(result) == []
    plan = plan_power(result.spec)
    assert (plan.required_total, plan.is_powered) == (result.plan.required_total, False)
    # none of the documents' numbers was changed to make the design pass
    assert result.values["population.daily_eligible_units"] == 300
    assert result.values["design.planned_duration_days"] == 14


def test_a_target_effect_that_cannot_exist_is_infeasible_with_the_reason() -> None:
    data = label(shop_draft(), "primary_metric.baseline", "inferred", 0.95)
    label(data, "design.mde_relative", "inferred", 0.5)

    result = check(data)

    assert result.status == "infeasible" and result.plan is None and result.plan_error


@pytest.mark.parametrize(
    ("path", "said", "ours_text"),
    [
        ("stated.required_total_players", 20000, "16,412 players"),
        ("stated.required_days", 30, "5 days"),
    ],
)
def test_a_size_the_draft_states_that_differs_from_referees_is_flagged_and_not_used(
    path: str, said: float, ours_text: str
) -> None:
    data = without(replay("08-stated-size-differs"), "stated.required_total_players")
    data["claims"].append(stated(path, said))

    result = check(data, brief="08-stated-size-differs")

    flagged = [p for p in result.problems if p.code == "SIZE_DIFFERS"]
    assert result.status == "ok" and [p.path for p in flagged] == [path]
    assert ours_text in flagged[0].message and flagged[0].severity == "warning"
    assert "stated" not in result.spec_dict  # the stated size is not a field of the spec


def test_a_size_within_one_percent_of_referees_is_not_flagged() -> None:
    data = replay("08-stated-size-differs")
    claim(data, "stated.required_total_players")["value"] = 16400
    claim(data, "stated.required_total_players")["evidence"] = {
        "kind": "inferred",
        "document": "",
        "quote": "",
        "note": "",
    }

    assert "SIZE_DIFFERS" not in codes(check(data, brief="08-stated-size-differs"))


@pytest.mark.parametrize("adjustment", [None, "none", "bonferroni", "dunnett"])
def test_the_alpha_adjustment_used_for_the_sizes_is_the_one_referee_plans_with(adjustment) -> None:
    raw = load_spec(POWERED).to_dict()
    raw["design"].pop("alpha_adjustment", None)
    if adjustment:
        raw["design"]["alpha_adjustment"] = adjustment
    spec = ExperimentSpec.from_dict(raw)

    assert power_adjustment(spec) == power_alpha_adjustment(spec)


def test_a_quote_from_a_pdf_cannot_be_searched_and_is_reported_not_rejected() -> None:
    pdf = Document(name="plan.pdf", kind="pdf", text=None, data=b"%PDF-1.7", sha256="0" * 64)
    data = shop_draft()
    claim(data, "design.alpha")["evidence"].update(
        document="plan.pdf", quote="Alpha 0.05, power 80%"
    )

    result = check(data, pdf)

    assert "QUOTE_UNVERIFIABLE" in codes(result, "info") and "QUOTE_NOT_FOUND" not in codes(result)
