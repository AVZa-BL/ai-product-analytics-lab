import copy
import json

import pytest

from tests.propose_helpers import example_request, final_proposal, prop, small_proposal
from tracewright.plan import TrackingPlan
from tracewright.propose.check import check_proposal, merge, needs_repair, repair_feedback
from tracewright.propose.documents import Document
from tracewright.propose.proposal import Proposal


def doc(text="Players can apply coupons at checkout."):
    return Document(name="gdd.md", kind="text", text=text, data=None, sha256="0" * 64)


def run(raw_plan, edit=None, *, plan=True, documents=None, **kw):
    data = small_proposal()
    if edit:
        edit(data)
    return check_proposal(
        Proposal.from_dict(data),
        TrackingPlan.from_dict(copy.deepcopy(raw_plan)) if plan else None,
        documents or [doc()],
        **kw,
    )


def codes(result):
    return {p.code for p in result.problems}


def rule_ids(result):
    return {f.rule_id for f in result.introduced}


def test_a_clean_proposal_has_no_problems(raw_plan):
    result = run(raw_plan)
    assert not result.problems and not result.introduced and not result.blocking
    assert result.merged_plan is not None and not needs_repair(result)


def test_the_merged_plan_marks_new_events_planned(raw_plan):
    merged = run(raw_plan).merged_plan
    assert {e.name: e.status for e in merged.events}["coupon_applied"] == "planned"
    assert [m.name for m in merged.metrics] == ["conversion", "coupon_use"]


def test_the_review_sees_new_events_as_shipped(raw_plan):
    # Were they "planned", COV-003 would fire on every metric of every proposal.
    assert "COV-003" not in rule_ids(run(raw_plan))


def test_a_new_event_that_already_exists_is_a_collision(raw_plan):
    result = run(raw_plan, lambda d: d["new_events"][0].update(name="Checkout_Started"))
    assert "COLLISION" in codes(result) and result.merged_plan is None and result.blocking


def test_an_unknown_extended_or_reused_event(raw_plan):
    def edit(d):
        d["reused_events"] = [{"name": "ghost", "rationale": "r"}]

    assert "UNKNOWN_EVENT" in codes(run(raw_plan, edit))


def test_an_event_in_two_lists_or_twice(raw_plan):
    def edit(d):
        d["reused_events"] = [{"name": "coupon_applied", "rationale": "r"}]

    assert "DUPLICATE" in codes(run(raw_plan, edit))


def test_extending_with_a_property_that_exists(raw_plan):
    def edit(d):
        d["extended_events"] = [
            {
                "name": "order_completed",
                "rationale": "r",
                "evidence": {"kind": "inferred", "document": "", "quote": ""},
                "add_properties": [prop("cart_value", "number", reuses_existing=True)],
            }
        ]

    assert "DUPLICATE_PROPERTY" in codes(run(raw_plan, edit))


def test_extending_adds_the_property_to_the_existing_event(raw_plan):
    def edit(d):
        d["extended_events"] = [
            {
                "name": "order_completed",
                "rationale": "r",
                "evidence": {"kind": "inferred", "document": "", "quote": ""},
                "add_properties": [prop("coupon_code", "string")],
            }
        ]

    merged = run(raw_plan, edit).merged_plan
    order = next(e for e in merged.events if e.name == "order_completed")
    assert [p.name for p in order.properties][-1] == "coupon_code"


def test_a_metric_name_clash(raw_plan):
    result = run(raw_plan, lambda d: d["metrics"][0].update(name="conversion"))
    assert "METRIC_COLLISION" in codes(result)


