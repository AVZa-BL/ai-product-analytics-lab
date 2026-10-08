"""Helpers shared by the tests of the proposer."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tracewright.loader import load_plan
from tracewright.propose.documents import load_documents
from tracewright.propose.request import ProposalRequest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "alliance-treasure-hunt"
GOLDEN = ROOT / "tests" / "golden" / "alliance-treasure-hunt"


def replay_attempts() -> list[dict]:
    return json.loads((EXAMPLE / "replayed-model-response.json").read_text(encoding="utf-8"))


def final_proposal() -> dict:
    return copy.deepcopy(replay_attempts()[-1])


def example_request(*, with_plan: bool = True) -> ProposalRequest:
    return ProposalRequest(
        documents=load_documents([str(EXAMPLE / "gdd.md")]),
        plan=load_plan(EXAMPLE / "current-tracking-plan.yaml") if with_plan else None,
    )


def prop(name: str, type_: str = "string", **kw) -> dict:
    base = {
        "name": name,
        "type": type_,
        "required": False,
        "pii": False,
        "allowed_values": [],
        "description": f"The {name}.",
        "rationale": f"Needed for {name}.",
        "reuses_existing": False,
    }
    return {**base, **kw}


def small_proposal(**changes) -> dict:
    """A small valid proposal against the checkout plan in conftest's `raw_plan`."""
    data = {
        "feature": {"id": "coupons", "name": "Coupons", "summary": "Players apply coupons."},
        "identity_keys": [],
        "new_events": [
            {
                "name": "coupon_applied",
                "description": "A coupon is applied.",
                "trigger": "The coupon is accepted.",
                "priority": "must",
                "rationale": "Measures coupon use.",
                "evidence": {"kind": "inferred", "document": "", "quote": ""},
                "properties": [
                    prop("user_id", required=True, reuses_existing=True),
                    prop("coupon_code", "string"),
                ],
            }
        ],
        "extended_events": [],
        "reused_events": [],
        "metrics": [
            {
                "name": "coupon_use",
                "definition": "Coupons applied per order.",
                "events": ["coupon_applied", "order_completed"],
                "rationale": "Adoption.",
            }
        ],
        "not_tracked": [],
        "assumptions": [],
        "open_questions": [],
    }
    data.update(changes)
    return data
