"""The refusals of the narration layer (design section 24.8): the body of a page that answers no
question, as the list of lines `render.render_refusal` puts into the frame.

    body = refusal_body(report, facts, understanding)
    page = render_refusal(report, understanding, decision, body)

Every line is one of: a fixed paragraph written here, saying what the layer does not do; a
pointer into the report, which is a catalogue sentence whole (`sentence_line`), a quiet line
(`quiet_lines`), the facts of a finding (`fact_lines`) or a value of the report beside a label
written here; or a catalogue sentence quoted after a lead that makes it conditional, since the
rule may be quiet. No line holds a word of the question: the router's result names a category,
and everything below is a function of the report and of that.

A compound question gets the paragraph and the pointers of every category matched, in the order
given (the router's, which is the order of precedence), at most three; any beyond are named. A
refusal that keeps the intent of an answerable part says that no part of the question was
answered. `CLAIMS` names, for each category, the keys of the report that its claims rest on: a
test walks them on the committed report and another records the keys that the pointers read.
`QUOTES` holds each quoted sentence with the first five words of its text, so that a rule edit
that moves the numbering fails a test (24.15).
"""

from __future__ import annotations

from functools import reduce
from typing import Any

from referee.narration.facts import FactList, catalogue_sentences
from referee.narration.render import (
    Understanding,
    fact_lines,
    format_value,
    quiet_lines,
    sentence_line,
)
from referee.narration.router import MAX_CHARS
from referee.report import MEMO_HEADINGS

MAX_SHOWN = 3  # categories a refusal prints in full; any beyond are named

# The keys of the report that the claims rest on (dotted paths).
BLOCKING = "blocking_rule_ids"
FINDINGS = "findings"
RULES_RUN = "rules_run"
DAYS_OBSERVED = "population.observed_days"
DAYS_PLANNED = "population.planned_duration_days"
READABLE = "effect.readable"
UNREADABLE_BECAUSE = "effect.unreadable_because"
UNDERPOWERED = "effect.underpowered"
EFFECT_TABLE = "effect.arms"
ASSIGNED = "population.assigned"
ANALYSED = "population.analysed"
IGNORED = "population.ignored_before_start"

CLAIMS: dict[str, tuple[str, ...]] = {
    "ship_decision": (BLOCKING,),
    "stopping": (FINDINGS, RULES_RUN, DAYS_OBSERVED, DAYS_PLANNED),
    "reassurance": (FINDINGS, RULES_RUN),
    "effect_reality": (READABLE, UNREADABLE_BECAUSE, UNDERPOWERED),
    "effect_numbers": (EFFECT_TABLE, READABLE, UNREADABLE_BECAUSE, UNDERPOWERED),
    "subgroup": (ASSIGNED, RULES_RUN),
    "data_access": (ASSIGNED, ANALYSED, IGNORED),
}

PARAGRAPHS: dict[str, str] = {
    "injection": (
        "A question cannot change this page: the layer prints the engine's sentences and the "
        "report's values by fixed rules, and no instruction in a question changes what it prints "
        "or how."
    ),
    "ship_decision": (
        "This layer does not decide, recommend or approve shipping, keeping or dropping the "
        "change, and does not say which variant wins."
    ),
    "stopping": (
        "This layer does not say whether an experiment may be stopped, called or read at the "
        "point it has reached."
    ),
    "reassurance": (
        "This layer does not agree that the experiment, its data, a result, a finding or a "
        "number is fine, valid, trustworthy or safe to ignore."
    ),
    "effect_reality": "This layer does not say whether the effect is real.",
    "effect_numbers": (
        "This layer prints no number of the effect: no estimate, interval, p value or lift."
    ),
    "causal": "This layer does not say why an effect, a difference or a change happened.",
    "forecast": (
        "This layer does not predict what will happen beyond what the experiment observed."
    ),
    "subgroup": (
        "This layer does not report on a part of the players that the arms do not define, such "
        "as a country, a platform or a device."
    ),
    "other_analysis": (
        "This layer reads the saved report only: it runs no other test, metric, filter, window "
        "or correction, and recomputes nothing."
    ),
    "data_access": (
        "This layer prints no player, row or identifier from the data behind the report."
    ),
    "rewording": (
        "This layer prints the engine's sentences unchanged: it does not put them in other "
        "words, shorter, simpler or in another language, tone or format."
    ),
}

