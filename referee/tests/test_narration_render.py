"""The page of the narration layer (design sections 24.4 and 24.7).

The fixed lines are written out here as the design gives them and compared with what the module
writes; the rest of a page is rebuilt from its sources (the catalogue, the fact list, the report)
by the small builders below, which are the oracle of the property test.
"""

import copy
import random

import pytest
from narration_reports import NAMES, report

from referee.display import for_line
from referee.narration import render
from referee.narration.facts import catalogue_sentences, check_report_consistency, fact_list
from referee.narration.render import (
    Chosen,
    Understanding,
    decision_block,
    format_value,
    render_answer,
    render_refusal,
    render_withheld,
)
from referee.report import render_results_memo

SENTENCES = catalogue_sentences()
SUMMARISED = ("RES-004", "RES-007", "RES-008")
FOOTER = (
    "Not a decision and not a gate. This page advises only; its exit status does not mean the "
    "experiment is valid."
)
OTHER_SECTIONS = "The memo's other sections are not part of this page."
CHOSEN_FIXED = "Chosen by: a fixed rule in the code (everything this question permits)."
CHOSEN_MODEL = [
    "Chosen by: the output of --llm-command (checked for scope, source and coverage, not "
    "relevance).",
    "For each finding narrated below, everything this question permits is printed; the narrator "
    "chose only what leads and which info findings are narrated; the labels are not a ranking of "
    "relevance.",
]
DISCLAIMER = "This is not agreement with the question, and it does not say the effect is real."
DISCLAIMER_OTHER = "A rule reads only what the export holds. " + DISCLAIMER
NOT_A_RESULTS_RULE = (
    "That is not one of the nine results rules this layer reads (the rules not built are under "
    "'Not yet' in docs/rules.md)."
)
SUMMARISED_TAIL = (
    "; how many comparisons or tests it made is in the report's summary_lines, and can be none."
)
NO_FINDING = "The rules that ran raised no finding."
KINDS = {"summary": ("why",), "next_steps": ("do",), "explain_finding": ("why", "do")}
OF_KIND: dict[tuple[str, str], list[str]] = {}  # (rule ID, "why" or "do") -> sentence IDs
for sentence_id in SENTENCES:
    OF_KIND.setdefault(tuple(sentence_id.split(".")[:2]), []).append(sentence_id)


def blocks(*parts: list[str]) -> list[str]:
    lines: list[str] = []
    for part in parts:
        if part:
            lines += ["", *part] if lines else part
    return lines


