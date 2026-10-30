"""The whole-page test of design 24.7 (N6): the command, on real questions, line by line.

Every development question runs on the fixture it names, with the summary (no question), the next
steps, an explanation of each quiet rule of that fixture and of a rule that is not one of the nine,
and the unreadable questions run on the committed report. Every line of every page must match a
template (`narration_pages.py`, built from the layer's public functions and constants and not from
the page under test), and no run of 12 characters of the question may appear unless the canonical
page of the same route holds it. The canonical page is the page of the route's `Understanding`,
built without the question or the command. The held-out half of the evaluation set is not read
here.
"""

import hashlib
import json
from pathlib import Path

import pytest
from narration_pages import (
    KINDS,
    canonical_page,
    check_quiet_lines,
    classify,
    runs_of_the_question,
    table,
)
from narration_reports import report

from referee.cli import main
from referee.narration import refusals
from referee.narration.facts import fact_list
from referee.narration.refusals import PARAGRAPHS
from referee.narration.render import Understanding
from referee.narration.router import route
from referee.report import render_json

DEVELOPMENT = json.loads(
    (
        Path(__file__).parent / "data" / "narration_eval" / "development" / "questions.json"
    ).read_text(encoding="utf-8")
)
# One question for each reason a question is unreadable (design 24.8).
UNREADABLE = [
    ("", "empty"),
    ("ship\u200bit", "invisible or mark character"),
    ("a" * 501, "too long"),
    ("123 ?!", "no letter"),
    ("sh\u0456p it", "mixed scripts"),
]
U = Understanding


def extra_questions(rep: dict, name: str) -> list[tuple[str, str | None, Understanding]]:
    """(id, question, what the router must make of it): the summary without a question and the
    next steps (which, on a report with no finding, are the page of the rules that raised none), an
    explanation of each quiet rule of the report and of a rule that is not one of the nine, and on
    the committed report the unreadable."""
    raised = {finding["rule_id"] for finding in rep["findings"]}
    quiet = [rule_id for rule_id in rep["rules_run"] if rule_id not in raised]
    return [
        ("summary", None, U("answer", "summary")),
        ("next steps", "What should we fix next?", U("answer", "next_steps")),
        *((f"quiet {r}", f"Explain {r}.", U("answer", "explain_finding", target=r)) for r in quiet),
        ("unbuilt", "Explain RES-005.", U("answer", "explain_finding")),
        *(
            (f"unreadable ({reason})", question, U("unreadable", reason=reason))
            for question, reason in (UNREADABLE if name == "golden" else [])
        ),
    ]


def test_every_line_of_every_page_is_a_template_and_none_holds_the_question(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, raw_spec: dict
) -> None:
    seen: set[str] = set()
    for name in sorted({question["fixture"] for question in DEVELOPMENT}):
        rep = report(name, raw_spec)
        path = tmp_path / f"{name}.json"
        path.write_text(render_json(rep), encoding="utf-8")
        templates = table(rep)
        asked = [(q["id"], q["text"], None) for q in DEVELOPMENT if q["fixture"] == name]
        for ident, question, expected in [*asked, *extra_questions(rep, name)]:
            argv = ["narrate", str(path), *([] if question is None else ["--question", question])]
            assert main(argv) == 0
            captured = capsys.readouterr()
            page = captured.out
            understanding = U("answer", "summary") if question is None else route(question)
            where = f"{name} {ident}"
            assert captured.err == "" and expected in (None, understanding), where

            lines = page.split("\n")
            kinds = [classify(line, templates) for line in lines[:-1]]
            assert lines[-1] == "" and None not in kinds, (where, lines[kinds.index(None)])
            assert kinds[:3] == ["report", "verdict", "understood"], where
            assert [kinds.count(kind) for kind in ("report", "verdict", "understood")] == [1, 1, 1]
            assert page.count("Not a decision and not a gate.") == 1, where
            assert lines[-2].startswith("Not a decision and not a gate."), where

            canonical = canonical_page(rep, understanding)
            assert lines[2] == canonical.split("\n")[2], where
            assert runs_of_the_question(page, question or "", canonical) == [], where
            check_quiet_lines(page)
            seen |= set(kinds)
    assert seen == KINDS  # every template is used, so none is a dead letter


