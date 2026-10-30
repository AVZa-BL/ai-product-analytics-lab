"""The sheet, the request and the egress assertion of the model path (design 24.4 and 24.16).

What the narrator is shown for each question that needs one, and the proof that nothing of the
report that code did not write is in it. The canary test is the proof for what a vocabulary check
cannot see: it replaces the free text of the committed report with canaries and requires that none
reaches the request. Whether the output of a narrator is accepted is test_narration_output.py's.
"""

import json
import re

import pytest
from narration_fakes import asks
from narration_reports import report
from test_narration_facts import rename_arms, with_canaries

from referee.narration.facts import check_report_consistency, fact_list
from referee.narration.output import SCHEMA, offered_ids
from referee.narration.render import CATEGORIES, Understanding
from referee.narration.sheet import (
    SYSTEM,
    EgressError,
    build_request,
    check_egress,
    tokens,
    vocabulary,
)

SUMMARY = Understanding("answer", "summary")
EXPLAIN = Understanding("answer", "explain_finding", target="RES-001")


def test_the_sheet_is_the_task_the_aliases_and_what_the_intent_offers_for_each_finding(
    raw_spec: dict,
) -> None:
    for ask in asks(raw_spec):
        request = build_request(ask.report, ask.facts, ask.understanding)
        sheet, offer = (
            json.loads(request.user),
            offered_ids(ask.report, ask.facts, ask.understanding),
        )

        assert set(sheet) == {"task", "arms", "findings"}, (
            ask.name
        )  # no verdict, effect or population
        assert sheet["task"] == {"intent": ask.intent, "target": ask.understanding.target}
        assert [arm["alias"] for arm in sheet["arms"]] == list(ask.facts.aliases.values())
        assert [arm["role"] for arm in sheet["arms"]] == ["control"] + ["variant"] * (
            len(sheet["arms"]) - 1
        )
        assert [item["rule_id"] for item in sheet["findings"]] == ask.scope
        for item in sheet["findings"]:
            rule_id = item["rule_id"]
            assert set(item) == {"rule_id", "severity", "title", "sentences", "facts"}
            assert item["severity"] == ask.severity[rule_id]
            assert [s["id"] for s in item["sentences"]] == list(offer[rule_id].sentences)
            # the facts it offers, in the order of the allowlist
            assert [f["id"] for f in item["facts"]] == [
                fact_id for fact_id in ask.fact_ids[rule_id] if fact_id in offer[rule_id].facts
            ]
        assert tokens(sheet) <= vocabulary(ask.facts), ask.name  # nothing but what code writes
        assert request.user == json.dumps(sheet, sort_keys=True, separators=(",", ":"))
        assert request.system == SYSTEM and request.max_tokens == 4096


def test_the_instructions_name_the_schema_of_the_output_check_and_nothing_the_router_saw() -> None:
    # twice: in words and in the shape; a prompt that names another would have every output refused
    assert re.findall(r"referee-narration-output/\w+", SYSTEM) == [SCHEMA, SCHEMA]
    assert not [category for category in CATEGORIES if category in SYSTEM]


def test_a_sheet_holds_the_sentences_and_facts_of_a_finding_as_the_report_gives_them(
    raw_spec: dict,
) -> None:
    golden = report("golden", raw_spec)
    facts = fact_list(golden)

    summary = json.loads(build_request(golden, facts, SUMMARY).user)
    explained = json.loads(build_request(golden, facts, EXPLAIN).user)

    assert [
        (f["rule_id"], f["severity"], len(f["sentences"]), f["facts"]) for f in summary["findings"]
    ] == [
        ("RES-001", "blocker", 3, []),
        ("RES-002", "blocker", 3, []),
        ("RES-007", "warning", 4, []),
        ("RES-008", "warning", 7, []),
        ("RES-012", "warning", 4, []),
        ("RES-013", "warning", 2, []),
    ]  # a summary offers the reasons, not the facts
    assert summary["findings"][0]["sentences"][0] == {
        "id": "RES-001.why.1",
        "text": "Random assignment gives arms of the registered sizes, up to chance.",
    }
    (finding,) = explained["findings"]
    assert finding["title"] == (
        "Sample ratio mismatch: the arms are not the size the allocation promised"
    )
    assert len(finding["sentences"]) == 7 and len(finding["facts"]) == 14
    assert finding["facts"][:2] == [
        {
            "id": "RES-001.alpha",
            "label": "significance level of the sample ratio test",
            "value": 0.001,
        },
        {"id": "RES-001.allocation.A1", "label": "registered allocation (A1)", "value": 1 / 3},
    ]