def plural(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def memo_decision(rep: dict) -> list[str]:
    """The Decision section cut from the memo's text, not through the module's code."""
    memo = render_results_memo(rep)
    section = memo.split("\n## Decision\n", 1)[1].split("\n## Observed facts\n", 1)[0]
    return section.strip("\n").split("\n")


def frame(
    rep: dict,
    understood: str,
    middle: list[str],
    body: list[str],
    decision: list[str] | None = None,
) -> str:
    counts, taken = rep["counts"], rep["as_of"]["time"]
    blocking = ", ".join(rep["blocking_rule_ids"]) or "none"
    found = [plural(counts["blocker"], "blocker"), plural(counts["warning"], "warning")]
    head = [
        f"Report of experiment {for_line(rep['experiment_id'])}, export taken "
        f"{for_line(taken) if taken else 'not known'}.",
        f"Verdict: {rep['verdict']}. Blocking rules: {blocking}. "
        f"Findings: {', '.join(found)}, {counts['info']} info.",
        f"Question understood as: {understood}.",
        *middle,
    ]
    lines = blocks(head, decision or memo_decision(rep), [OTHER_SECTIONS], body, [FOOTER])
    return "\n".join(lines) + "\n"


def quiet(rule_ids: list[str]) -> list[str]:
    lines = []
    for rule in rule_ids:
        tail = SUMMARISED_TAIL if rule in SUMMARISED else "."
        lines.append(f"{rule} ran and raised no finding" + tail)
        if rule == "RES-008":
            lines.append(f"  [RES-008.why.6] {SENTENCES['RES-008.why.6']}")
    if lines:
        other = any(rule not in SUMMARISED for rule in rule_ids)
        lines.append(DISCLAIMER_OTHER if other else DISCLAIMER)
    return lines


def fact_line(fact, arms: dict[str, str]) -> str:
    label = fact.label
    if fact.alias:
        label = label.replace(f"({fact.alias})", f"({for_line(arms[fact.alias])})")
    return f"  {label}: {format_value(fact.value)}"


def answer_body(rep, found, intent, target, selection) -> list[str]:
    """The body of an answer, rebuilt: the findings in report order, each with its sentences of
    the catalogue in catalogue order and its facts in allowlist order, led or left."""
    arms = {alias: arm for arm, alias in found.aliases.items()}
    narrated, parts = [], []
    for finding, facts_of in zip(rep["findings"], found.findings, strict=True):
        rule = finding["rule_id"]
        if (intent == "explain_finding" and rule != target) or (
            selection is not None and rule not in selection
        ):
            continue
        narrated.append(rule)
        chosen = None if selection is None else selection[rule]
        items = [
            (chosen is None or sid in chosen.sentences, f"  [{sid}] {SENTENCES[sid]}")
            for kind in KINDS[intent]
            for sid in OF_KIND[rule, kind]
        ]
        if intent == "explain_finding":
            items += [
                (chosen is None or fact.id in chosen.facts, fact_line(fact, arms))
                for fact in facts_of.facts
            ]
        part = [f"{rule} {finding['severity']}: {finding['title']}", "Selected:"]
        part += [line for led, line in items if led]
        if not all(led for led, _ in items):
            part += ["Not selected by the narrator:"] + [line for led, line in items if not led]
        if intent == "explain_finding":
            shown = f"{facts_of.dropped + facts_of.withheld:,}"
            part.append(f"Evidence values not shown on this page (the report holds them): {shown}.")
        parts.append(part)
    left = [f for f in rep["findings"] if f["rule_id"] not in narrated]
    if left:
        parts.append(
            ["Findings not narrated:"]
            + [f"  {f['rule_id']} {f['severity']} {f['title']}" for f in left]
        )
    if not rep["findings"]:
        parts.append([NO_FINDING, DISCLAIMER_OTHER])
    return blocks(*parts)


def understood_of(intent: str, target: str | None) -> str:
    return {
        "summary": "a summary of the review",
        "next_steps": "what to do next",
        "explain_finding": f"an explanation of {target}",
    }[intent]


def checked_body(rep) -> list[str]:
    raised = {f["rule_id"]: f["severity"] for f in rep["findings"]}
    lines = [
        "Rules that ran, each with its title and, if it raised a finding, its severity:",
        *(
            f"  {rule} {raised.get(rule, 'quiet')}: {SENTENCES[rule + '.title']}"
            for rule in rep["rules_run"]
        ),
        "Rules not built are listed under 'Not yet' in docs/rules.md.",
    ]
    return blocks(lines, quiet([rule for rule in rep["rules_run"] if rule not in raised]))


def with_info(rep: dict) -> dict:
    """`rep` with its RES-008 finding demoted to info (no escalation) and the counts, the order
    of the findings and the evidence of the finding changed to match: it still passes the check."""
    rep = copy.deepcopy(rep)
    finding = next(f for f in rep["findings"] if f["rule_id"] == "RES-008")
    finding["evidence"]["summary"].update(largest_simulated_rate=0.04, floor_ranges=0)
    finding["severity"] = "info"
    rep["findings"].remove(finding)
    rep["findings"].append(finding)
    rep["counts"].update(warning=rep["counts"]["warning"] - 1, info=1)
    check_report_consistency(rep)
    return rep


# --- Numbers ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.05, "0.05"),
        (12, "12"),
        (12.0, "12"),
        (0.0, "0"),
        (100000, "100,000"),
        (100000.0, "100,000"),
        (10.0, "10"),
        (100.0, "100"),
        (1000.0, "1,000"),
        (1500.0, "1,500"),
        (2107.0, "2,107"),
        (1234567.0, "1,234,570"),
        (0.7215426614114665, "0.721543"),
        (1.5e20, "1.50000e+20"),
        (1e-7, "1.00000e-07"),
        (True, "yes"),
        (False, "no"),
        ("chi_square", "chi_square"),
    ],
)
def test_a_value_prints_as_the_design_says(value, text: str) -> None:
    assert format_value(value) == text