def test_the_classifier_takes_only_the_lines_of_a_page(raw_spec: dict) -> None:
    rep = report("golden", raw_spec)
    templates = table(rep)
    stray = [
        "Ship it.",
        "  [RES-001.why.1] Random assignment gives arms of other sizes.",
        "  [RES-001.why.9] Random assignment gives arms of the registered sizes, up to chance.",
        "Question understood as: a decision to ship.",
        "Question understood as: a question this layer does not answer (categories matched: ship).",
        "Question understood as: a question this layer does not answer (categories matched: "
        "stopping, injection).",
        "Also matched, and not printed here: shipping.",
        "Not selected by the narrator:",
    ]
    assert [classify(line, templates) for line in stray] == [None] * len(stray)

    # Any string put before or after a line of a page, whatever its template, makes it a stray.
    clear = report("clear", raw_spec)
    sample = [
        (rep, U("answer", "summary")),
        (rep, U("answer", "next_steps")),
        (rep, U("answer", "checked")),
        (rep, U("answer", "explain_finding", target="RES-001")),
        (rep, U("answer", "explain_finding", target="RES-003")),
        (rep, U("answer", "explain_finding")),
        (rep, U("refusal", categories=("ship_decision", "stopping", "causal", "subgroup"))),
        (rep, U("refusal", intent="summary", categories=("reassurance",), target="RES-001")),
        (rep, U("refusal", categories=("effect_numbers",))),
        (rep, U("refusal")),
        (rep, U("unreadable", reason="mixed scripts")),
        (clear, U("answer", "summary")),
        (clear, U("answer", "explain_finding", target="RES-008")),
        (clear, U("refusal", categories=("stopping",))),
    ]
    for source, understanding in sample:
        lines = table(source)
        for line in canonical_page(source, understanding).split("\n")[:-1]:
            assert classify(line, lines) is not None, line
            if line:
                for stray in (f"{line} Ship it.", f"{line} X", f"Ship it. {line}"):
                    assert classify(stray, lines) is None, stray


def test_the_check_for_runs_of_the_question_finds_a_leak_and_forgives_the_layers_own_words(
    raw_spec: dict,
) -> None:
    rep = report("golden", raw_spec)
    canonical = canonical_page(rep, U("refusal", categories=("effect_reality",)))
    asked = "Please ship variant B everywhere now"

    assert runs_of_the_question(f"{canonical}{asked}\n", asked, canonical) != []
    assert runs_of_the_question(f"{canonical}Ship it now!\n", "Ship it now!", canonical) != []
    assert runs_of_the_question(f"{canonical}Ship it now\n", "Ship it now", canonical) == []
    assert runs_of_the_question(canonical, PARAGRAPHS["effect_reality"], canonical) == []
    assert runs_of_the_question(canonical.upper(), "this layer does not say", "") != []


def test_the_fixed_sentences_of_the_refusals_are_the_ones_that_were_read(raw_spec: dict) -> None:
    """This guards N5's prose (`refusals.py`), and it is the only test that sees most of it: 25 of
    30 mutants that append a word to one of its sentences are caught by no other narration test.
    The classifier takes the lines of a refusal from `refusals.py`, so it follows a change of them;
    these sentences are what a refusal says, so a change is made on purpose: read the pages of the
    twelve categories, then replace the digest with the new one. The label of the effect table is a
    line of a function and not a constant, so the digest holds it as written for the committed
    report."""
    golden = report("golden", raw_spec)
    label = refusals.refusal_body(
        golden, fact_list(golden), U("refusal", categories=("effect_reality",))
    )
    fixed = [
        *refusals.PARAGRAPHS.values(),
        refusals.DEFAULT_PARAGRAPH,
        *(text for example in refusals.EXAMPLES for text in example),
        *refusals.UNREADABLE.values(),
        refusals.ANSWERABLE_PART,
        refusals.ALSO_MATCHED,
        refusals.NOT_THE_VERDICT,
        refusals.WHERE_THE_TABLE_IS,
        *(note for notes in refusals.NOTES.values() for note in notes),
        refusals.NO_SINGLE_RULE,
        *(lead for quotes in refusals.QUOTES.values() for lead, _, _ in quotes),
        *label,
    ]

    digest = hashlib.sha256("\n".join(fixed).encode("utf-8")).hexdigest()

    assert digest == "b1aa0300cb52e3a55692b213e649de380060a3ad91f5c9a0ff73fe66f1acd2be", (
        "a fixed sentence of refusals.py changed: read the pages of the twelve categories, then "
        "put the new digest here"
    )