def test_a_type_clash_with_the_existing_plan_is_found_by_the_rules(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"].append(prop("cart_value", "string", reuses_existing=True))

    result = run(raw_plan, edit)
    assert "SCH-001" in rule_ids(result) and result.blocking and needs_repair(result)


def test_every_layer_of_problems_is_reported_at_once(raw_plan):
    def edit(d):
        d["new_events"].append({**copy.deepcopy(d["new_events"][0]), "name": "order_completed"})
        d["new_events"][0]["properties"].append(prop("cart_value", "string", reuses_existing=True))
        d["new_events"][0]["properties"].append(prop("couponCode"))

    result = run(raw_plan, edit)
    assert "COLLISION" in codes(result)
    assert {"SCH-001", "NAM-002"} <= rule_ids(result)


def test_findings_the_plan_already_had_are_not_blamed_on_the_proposal(raw_plan):
    raw_plan["events"][0].pop("trigger")  # DOC-001 already fires on the plan
    result = run(raw_plan)
    assert result.baseline_review.findings and not result.introduced


def test_making_an_existing_finding_worse_is_blamed(raw_plan):
    raw_plan["events"][0]["name"] = "click"  # NAM-001 already fires, on "click" alone

    def edit(d):
        d["new_events"][0]["name"] = "CouponApplied"
        d["metrics"][0]["events"] = ["CouponApplied", "order_completed"]

    result = run(raw_plan, edit)
    assert {f.rule_id for f in result.introduced} >= {"NAM-001"}
    nam = next(f for f in result.introduced if f.rule_id == "NAM-001")
    assert nam.evidence["events"] == ["click", "CouponApplied"]


def test_an_event_nothing_uses_is_info_not_a_repair(raw_plan):
    def edit(d):
        d["metrics"][0]["events"] = ["order_completed"]

    result = run(raw_plan, edit)
    assert "COV-004" in rule_ids(result) and not needs_repair(result)


def test_missing_owner_is_reported_but_not_sent_for_repair(raw_plan):
    del raw_plan["owner"]
    result = run(raw_plan)
    assert "DOC-002" in rule_ids(result)
    assert not any("DOC-002" in line for line in repair_feedback(result))


def test_the_owner_option_is_recorded_on_new_events(raw_plan):
    del raw_plan["owner"]
    result = run(raw_plan, owner="growth")
    assert "DOC-002" not in rule_ids(result)
    merged = result.merged_plan
    assert next(e for e in merged.events if e.name == "coupon_applied").owner == "growth"


# --- evidence ---------------------------------------------------------------------------------


def test_a_found_quote_is_counted(raw_plan):
    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document",
            "document": "gdd.md",
            "quote": "Players can apply coupons at checkout.",
        }

    result = run(raw_plan, edit)
    assert result.grounding.quoted_found == 1 and not result.problems
    assert result.grounding.by_event == {"coupon_applied": "found"}


def test_a_quote_that_is_not_in_the_document_blocks(raw_plan):
    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "gdd.md", "quote": "Coupons expire after seven days."
        }

    result = run(raw_plan, edit)
    assert "EVIDENCE_QUOTE" in codes(result) and result.blocking
    assert result.grounding.quoted_missing == 1


def test_a_document_that_was_not_provided_blocks(raw_plan):
    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "other.md", "quote": "Players can apply coupons."
        }

    assert "EVIDENCE_DOCUMENT" in codes(run(raw_plan, edit))


def test_a_pdf_quote_is_unverifiable_and_not_blocking(raw_plan):
    pdf = Document(name="gdd.pdf", kind="pdf", text=None, data=b"%PDF-", sha256="0" * 64)

    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "gdd.pdf", "quote": "Players can apply coupons."
        }

    result = run(raw_plan, edit, documents=[pdf])
    assert result.grounding.unverifiable == 1 and not result.blocking


# --- reuse ------------------------------------------------------------------------------------