# --- The page, from its sources ---------------------------------------------------------------


def test_every_page_of_every_intent_is_its_sources_in_a_fixed_order(raw_spec: dict) -> None:
    reports = {name: report(name, raw_spec) for name in NAMES}
    reports["golden_with_info"] = with_info(reports["golden"])
    cases = []
    for rep in reports.values():
        found, decision = fact_list(rep), decision_block(rep)
        assert list(decision) == memo_decision(rep)
        raised = [f["rule_id"] for f in rep["findings"]]
        for intent, target in [("summary", None), ("next_steps", None), ("checked", None)] + [
            ("explain_finding", rule) for rule in raised
        ]:
            understanding = Understanding("answer", intent, target=target)
            args = (rep, found, understanding, decision)
            # the fixed rule leads with everything and leaves nothing
            body = (
                checked_body(rep)
                if intent == "checked"
                else answer_body(rep, found, intent, target, None)
            )
            understood = (
                "what was checked" if intent == "checked" else understood_of(intent, target)
            )
            page = frame(rep, understood, [CHOSEN_FIXED], body, decision)
            assert render_answer(*args) == page
            if intent == "checked":  # code only, whatever the narrator was asked
                assert render_answer(*args, {}) == page
            if intent != "checked" and raised:
                cases.append((rep, found, decision, understanding, intent, target))

    rng = random.Random(20261029)
    seen = set()
    counts = {
        "info narrated beside others": 0,
        "info left out": 0,
        "facts led": 0,
        "second label": 0,
    }
    for _ in range(20_000):
        rep, found, decision, understanding, intent, target = rng.choice(cases)
        selection = {}
        for finding, facts_of in zip(rep["findings"], found.findings, strict=True):
            rule = finding["rule_id"]
            if intent == "explain_finding" and rule != target:
                continue
            if finding["severity"] == "info" and rule != target and rng.random() < 0.5:
                counts["info left out"] += 1
                continue
            counts["info narrated beside others"] += (
                finding["severity"] == "info" and intent != "explain_finding"
            )
            groups = [OF_KIND[rule, kind] for kind in KINDS[intent]]
            led = {sid for group in groups for sid in group if rng.random() < 0.5}
            led |= {rng.choice(group) for group in groups if not led.intersection(group)}
            led_facts = (
                {fact.id for fact in facts_of.facts if rng.random() < 0.5}
                if intent == "explain_finding"
                else set()
            )
            selection[rule] = Chosen(frozenset(led), frozenset(led_facts))
            counts["facts led"] += len(led_facts)
        order = list(selection.items())
        rng.shuffle(order)  # the narrator's order, which the page must not use
        page = render_answer(rep, found, understanding, decision, dict(order))
        body = answer_body(rep, found, intent, target, selection)
        assert page == frame(rep, understood_of(intent, target), CHOSEN_MODEL, body, decision)
        counts["second label"] += "Not selected by the narrator:" in page
        seen.add((id(rep), intent, target))
    assert len(seen) == len(cases)
    assert all(counts.values()), counts


def test_the_count_of_evidence_values_not_shown_is_written_with_separators(raw_spec: dict) -> None:
    rep = report("golden", raw_spec)
    next(f for f in rep["findings"] if f["rule_id"] == "RES-001")["evidence"]["notes"] = [
        "x"
    ] * 1500
    page = render_answer(
        rep,
        fact_list(rep),
        Understanding("answer", "explain_finding", target="RES-001"),
        decision_block(rep),
    )

    assert "(the report holds them): 1,518." in page


# --- The frame --------------------------------------------------------------------------------


