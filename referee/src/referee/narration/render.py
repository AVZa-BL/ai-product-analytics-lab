"""The page (design section 24.7): one string from a report that passed the check and its facts.

Nothing here prints, runs a process or reads a file. Every line of a page is one of: a catalogue
sentence of a finding, whole, with its ID; a text written in this module; a report value beside a
label written here (an experiment id, the export time and an arm's name go through `for_line`);
or a line of the memo's Decision section as `render_results_memo` writes it.

The API, for the router (N5) and the command (N6, N7):

    decision = decision_block(report)       # once per report; raises ValueError (status 3)
    render_answer(report, facts, understanding, decision, selection=None)
    render_refusal(report, understanding, decision, body)      # a refusal or an unreadable question
    render_withheld(report, understanding, decision, violations)

`report` has passed `check_report_consistency` and `facts` is its `fact_list`. `body` is the list of
lines that N5 writes (the fixed paragraph and pointers; `quiet_lines` gives the line of a rule that
raised no finding, with its disclaimer). `violations` is a list of `(code, finding ID)` as N7a
reports them, the ID `-` where the report holds none; a code outside `VIOLATION_CODES` or an ID the
report does not hold raises `ValueError`, so that nothing of a narrator's output reaches the page.

`selection=None` is the fixed rule (everything the intent permits, nothing left); otherwise it is
the model path: `{finding ID: Chosen(sentences, facts)}` of IDs that passed the output check, and
the page prints what is not chosen under the second label. The narrator's order is never used:
sentences print in catalogue order, facts in allowlist order, findings in report order. A finding of
the report without an entry is not narrated and is listed by ID, severity and title; that only an
info finding may be left out is the output check's rule, not this module's. `checked` and the
explanation of a rule that raised no finding or is not one of the nine are code only (24.3):
`selection` does not change them, and the explanations print no `Chosen by` line.

A page is blocks of lines with one blank line between them: the report line, the verdict line, the
understood line and the `Chosen by` lines; the Decision block; the line that ends it; the body; the
footer. `format_value` is the one formatter of a fact's value.

N5 builds an `Understanding` from its route without changing this module:

    Understanding("answer", "summary")
    Understanding("answer", "explain_finding", target="RES-001")    # one of the nine
    Understanding("answer", "explain_finding")                      # names a rule that is not one
                                                                    # of the nine: no ID is kept
    Understanding("answer", "explain_finding", as_summary=True)     # no single target: a summary
    Understanding("refusal", categories=("ship_decision", "subgroup"))
    Understanding("unreadable", reason="mixed scripts")

`target`, `categories` and `reason` are printed as they are, so they must be what the router's
code wrote and never a word of the question; only `target` is checked here, against the nine IDs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from referee.display import for_line
from referee.narration.facts import (
    SUMMARISED_RULES,
    Fact,
    FactList,
    FindingFacts,
    catalogue_sentences,
)
from referee.report import MEMO_HEADINGS, render_results_memo
from referee.rules import RESULTS_RULES
from referee.rules.text import sig

KINDS = ("answer", "refusal", "unreadable")
INTENTS = ("summary", "explain_finding", "next_steps", "checked")
VIOLATION_CODES = ("schema", "scope", "duplicate", "fact", "source", "coverage")  # 24.6
RULE_IDS = tuple(rule.id for rule in RESULTS_RULES)

_SENTENCES = catalogue_sentences()
# The sentences an intent offers for a finding: reasons (why), advice (do), both for an explanation.
_OFFERED = {
    (rule_id, intent): tuple(
        sid for sid in _SENTENCES if sid.startswith(f"{rule_id}.") and sid.split(".")[1] in kinds
    )
    for rule_id in RULE_IDS
    for intent, kinds in (
        ("summary", ("why",)),
        ("next_steps", ("do",)),
        ("explain_finding", ("why", "do")),
    )
}

_DISCLAIMER = "This is not agreement with the question, and it does not say the effect is real."
_DISCLAIMER_OTHER = f"A rule reads only what the export holds. {_DISCLAIMER}"
_CHOSEN_FIXED = "Chosen by: a fixed rule in the code (everything this question permits)."
_CHOSEN_MODEL = (
    "Chosen by: the output of --llm-command (checked for scope, source and coverage, not "
    "relevance).",
    "For each finding narrated below, everything this question permits is printed; the narrator "
    "chose only what leads and which info findings are narrated; the labels are not a ranking of "
    "relevance.",
)
_OTHER_SECTIONS = "The memo's other sections are not part of this page."
_FOOTER = (
    "Not a decision and not a gate. This page advises only; its exit status does not mean the "
    "experiment is valid."
)
_NOT_A_RESULTS_RULE = (
    "That is not one of the nine results rules this layer reads (the rules not built are under "
    "'Not yet' in docs/rules.md)."
)
_NO_FINDING = "The rules that ran raised no finding."
_NOT_BUILT = "Rules not built are listed under 'Not yet' in docs/rules.md."


@dataclass(frozen=True)
class Understanding:
    """What the router made of a question, with no word of it (see the module docstring)."""

    kind: str  # one of KINDS
    intent: str | None = None  # one of INTENTS, for an answer
    target: str | None = None  # an explanation's rule, one of the nine results rules
    categories: tuple[str, ...] = ()  # a refusal's categories, in precedence order
    reason: str | None = None  # an unreadable question's reason
    as_summary: bool = False  # explain_finding without exactly one target, answered as a summary

    def __post_init__(self) -> None:
        if self.kind not in KINDS or (self.intent is not None and self.intent not in INTENTS):
            raise ValueError("the kind or the intent is not one the page knows")
        if self.target is not None and self.target not in RULE_IDS:
            raise ValueError("the target is not one of the nine results rules")


@dataclass(frozen=True)
class Chosen:
    """What the narrator chose to lead with for one finding: sentence IDs and fact IDs."""

    sentences: frozenset[str] = frozenset()
    facts: frozenset[str] = frozenset()


Selection = Mapping[str, Chosen]


def format_value(value: int | float | str) -> str:
    """A fact's value as the page prints it (24.4): an integer with thousands separators, a float
    to six significant digits with the zeros after the decimal point stripped, a boolean as yes or
    no, an enumeration word as it is. Never a percentage."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        text = sig(value, 6)
        return text.rstrip("0").rstrip(".") if "." in text and "e" not in text else text
    return value