def test_a_reuse_claim_the_plan_cannot_back(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"][1]["reuses_existing"] = True

    assert "REUSE_CLAIM" in codes(run(raw_plan, edit))


def test_an_unflagged_reuse_is_only_info(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"][0]["reuses_existing"] = False

    result = run(raw_plan, edit)
    assert "REUSE_UNFLAGGED" in codes(result) and not result.blocking


# --- no existing plan --------------------------------------------------------------------------


def test_without_a_plan_identity_keys_are_required(raw_plan):
    result = run(raw_plan, plan=False)
    assert "IDENTITY" in codes(result) and result.merged_plan is None


def test_without_a_plan_a_new_plan_is_built(raw_plan):
    def edit(d):
        d["identity_keys"] = ["user_id"]
        d["metrics"][0]["events"] = ["coupon_applied"]

    result = run(raw_plan, edit, plan=False, owner="growth")
    assert not result.problems and not result.introduced
    assert result.merged_plan.id == "coupons" and result.merged_plan.identity_keys == ("user_id",)


# --- the worked example ------------------------------------------------------------------------


def test_the_example_final_proposal_is_clean():
    request = example_request()
    result = check_proposal(Proposal.from_dict(final_proposal()), request.plan, request.documents)
    assert not result.blocking and not result.problems and not result.introduced
    assert result.grounding.quoted_found == 6 and result.grounding.inferred == 1
    assert result.baseline_review.findings  # alliance_left's DOC-001, not blamed on the proposal


def test_the_example_first_attempt_has_the_planted_mistakes():
    from tests.propose_helpers import replay_attempts

    request = example_request()
    result = check_proposal(
        Proposal.from_dict(replay_attempts()[0]), request.plan, request.documents
    )
    assert {"COLLISION", "EVIDENCE_QUOTE"} <= codes(result)
    assert {"SCH-001", "NAM-002"} <= rule_ids(result)


def test_merge_does_not_modify_the_plan(raw_plan):
    plan = TrackingPlan.from_dict(copy.deepcopy(raw_plan))
    before = plan.sha256()
    merge(Proposal.from_dict(small_proposal()), plan, new_status="planned")
    assert plan.sha256() == before


@pytest.mark.parametrize("status", ["planned", "active"])
def test_merge_is_deterministic(raw_plan, status):
    plan = TrackingPlan.from_dict(copy.deepcopy(raw_plan))
    proposal = Proposal.from_dict(small_proposal())
    first = merge(proposal, plan, new_status=status)
    assert first.sha256() == merge(proposal, plan, new_status=status).sha256()


# --- findings the model cannot clear are reported, not sent back ---------------------------------


def test_cov_003_is_reported_but_never_sent_back(raw_plan):
    raw_plan["events"].append(
        {
            "name": "beta_seen",
            "status": "planned",
            "description": "d",
            "trigger": "t",
            "properties": [{"name": "user_id", "type": "string", "required": True}],
        }
    )

    def edit(d):
        d["metrics"][0]["events"] = ["coupon_applied", "beta_seen"]

    result = run(raw_plan, edit)
    assert "COV-003" in rule_ids(result)
    assert not any("COV-003" in line for line in repair_feedback(result))
    assert not needs_repair(result)


# --- the plan's own conflict is not the proposal's to fix ---------------------------------------


def conflicted(raw_plan):
    raw_plan["events"][1]["properties"][1]["type"] = "string"  # cart_value: number vs string
    return raw_plan


def test_reusing_a_property_the_plan_already_has_in_two_types_is_not_blamed(raw_plan):
    def edit(d):
        extra = prop("cart_value", "number", reuses_existing=True)
        d["new_events"][0]["properties"].append(extra)

    result = run(conflicted(raw_plan), edit)
    assert "SCH-001" not in rule_ids(result) and not result.blocking
    assert result.baseline_review.blocking_rule_ids == ("SCH-001",)


def test_a_new_type_on_a_conflicted_property_is_blamed(raw_plan):
    def edit(d):
        extra = prop("cart_value", "boolean", reuses_existing=True)
        d["new_events"][0]["properties"].append(extra)

    assert "SCH-001" in rule_ids(run(conflicted(raw_plan), edit))


def test_a_new_conflicting_property_is_blamed_even_beside_an_old_conflict(raw_plan):
    def edit(d):  # "method" is an enum in the plan
        d["new_events"][0]["properties"].append(prop("method", "string", reuses_existing=True))

    assert "SCH-001" in rule_ids(run(conflicted(raw_plan), edit))


# --- events that differ only in letter case ----------------------------------------------------


def case_variants(raw_plan):
    raw_plan["events"].append(
        {
            "name": "Checkout_Started",
            "description": "d",
            "trigger": "t",
            "properties": [
                {"name": "user_id", "type": "string", "required": True},
                {"name": "mode", "type": "string"},
            ],
        }
    )
    return raw_plan


def extend(name, *props):
    def edit(d):
        d["extended_events"] = [
            {
                "name": name,
                "rationale": "r",
                "evidence": {"kind": "inferred", "document": "", "quote": ""},
                "add_properties": list(props),
            }
        ]

    return edit


def test_an_exact_name_picks_exactly_one_of_two_case_variants(raw_plan):
    result = run(case_variants(raw_plan), extend("checkout_started", prop("coupon_code")))
    assert not result.blocking
    events = {e.name: [p.name for p in e.properties] for e in result.merged_plan.events}
    assert "coupon_code" in events["checkout_started"]
    assert "coupon_code" not in events["Checkout_Started"]


def test_a_duplicate_property_is_checked_against_the_event_that_is_edited(raw_plan):
    # "mode" exists only on Checkout_Started, so adding it to checkout_started is fine.
    result = run(case_variants(raw_plan), extend("checkout_started", prop("mode")))
    assert not result.blocking and "DUPLICATE_PROPERTY" not in codes(result)


def test_a_name_matching_two_variants_and_neither_exactly_is_ambiguous(raw_plan):
    raw_plan["events"][0]["name"] = "checkout_started"
    raw_plan["events"].append({**copy.deepcopy(raw_plan["events"][0]), "name": "CHECKOUT_STARTED"})
    raw_plan["metrics"][0]["events"] = ["checkout_started", "order_completed"]
    result = run(raw_plan, extend("Checkout_Started", prop("coupon_code")))
    assert "AMBIGUOUS_EVENT" in codes(result) and result.merged_plan is None


def test_one_case_variant_is_found_when_it_is_the_only_match(raw_plan):
    result = run(raw_plan, extend("Checkout_Started", prop("coupon_code")))
    assert not result.blocking
    started = next(e for e in result.merged_plan.events if e.name == "checkout_started")
    assert started.properties[-1].name == "coupon_code"


# --- severity and routing of every kind of problem ----------------------------------------------


def test_a_reuse_claim_is_a_warning_that_is_repaired_but_does_not_block(raw_plan):
    result = run(
        raw_plan, lambda d: d["new_events"][0]["properties"][1].update(reuses_existing=True)
    )
    problem = next(p for p in result.problems if p.code == "REUSE_CLAIM")
    assert problem.severity == "warning" and not result.blocking and needs_repair(result)


def test_info_problems_are_reported_and_not_repaired(raw_plan):
    unflagged = run(
        raw_plan, lambda d: d["new_events"][0]["properties"][0].update(reuses_existing=False)
    )
    assert not needs_repair(unflagged)
    pdf = Document(name="gdd.pdf", kind="pdf", text=None, data=b"%PDF-", sha256="0" * 64)

    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "gdd.pdf", "quote": "a quote of twelve"
        }

    assert not needs_repair(run(raw_plan, edit, documents=[pdf]))


@pytest.mark.parametrize("label", ["extended_events", "reused_events"])
def test_an_unknown_event_is_a_blocker_in_either_list(raw_plan, label):
    def edit(d):
        item = {"name": "ghost", "rationale": "r"}
        if label == "extended_events":
            item.update(
                evidence={"kind": "inferred", "document": "", "quote": ""},
                add_properties=[prop("x_y")],
            )
        d[label] = [item]

    result = run(raw_plan, edit)
    assert "UNKNOWN_EVENT" in codes(result) and result.blocking


def test_the_same_event_twice_in_one_list_is_a_duplicate(raw_plan):
    def edit(d):
        d["new_events"].append(copy.deepcopy(d["new_events"][0]))

    assert "DUPLICATE" in codes(run(raw_plan, edit))


def test_evidence_can_cite_any_of_several_documents(raw_plan):
    other = Document(
        name="notes.md", kind="text", text="Coupons stack up to three.", data=None, sha256="1" * 64
    )

    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "notes.md", "quote": "Coupons stack up to three."
        }

    result = run(raw_plan, edit, documents=[doc(), other])
    assert result.grounding.quoted_found == 1 and not result.problems