DEFAULT_PARAGRAPH = (
    "This question is none of the four kinds this layer answers about a saved results report. "
    "It answers these, one example of each:"
)
EXAMPLES: tuple[tuple[str, str], ...] = (
    ("a summary of the review", "What did the review find?"),
    ("one finding explained", "Why does RES-001 block the review?"),
    ("what to do next", "What should we fix before running this again?"),
    ("what was checked", "Which checks did this review run?"),
)
UNREADABLE: dict[str, str] = {
    "empty": "The question could not be read: it is empty.",
    "too long": f"The question could not be read: it is longer than {MAX_CHARS} characters.",
    "no letter": "The question could not be read: it holds no letter.",
    "invisible or mark character": (
        "The question could not be read: it holds a control, invisible or combining character, "
        "which can hide or split a word."
    ),
    "mixed scripts": (
        "The question could not be read: a word of it mixes Latin letters with Cyrillic, Greek, "
        "Armenian, Coptic or Cherokee ones, which can pass for Latin letters."
    ),
}
ANSWERABLE_PART = (
    "Part of the question may be one this layer answers (what the review found, one finding, "
    "what to do next, what was checked). This page answers none of the question: ask that part "
    "on its own."
)
ALSO_MATCHED = "Also matched, and not printed here:"
NOT_THE_VERDICT = (
    "A verdict of clear says only that the rules that ran found nothing that blocks or warns; "
    "it does not say the effect is real."
)
WHERE_THE_TABLE_IS = (
    f"The effect table is in the memo, under '{MEMO_HEADINGS[1]}', and in the report's JSON "
    "under 'effect'; this layer prints none of its numbers."
)
NOTES: dict[str, tuple[str, ...]] = {  # fixed pointers, with the keys of CLAIMS they rest on
    "subgroup": (
        "The report holds counts by arm and no breakdown by country, platform or device.",
    ),
    "other_analysis": ("The rules not built are listed under 'Not yet' in docs/rules.md.",),
    "data_access": (
        "The report holds the number of players assigned and analysed in each arm and, if a "
        "start was registered, the ids of the players assigned before it; this layer prints no "
        "player id.",
    ),
}

NO_SINGLE_RULE = "The question names no single rule of the nine results rules."
COHORT_LEAD = "The catalogue says of the cohort test, for when it flags a difference:"
RATES_LEAD = (
    "The catalogue says of the simulated error rates that RES-008 quotes, for when it raises "
    "a finding:"
)
# Each quotation: the lead, the sentence ID and the first five words of the sentence.
QUOTES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "causal": ((COHORT_LEAD, "RES-007.why.3", "The test says that the"),),
    "forecast": (
        (COHORT_LEAD, "RES-007.why.2", "If the effect differs between"),
        (RATES_LEAD, "RES-008.why.4", "These rates come from one"),
    ),
    "subgroup": (
        (
            "The report counts players by arm; its cohort test divides them by cohort of first "
            "exposure. The catalogue says of that test, for when it flags a difference:",
            "RES-007.why.2",
            "If the effect differs between",
        ),
    ),
}


def value(report: dict[str, Any], path: str) -> Any:
    """The value of the report at a dotted key path of `CLAIMS`."""
    return reduce(lambda node, key: node[key], path.split("."), report)


def _quotes(category: str) -> list[str]:
    lines: list[str] = []
    for lead, sentence_id, _ in QUOTES[category]:
        lines += [lead, sentence_line(sentence_id)]
    return lines


def _titles(rule_ids: list[str]) -> list[str]:
    return [sentence_line(f"{rule_id}.title") for rule_id in rule_ids]