@pytest.mark.parametrize(
    ("in_report", "in_sheet", "words", "leaks"),
    [
        ({"x": ["zebra"]}, {"y": ["zebra"]}, set(), True),
        ({"x": "Zebra"}, {"y": "zEBRA"}, set(), True),  # case is folded on both sides
        ({"x": "zebra"}, {"y": "ZEBRA"}, set(), True),
        ({"x": "Stra\u00dfe"}, {"y": "STRASSE"}, set(), True),  # folded, not only lower-cased
        ({"zebra": 1}, {"y": "zebra"}, set(), True),  # a key of the report
        ({"x": "zebra"}, {"zebra": 1}, set(), True),  # a key of the sheet
        ({"x": "a zebra-b"}, {"y": "the zebra"}, set(), True),  # a token, not a string
        ({"a": [{"b": ["zebra"]}]}, {"c": [["zebra"]]}, set(), True),  # at any depth
        ({"x": "arm_2"}, {"y": "arm_2"}, set(), True),  # the underscore and digits are in a token
        ({"x": "arm_2"}, {"y": "arm"}, set(), False),
        ({"x": "zebra"}, {"y": "zebra"}, {"zebra"}, False),  # what code writes is no leak
        ({"x": "zebra"}, {"y": "horse"}, set(), False),  # not in the sheet
        ({"x": "zebra", "z": 12345}, {"y": ["horse", 12345, True, None]}, set(), False),
    ],
)
def test_the_egress_assertion_refuses_a_token_of_the_report_in_the_sheet_that_code_did_not_write(
    in_report: object, in_sheet: object, words: set[str], leaks: bool
) -> None:
    if leaks:
        with pytest.raises(EgressError) as caught:
            check_egress(in_report, in_sheet, words)
        assert "zebra" not in str(caught.value).casefold() and "arm_2" not in str(caught.value)
    else:
        check_egress(in_report, in_sheet, words)


@pytest.mark.parametrize(
    "arms",
    [
        ("a", "A", "1"),
        ("1", "control", "a"),
        ("alpha", "p_value", "estimate"),
        ("tests", "settings", "notes"),
        ("A3", "A1", "A2"),
    ],
)
def test_arms_named_like_the_words_of_the_sheet_do_not_trip_the_assertion_or_change_the_sheet(
    raw_spec: dict, arms: tuple[str, ...]
) -> None:
    golden = report("golden", raw_spec)
    renamed = rename_arms(
        golden, dict(zip(("control", "variant_b", "variant_c"), arms, strict=True))
    )
    check_report_consistency(renamed)

    for understanding in (SUMMARY, EXPLAIN):
        made = build_request(renamed, fact_list(renamed), understanding)
        assert made == build_request(golden, fact_list(golden), understanding)


def test_no_free_text_of_the_report_reaches_the_request(raw_spec: dict) -> None:
    """The arm names (keys and values), the ids of the spec and the experiment, the metric names,
    the error texts, the notes and the summary lines of the committed report are replaced with
    canaries, the structure kept. The request is the golden's, and no canary is in it. A mutant
    that copies an arm's name into the sheet (a label, an alias) is caught by the assertion before
    this check, and by this check when the assertion is off."""
    golden = report("golden", raw_spec)
    canaried, canaries = with_canaries(golden)
    check_report_consistency(canaried)

    made = [
        (
            build_request(canaried, fact_list(canaried), ask.understanding),
            build_request(ask.report, ask.facts, ask.understanding),
        )
        for ask in asks(raw_spec)
        if ask.name.startswith("golden/")
    ]

    text = json.dumps(canaried)
    assert len(canaries) > 30 and all(canary in text for canary in canaries)  # not vacuous
    assert len(made) == 9 and all(request == plain for request, plain in made)
    explained = [json.loads(request.user)["findings"] for request, _ in made[3:]]  # six findings
    assert sum(len(item["facts"]) for items in explained for item in items) == 77
    assert [arm["alias"] for arm in json.loads(made[0][0].user)["arms"]] == ["A1", "A2", "A3"]
    assert not any(
        canary in request.system + request.user for request, _ in made for canary in canaries
    )