# --- personal data flows through the whole pipeline ---------------------------------------------


def test_a_property_marked_pii_survives_check_merge_and_report(raw_plan):
    from tracewright.propose.render import render_markdown
    from tracewright.propose.request import ProposalRequest, ProposerResponse
    from tracewright.propose.run import run_proposal

    def edit(d):
        d["new_events"][0]["properties"].append(prop("contact_email", pii=True))

    result = run(raw_plan, edit)
    assert "GOV-001" not in rule_ids(result)  # marked, so not flagged
    merged = next(e for e in result.merged_plan.events if e.name == "coupon_applied")
    assert next(p for p in merged.properties if p.name == "contact_email").pii is True

    data = small_proposal()
    data["new_events"][0]["properties"].append(prop("contact_email", pii=True))

    class Fixed:
        def propose(self, request, feedback):
            return ProposerResponse(text=json.dumps(data))

    request = ProposalRequest(
        documents=(doc(),), plan=TrackingPlan.from_dict(copy.deepcopy(raw_plan))
    )
    report = render_markdown(run_proposal(request, Fixed(), max_repairs=0))
    row = next(line for line in report.splitlines() if "`contact_email`" in line)
    assert "| yes |" in row.split("`contact_email`")[1]  # the PII column says yes


def test_a_personal_data_property_not_marked_pii_is_sent_back(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"].append(prop("contactEmail"))

    result = run(raw_plan, edit)
    assert "GOV-001" in rule_ids(result) and result.blocking