def test_the_report_line_and_the_verdict_line_are_the_reports_values(raw_spec: dict) -> None:
    golden = report("golden", raw_spec)
    assert render_answer(golden, fact_list(golden), Understanding("answer", "summary"), ()).split(
        "\n"
    )[:2] == [
        "Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.",
        "Verdict: invalid. Blocking rules: RES-001, RES-002. "
        "Findings: 2 blockers, 4 warnings, 0 info.",
    ]
    clear = report("clear", raw_spec)
    clear["as_of"]["time"] = None
    harm = report("harm_blocker", raw_spec)
    for rep, expected in (
        (clear, "Report of experiment e1, export taken not known."),
        (harm, "Report of experiment e1, export taken 2026-05-26T00:00:00Z."),
    ):
        assert render_refusal(rep, Understanding("unreadable", reason="x"), (), []).startswith(
            expected + "\n"
        )
    assert render_refusal(clear, Understanding("unreadable", reason="x"), (), []).split("\n")[
        1
    ] == ("Verdict: clear. Blocking rules: none. Findings: 0 blockers, 0 warnings, 0 info.")
    assert render_refusal(harm, Understanding("unreadable", reason="x"), (), []).split("\n")[1] == (
        "Verdict: invalid. Blocking rules: RES-004. Findings: 1 blocker, 0 warnings, 0 info."
    )


@pytest.mark.parametrize(
    ("understanding", "understood"),
    [
        (Understanding("answer", "summary"), "a summary of the review"),
        (Understanding("answer", "next_steps"), "what to do next"),
        (Understanding("answer", "checked"), "what was checked"),
        (Understanding("answer", "explain_finding", target="RES-001"), "an explanation of RES-001"),
        (
            Understanding("answer", "explain_finding", as_summary=True),
            "an explanation of a finding, but no single rule was named, so it is answered as a "
            "summary",
        ),
        (
            Understanding("answer", "explain_finding"),
            "an explanation of a rule that is not one of the nine results rules",
        ),
        (
            Understanding("refusal", categories=("ship_decision", "subgroup")),
            "a question this layer does not answer (categories matched: ship_decision, subgroup)",
        ),
        (
            Understanding("unreadable", reason="mixed scripts"),
            "a question it could not read (reason: mixed scripts)",
        ),
    ],
)
def test_the_understood_line_is_written_from_the_routers_result(
    raw_spec: dict, understanding: Understanding, understood: str
) -> None:
    rep = report("golden", raw_spec)
    if understanding.kind == "answer":
        page = render_answer(rep, fact_list(rep), understanding, ())
    else:
        page = render_refusal(rep, understanding, (), [])
    assert page.split("\n")[2] == f"Question understood as: {understood}."


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "answer", "intent": "explain_finding", "target": "ZZZ-123"},
        {"kind": "answer", "intent": "explain_finding", "target": "RES-005"},
        {"kind": "answer", "intent": "explain_finding", "target": "DES-001"},
        {"kind": "answer", "intent": "explain_finding", "target": "res-001"},
        {"kind": "answer", "intent": "explain_finding", "target": "RES-001 x"},
        {"kind": "answer", "intent": "shout"},
        {"kind": "advice"},
    ],
)
def test_an_understanding_with_a_target_outside_the_nine_or_an_unknown_kind_is_refused(
    bad: dict,
) -> None:
    with pytest.raises(ValueError, match="nine results rules|kind or the intent"):
        Understanding(**bad)


def test_a_fact_list_that_is_not_the_reports_cannot_drop_a_finding_from_the_page(
    raw_spec: dict,
) -> None:
    with pytest.raises(ValueError):
        render_answer(
            report("golden", raw_spec),
            fact_list(report("clear", raw_spec)),
            Understanding("answer", "summary"),
            (),
        )


@pytest.mark.parametrize("name", ["golden", "clear"])  # clear has no finding to summarise
def test_an_explanation_without_a_single_target_is_a_summary_that_says_so(
    raw_spec: dict, name: str
) -> None:
    rep = report(name, raw_spec)
    found, decision = fact_list(rep), decision_block(rep)
    summary = render_answer(rep, found, Understanding("answer", "summary"), decision).split("\n")
    explained = render_answer(
        rep, found, Understanding("answer", "explain_finding", as_summary=True), decision
    ).split("\n")

    assert explained[2].endswith("so it is answered as a summary.")
    assert explained[:2] + explained[3:] == summary[:2] + summary[3:]


def test_an_empty_selection_is_the_model_path_with_nothing_narrated(raw_spec: dict) -> None:
    rep = report("golden", raw_spec)
    found, decision = fact_list(rep), decision_block(rep)
    page = render_answer(rep, found, Understanding("answer", "summary"), decision, {})
    body = answer_body(rep, found, "summary", None, {})

    assert page == frame(rep, "a summary of the review", CHOSEN_MODEL, body, decision)
    assert body[0] == "Findings not narrated:"
    assert len(body) == 1 + len(rep["findings"])  # every finding, whatever its severity


