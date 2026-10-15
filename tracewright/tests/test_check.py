import copy
import json

from tests.propose_helpers import prop, small_proposal
from tracewright.plan import TrackingPlan
from tracewright.propose.check import check_proposal, needs_repair, repair_feedback
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


def test_a_metric_name_clash(raw_plan):
    result = run(raw_plan, lambda d: d["metrics"][0].update(name="conversion"))
    assert "METRIC_COLLISION" in codes(result)


def test_a_type_clash_with_the_existing_plan_is_found_by_the_rules(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"].append(prop("cart_value", "string", reuses_existing=True))

    result = run(raw_plan, edit)
    assert "SCH-001" in rule_ids(result) and result.blocking and needs_repair(result)


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


def test_a_quote_that_is_not_in_the_document_blocks(raw_plan):
    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "gdd.md", "quote": "Coupons expire after seven days."
        }

    result = run(raw_plan, edit)
    assert "EVIDENCE_QUOTE" in codes(result) and result.blocking
    assert result.grounding.quoted_missing == 1


def test_a_pdf_quote_is_unverifiable_and_not_blocking(raw_plan):
    pdf = Document(name="gdd.pdf", kind="pdf", text=None, data=b"%PDF-", sha256="0" * 64)

    def edit(d):
        d["new_events"][0]["evidence"] = {
            "kind": "document", "document": "gdd.pdf", "quote": "Players can apply coupons."
        }

    result = run(raw_plan, edit, documents=[pdf])
    assert result.grounding.unverifiable == 1 and not result.blocking


# --- reuse ------------------------------------------------------------------------------------


def test_an_unflagged_reuse_is_only_info(raw_plan):
    def edit(d):
        d["new_events"][0]["properties"][0]["reuses_existing"] = False

    result = run(raw_plan, edit)
    assert "REUSE_UNFLAGGED" in codes(result) and not result.blocking


# --- no existing plan --------------------------------------------------------------------------


def test_without_a_plan_identity_keys_are_required(raw_plan):
    result = run(raw_plan, plan=False)
    assert "IDENTITY" in codes(result) and result.merged_plan is None


# --- the worked example ------------------------------------------------------------------------


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