def _effect_label(report: dict[str, Any]) -> str:
    label = (
        "can be read"
        if value(report, READABLE)
        else f"NOT TO BE READ, blocked by {', '.join(value(report, UNREADABLE_BECAUSE))}"
    )
    if value(report, UNDERPOWERED):
        label += "; UNDERPOWERED, an arm is smaller than registered"
    return f"The report labels its effect table: {label}."


def _stopping(report: dict[str, Any]) -> list[str]:
    raised = [finding["rule_id"] for finding in value(report, FINDINGS)]
    lengths = [rule_id for rule_id in ("RES-003", "RES-002") if rule_id in raised]
    lines = [
        f"Days observed: {format_value(value(report, DAYS_OBSERVED))}; days planned: "
        f"{format_value(value(report, DAYS_PLANNED))}."
    ]
    if lengths:
        lines += ["Raised in this report, about the length and size of the run:", *_titles(lengths)]
    return lines + quiet_lines([r for r in ("RES-003", "RES-002") if r not in lengths])


def _reassurance(report: dict[str, Any], facts: FactList, target: str | None) -> list[str]:
    raised = {finding["rule_id"]: finding["severity"] for finding in value(report, FINDINGS)}
    if target in raised:
        found = next(f for f in facts.findings if f.rule_id == target)
        return [
            f"The finding the question names, as the report holds it ({raised[target]}):",
            *_titles([target]),
            *fact_lines(found, facts.aliases),
            "These are the report's values for it; they are not agreement that it is fine.",
        ]
    if target is not None:
        return [
            "The question names a rule that raised nothing in this report:",
            *quiet_lines([target]),
        ]
    if raised:
        return [
            f"{NO_SINGLE_RULE} The findings of the report, with their severity:",
            *(
                f"  {rule_id} {severity}: {catalogue_sentences()[f'{rule_id}.title']}"
                for rule_id, severity in raised.items()
            ),
        ]
    return [NO_SINGLE_RULE, *quiet_lines(value(report, RULES_RUN))]


def _category(
    category: str, report: dict[str, Any], facts: FactList, target: str | None
) -> list[str]:
    """The paragraph and the pointers of one category."""
    lines = [PARAGRAPHS[category]]
    if category == "ship_decision":
        blocking = value(report, BLOCKING)
        if blocking:
            return [
                *lines,
                "The blocking rules of the report, by ID and title:",
                *_titles(blocking),
            ]
        return [*lines, "The report names no blocking rule; that is not a recommendation to ship."]
    if category == "stopping":
        return [*lines, *_stopping(report)]
    if category == "reassurance":
        return [*lines, *_reassurance(report, facts, target)]
    if category == "effect_reality":
        return [*lines, _effect_label(report), NOT_THE_VERDICT]
    if category == "effect_numbers":
        return [*lines, WHERE_THE_TABLE_IS, _effect_label(report)]
    if category in QUOTES:
        return [*lines, *_quotes(category), *NOTES.get(category, ())]
    return [*lines, *NOTES.get(category, ())]


def refusal_body(
    report: dict[str, Any], facts: FactList, understanding: Understanding
) -> list[str]:
    """The lines of the body of a refusal, a refusal by the default route or an unreadable
    question, for `render.render_refusal`. `report` must have passed the check and `facts` be
    its fact list. `ValueError` for an understanding that is an answer."""
    if understanding.kind == "unreadable":
        return [UNREADABLE[understanding.reason]]
    if understanding.kind != "refusal":
        raise ValueError("a refusal body is made from a refusal or an unreadable question")
    if not understanding.categories:
        return [
            DEFAULT_PARAGRAPH,
            *(f"  {what}: {example}" for what, example in EXAMPLES),
        ]
    shown, more = understanding.categories[:MAX_SHOWN], understanding.categories[MAX_SHOWN:]
    blocks = [_category(c, report, facts, understanding.target) for c in shown]
    if more:
        blocks.append([f"{ALSO_MATCHED} {', '.join(more)}."])
    if understanding.intent is not None:
        blocks.append([ANSWERABLE_PART])
    lines: list[str] = []
    for block in blocks:
        lines += ["", *block] if lines else block
    return lines