def test_the_frame_has_one_shape_for_an_answer_a_refusal_an_unreadable_question_and_a_withheld_page(
    raw_spec: dict,
) -> None:
    rep = report("golden", raw_spec)
    found, decision = fact_list(rep), decision_block(rep)
    refusal = Understanding("refusal", categories=("stopping",))
    unreadable = Understanding("unreadable", reason="empty")
    withheld = render_withheld(
        rep,
        Understanding("answer", "summary"),
        decision,
        [("schema", "-"), ("scope", "RES-001")],
    )
    pages = {
        "answer": (
            render_answer(rep, found, Understanding("answer", "summary"), decision),
            "a summary of the review",
            [CHOSEN_FIXED],
            answer_body(rep, found, "summary", None, None),
        ),
        "refusal": (
            render_refusal(rep, refusal, decision, ["BODY", "two"]),
            "a question this layer does not answer (categories matched: stopping)",
            [],
            ["BODY", "two"],
        ),
        "unreadable": (
            render_refusal(rep, unreadable, decision, ["BODY"]),
            "a question it could not read (reason: empty)",
            [],
            ["BODY"],
        ),
        "withheld": (
            withheld,
            "a summary of the review",
            [
                "Narration withheld: the output of --llm-command failed these checks: "
                "schema -, scope RES-001"
            ],
            [],
        ),
    }
    for page, understood, middle, body in pages.values():
        assert page == frame(rep, understood, middle, body)


@pytest.mark.parametrize(
    ("violations", "valid"),
    [
        *[
            ([(code, "-")], True)
            for code in ("schema", "scope", "duplicate", "fact", "source", "coverage")
        ],
        ([("schema", "RES-002")], True),
        ([("fact", "RES-003")], False),  # not a finding of the report
        ([("fact", "hostile\nid")], False),
        ([("fact", "RES-001\x1b[2J")], False),  # an ID the report holds, with something after it
        ([("nothing", "RES-001")], False),
        ([("retry", "-")], False),  # a seventh code
        ([("schema", "-"), ("nothing", "RES-001")], False),  # one good, one bad
    ],
)
def test_a_withheld_page_prints_codes_and_finding_ids_of_the_report_only(
    raw_spec: dict, violations: list, valid: bool
) -> None:
    rep = report("golden", raw_spec)
    understanding = Understanding("answer", "summary")
    if valid:
        page = render_withheld(rep, understanding, (), violations)
        line = "Narration withheld: the output of --llm-command failed these checks: "
        assert line + f"{violations[0][0]} {violations[0][1]}\n" in page
    else:
        with pytest.raises(ValueError, match="may not print"):
            render_withheld(rep, understanding, (), violations)


# --- The Decision block -----------------------------------------------------------------------

MEMO = "# Decision memo: x\n\n## Decision\n\nbody\n\n## Observed facts\n\nmore\n"


@pytest.mark.parametrize(
    ("memo", "block"),
    [
        (MEMO, ("body",)),
        ("## Decision\nbody\n## Observed facts\nmore\n", ("body",)),
        (MEMO.replace("## Decision\n", ""), None),
        (MEMO.replace("## Observed facts\n", ""), None),
        (MEMO + "\n## Decision\n", None),
        (MEMO + "\n## Observed facts\n", None),
        (MEMO.replace("## Decision\n", "## Decision (draft)\n"), None),
        (MEMO.replace("## Observed facts\n", "text ## Observed facts\n"), None),
        ("# x\n\n## Observed facts\n\nmore\n\n## Decision\n\nbody\n", None),
    ],
)
def test_a_memo_whose_headings_are_not_one_whole_line_each_in_order_ends_in_an_exception(
    monkeypatch: pytest.MonkeyPatch, memo: str, block: tuple | None
) -> None:
    monkeypatch.setattr(render, "render_results_memo", lambda _report: memo)
    if block is None:
        with pytest.raises(ValueError, match="first two headings"):
            decision_block({})
    else:
        assert decision_block({}) == block


# --- Report values that are text someone chose ------------------------------------------------

HOSTILE = ["## Observed facts", "`code` `` ```", "a\nb", "esc\x1b[31mape", "rlo‮txt"]


