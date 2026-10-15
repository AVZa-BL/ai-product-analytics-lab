import json
import re

import pytest

from tests.propose_helpers import example_request, final_proposal, small_proposal
from tracewright.propose.documents import Document
from tracewright.propose.render import (
    _cell,
    _code,
    _code_cell,
    _line,
    render_json,
    render_markdown,
)
from tracewright.propose.request import ProposalRequest, ProposerResponse
from tracewright.propose.run import run_proposal


class Fixed:
    def __init__(self, *texts):
        self.texts = list(texts)

    def propose(self, request, feedback):
        return ProposerResponse(text=self.texts.pop(0), model="fake")


def run(data, request=None, **kw):
    text = data if isinstance(data, str) else json.dumps(data)
    return run_proposal(request or example_request(), Fixed(text), max_repairs=0, **kw)


# --- escaping ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("<script>alert(1)</script>", "&lt;script>alert(1)&lt;/script>"),
        ("![i](https://evil.example/p.png)", "!\\[i\\](https://evil.example/p.png)"),
    ],
)
def test_html_and_link_syntax_are_defused(text, expected):
    assert _line(text) == expected


def test_a_pipe_cannot_end_a_table_cell():
    assert _cell("a | b") == "a \\| b"
    assert _code_cell("a|b") == "`a\\|b`"


def test_a_backtick_cannot_end_a_code_span():
    assert _code("a`b") == "`a'b`"


def test_hostile_model_text_cannot_make_a_link_an_image_or_a_new_table_row():
    data = final_proposal()
    hostile = "x ![p](https://evil.example/leak) [c](https://evil.example/l) | extra\n| a | b |"
    data["new_events"][0]["rationale"] = hostile
    data["new_events"][0]["properties"][0]["description"] = hostile
    data["assumptions"] = [hostile]
    report = render_markdown(run(data))
    assert "![" not in report.replace("!\\[", "")
    assert "](https://evil" in report  # kept as text...
    assert "\\](https://evil" in report  # ...but its brackets are escaped, so it is not a link
    for line in report.splitlines():  # no stray table row was made from the injected text
        if line.startswith("| a | b |"):
            pytest.fail("injected text became a table row")


def test_a_backslash_cannot_undo_an_escape():
    data = final_proposal()
    data["feature"]["name"] = "\\[x\\](https://evil.example/l)"
    data["new_events"][0]["properties"][-1]["name"] = "cost\\|rest"
    report = render_markdown(run(data))
    # A `](` is a live link unless its bracket has an odd number of backslashes before it.
    assert not re.search(r"(?<!\\)(?:\\\\)*\]\(", report)
    # Likewise a pipe ends a table cell unless an odd number of backslashes precedes it.
    (row,) = [line for line in report.splitlines() if line.startswith("| `cost")]
    assert len(re.split(r"(?<!\\)(?:\\\\)*\|", row)) == 8  # six cells between the outer pipes


# --- the labels a reader relies on --------------------------------------------------------------


def test_each_evidence_state_has_its_own_label():
    pdf = Document(name="gdd.pdf", kind="pdf", text=None, data=b"%PDF-", sha256="0" * 64)
    request = ProposalRequest(
        documents=example_request().documents + (pdf,), plan=example_request().plan
    )
    data = final_proposal()
    data["new_events"][0]["evidence"] = {
        "kind": "document", "document": "gdd.pdf", "quote": "a quote from the pdf"
    }
    data["new_events"][2]["evidence"] = {  # event 1 stays "inferred"; the rest are found
        "kind": "document", "document": "gdd.md", "quote": "Players can win a free car."
    }
    report = render_markdown(run(data, request))
    assert "from a PDF; not machine-checked" in report
    assert "QUOTE NOT FOUND" in report
    assert "quote found in the document" in report
    assert "analyst's judgement, not from the documents" in report


# --- the report when nothing usable came back ----------------------------------------------------


def test_a_response_that_is_not_a_proposal_gets_an_honest_report():
    result = run({"foo": 1})
    report = render_markdown(result)
    assert report.startswith("# Tracking proposal: no valid proposal")
    assert "UNRESOLVED" in report and "Status: OK" not in report and "is required" in report
    data = json.loads(render_json(result))
    assert data["status"] == "unresolved" and data["proposal"] is None
    assert data["schema_violations"]


# --- what the report says about the existing plan ------------------------------------------------


def test_a_blocker_the_plan_already_had_is_named_in_the_report(raw_plan):
    from tracewright.plan import TrackingPlan

    raw_plan["events"][1]["properties"][1]["type"] = "string"  # SCH-001 in the plan itself
    plan = TrackingPlan.from_dict(raw_plan)
    request = ProposalRequest(documents=example_request().documents, plan=plan)
    report = render_markdown(run(small_proposal(), request))
    assert "Status: OK" in report
    assert "1 blocker, 0 warning, 0 info" in report
    assert "will still recommend REVISE" in report and "SCH-001" in report


# --- files that exist only when the proposal is usable -------------------------------------------


def test_the_note_is_absent_when_no_metric_uses_a_new_event():
    data = small_proposal()
    data["metrics"] = []
    assert "marks the new events" not in render_markdown(run(data))