def decision_block(report: dict[str, Any]) -> tuple[str, ...]:
    """The lines of the memo's Decision section: those of `render_results_memo(report)` between
    its first two headings. Raises `ValueError` unless each heading is exactly one whole line of
    the memo, the first before the second."""
    lines = render_results_memo(report).split("\n")
    first, second = (f"## {name}" for name in MEMO_HEADINGS[:2])
    if (
        lines.count(first) != 1
        or lines.count(second) != 1
        or lines.index(first) > lines.index(second)
    ):
        raise ValueError("the memo does not hold its first two headings as one whole line each")
    section = lines[lines.index(first) + 1 : lines.index(second)]
    return tuple("\n".join(section).strip("\n").split("\n"))


def quiet_lines(rule_ids: Sequence[str]) -> list[str]:
    """The line of each quiet rule, never bare for RES-004, RES-007 and RES-008, RES-008.why.6
    after a quiet RES-008, and then the disclaimer, which begins `A rule reads only what the
    export holds.` if any of the rules is another one. Nothing for no rule."""
    lines: list[str] = []
    for rule_id in rule_ids:
        if rule_id in SUMMARISED_RULES:
            lines.append(
                f"{rule_id} ran and raised no finding; how many comparisons or tests it made is "
                "in the report's summary_lines, and can be none."
            )
        else:
            lines.append(f"{rule_id} ran and raised no finding.")
        if rule_id == "RES-008":
            lines.append(_sentence_line("RES-008.why.6"))
    other = any(rule_id not in SUMMARISED_RULES for rule_id in rule_ids)
    return [*lines, _DISCLAIMER_OTHER if other else _DISCLAIMER] if lines else []


def _line(value: object) -> str:
    return for_line(str(value))


def _sentence_line(sentence_id: str) -> str:
    return f"  [{sentence_id}] {_SENTENCES[sentence_id]}"


def _fact_line(fact: Fact, arms: Mapping[str, str]) -> str:
    label = fact.label
    if fact.alias is not None:
        label = f"{label.removesuffix(f' ({fact.alias})')} ({_line(arms[fact.alias])})"
    return f"  {label}: {format_value(fact.value)}"