def renamed(node, names: dict):
    if isinstance(node, dict):
        return {names.get(key, key): renamed(item, names) for key, item in node.items()}
    if isinstance(node, list):
        return [renamed(item, names) for item in node]
    return names.get(node, node) if isinstance(node, str) else node


@pytest.mark.parametrize("name", HOSTILE)
def test_an_arm_or_an_experiment_named_to_look_like_a_line_prints_as_for_line_writes_it(
    raw_spec: dict, name: str
) -> None:
    rep = renamed(report("golden", raw_spec), {"variant_b": name})
    rep["experiment_id"] = rep["as_of"]["time"] = name
    check_report_consistency(rep)
    found, decision = fact_list(rep), decision_block(rep)
    assert found.aliases[name] == "A2"
    assert list(decision) == memo_decision(rep)  # the memo's own output, which has written them

    for target in ("RES-002", "RES-013"):  # both print facts of an arm
        page = render_answer(
            rep, found, Understanding("answer", "explain_finding", target=target), decision
        )
        body = answer_body(rep, found, "explain_finding", target, None)
        assert page == frame(rep, f"an explanation of {target}", [CHOSEN_FIXED], body, decision)
        assert f"({for_line(name)})" in page
        assert "## Observed facts" not in page.split("\n")
        assert not any("\x1b" in line or "\u202e" in line for line in page.split("\n"))


# --- Quiet rules, rules that are not findings, and the checked page ---------------------------


def quiet_discipline(page: str) -> int:
    """Every line that says a rule raised no finding is in a run of such lines (and RES-008's
    quotation) that ends in the disclaimer, which begins `A rule reads only what the export
    holds.` unless every rule of the run is RES-004, RES-007 or RES-008, which are never bare.
    Returns the number of quiet lines."""
    lines, found, at = page.split("\n"), 0, 0
    while at < len(lines):
        if "raised no finding" not in lines[at]:
            at += 1
            continue
        rules = []
        while "raised no finding" in lines[at] or lines[at].startswith("  [RES-008.why.6]"):
            if "raised no finding" in lines[at]:
                rule = lines[at].split()[0]
                rules.append(rule)
                if rule in SUMMARISED:
                    assert lines[at].endswith(SUMMARISED_TAIL), lines[at]
                if rule == "RES-008":
                    assert lines[at + 1].startswith("  [RES-008.why.6] A quiet RES-008 is not")
            at += 1
        assert lines[at] == (DISCLAIMER if set(rules) <= set(SUMMARISED) else DISCLAIMER_OTHER)
        found += len(rules)
    return found


def test_a_quiet_rule_is_never_bare_and_never_without_the_disclaimer(raw_spec: dict) -> None:
    quiet_seen = set()
    for name in NAMES:
        rep = report(name, raw_spec)
        found, decision = fact_list(rep), decision_block(rep)
        quiet_rules = [
            r for r in rep["rules_run"] if r not in {f["rule_id"] for f in rep["findings"]}
        ]
        for rule in quiet_rules:
            understanding = Understanding("answer", "explain_finding", target=rule)
            page = render_answer(rep, found, understanding, decision)
            assert page == frame(rep, f"an explanation of {rule}", [], quiet([rule]), decision)
            assert render_answer(rep, found, understanding, decision, {}) == page  # no narrator
            assert quiet_discipline(page) == 1
            quiet_seen.add(rule)
        checked = render_answer(rep, found, Understanding("answer", "checked"), decision)
        body = checked_body(rep)
        assert checked == frame(rep, "what was checked", [CHOSEN_FIXED], body, decision)
        assert quiet_discipline(checked) == len(quiet_rules)
    assert set(SUMMARISED) <= quiet_seen


def test_a_target_that_is_not_a_finding_gets_one_code_written_line_and_the_disclaimer(
    raw_spec: dict,
) -> None:
    rep = report("golden", raw_spec)
    page = render_answer(
        rep, fact_list(rep), Understanding("answer", "explain_finding"), decision_block(rep)
    )
    assert page == frame(
        rep,
        "an explanation of a rule that is not one of the nine results rules",
        [],
        [NOT_A_RESULTS_RULE, DISCLAIMER],
    )