def _plural(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def _blocks(*blocks: Sequence[str]) -> list[str]:
    """The non-empty blocks of lines with a blank line between them."""
    lines: list[str] = []
    for block in blocks:
        if block:
            lines += ["", *block] if lines else block
    return lines


def _understood(understanding: Understanding) -> str:
    if understanding.kind == "refusal":
        categories = ", ".join(understanding.categories)
        what = f"a question this layer does not answer (categories matched: {categories})"
    elif understanding.kind == "unreadable":
        what = f"a question it could not read (reason: {understanding.reason})"
    elif understanding.intent != "explain_finding":
        what = {
            "summary": "a summary of the review",
            "next_steps": "what to do next",
            "checked": "what was checked",
        }[understanding.intent]
    elif understanding.target is not None:
        what = f"an explanation of {understanding.target}"
    elif understanding.as_summary:
        what = (
            "an explanation of a finding, but no single rule was named, so it is answered as a "
            "summary"
        )
    else:
        what = "an explanation of a rule that is not one of the nine results rules"
    return f"Question understood as: {what}."


def _page(
    report: dict[str, Any],
    understanding: Understanding,
    decision: Sequence[str],
    after_question: Sequence[str],
    body: Sequence[str],
) -> str:
    """The frame (24.7) around a body. The one string of the page, ending in a newline."""
    counts, taken = report["counts"], report["as_of"]["time"]
    head = [
        f"Report of experiment {_line(report['experiment_id'])}, export taken "
        f"{'not known' if taken is None else _line(taken)}.",
        f"Verdict: {report['verdict']}. Blocking rules: "
        f"{', '.join(report['blocking_rule_ids']) or 'none'}. Findings: "
        f"{_plural(counts['blocker'], 'blocker')}, {_plural(counts['warning'], 'warning')}, "
        f"{counts['info']} info.",
        _understood(understanding),
        *after_question,
    ]
    lines = _blocks(head, decision, [_OTHER_SECTIONS], body, [_FOOTER])
    return "\n".join(lines) + "\n"


def render_refusal(
    report: dict[str, Any],
    understanding: Understanding,
    decision: Sequence[str],
    body: Sequence[str],
) -> str:
    """The frame around `body`, the lines N5 writes for a refusal or an unreadable question."""
    return _page(report, understanding, decision, [], body)


def render_withheld(
    report: dict[str, Any],
    understanding: Understanding,
    decision: Sequence[str],
    violations: Sequence[tuple[str, str]],
) -> str:
    """The page of a withheld narration: the frame with the codes and finding IDs of the failed
    checks before the Decision block. A code or an ID that is not one of the report's raises
    `ValueError`, so that no string of the narrator's output can reach the page."""
    known = {finding["rule_id"] for finding in report["findings"]} | {"-"}
    if any(code not in VIOLATION_CODES or rule_id not in known for code, rule_id in violations):
        raise ValueError("a violation names a code or a finding that the page may not print")
    withheld = "Narration withheld: the output of --llm-command failed these checks: " + ", ".join(
        f"{code} {rule_id}" for code, rule_id in violations
    )
    return _page(report, understanding, decision, [withheld], [])


def _checked_lines(report: dict[str, Any]) -> list[str]:
    raised = {finding["rule_id"]: finding["severity"] for finding in report["findings"]}
    ran = [
        "Rules that ran, each with its title and, if it raised a finding, its severity:",
        *(
            f"  {rule_id} {raised.get(rule_id, 'quiet')}: {_SENTENCES[f'{rule_id}.title']}"
            for rule_id in report["rules_run"]
        ),
        _NOT_BUILT,
    ]
    return _blocks(ran, quiet_lines([r for r in report["rules_run"] if r not in raised]))


def _finding_block(
    finding: dict[str, Any],
    found: FindingFacts,
    intent: str,
    chosen: Chosen | None,
    arms: Mapping[str, str],
) -> list[str]:
    """One narrated finding: its heading, what leads, what is left. `chosen` None is the fixed
    rule, which leads with everything."""
    items = [
        (chosen is None or sid in chosen.sentences, _sentence_line(sid))
        for sid in _OFFERED[finding["rule_id"], intent]
    ]
    if intent == "explain_finding":
        items += [
            (chosen is None or fact.id in chosen.facts, _fact_line(fact, arms))
            for fact in found.facts
        ]
    lines = [
        f"{finding['rule_id']} {finding['severity']}: {finding['title']}",
        "Selected:",
        *(line for lead, line in items if lead),
    ]
    if not all(lead for lead, _ in items):
        lines += ["Not selected by the narrator:", *(line for lead, line in items if not lead)]
    if intent == "explain_finding":
        lines.append(
            f"Evidence values not shown on this page (the report holds them): "
            f"{found.dropped + found.withheld:,}."
        )
    return lines


def render_answer(
    report: dict[str, Any],
    facts: FactList,
    understanding: Understanding,
    decision: Sequence[str],
    selection: Selection | None = None,
) -> str:
    """The page of an answer. `selection` None is the fixed rule; otherwise the model path."""
    intent, target = understanding.intent, understanding.target
    if intent == "explain_finding" and understanding.as_summary:
        intent = "summary"
    raised = [finding["rule_id"] for finding in report["findings"]]
    if intent == "explain_finding" and target not in raised:
        # a quiet rule, or something that is not one of the nine: no narrator, no `Chosen by`
        body = [_NOT_A_RESULTS_RULE, _DISCLAIMER] if target is None else quiet_lines([target])
        return _page(report, understanding, decision, [], body)

    if intent == "checked":  # code only, whatever the narrator was asked
        return _page(report, understanding, decision, [_CHOSEN_FIXED], _checked_lines(report))
    chosen_by = [_CHOSEN_FIXED] if selection is None else list(_CHOSEN_MODEL)

    scope = [target] if intent == "explain_finding" else raised
    narrated = [rule_id for rule_id in scope if selection is None or rule_id in selection]
    arms = {alias: arm for arm, alias in facts.aliases.items()}
    blocks = [
        _finding_block(
            finding,
            found,
            intent,
            None if selection is None else selection[finding["rule_id"]],
            arms,
        )
        for finding, found in zip(report["findings"], facts.findings, strict=True)
        if finding["rule_id"] in narrated
    ]
    left = [finding for finding in report["findings"] if finding["rule_id"] not in narrated]
    if left:
        blocks.append(
            [
                "Findings not narrated:",
                *(f"  {f['rule_id']} {f['severity']} {f['title']}" for f in left),
            ]
        )
    if not report["findings"]:
        blocks.append([_NO_FINDING, _DISCLAIMER_OTHER])
    return _page(report, understanding, decision, chosen_by, _blocks(*blocks))
