"""What a page of the narration layer may hold, line by line (design 24.7), for the command's tests.

`table(rep)` lists every fixed line a page of the report `rep` can hold, each with the name of its
template; `classify(line, table)` names the template of a line, or is None for a line that is none
of them. The frame lines, the headings and the labels are written out here as the design gives
them; the sentences of the catalogue, the Decision block, the facts, the quiet lines and the lines
of a refusal are taken from the public functions and constants of `render.py`, `refusals.py` and
`facts.py`, never from the page under test. A page of the fixed rule has no `Not selected by the
narrator` line and no model-path `Chosen by` line; the model path's lines and the withheld page's
line (design 24.7) are written out here as the design gives them, `render.py` keeping them private.
"""

import re

from referee.display import for_line
from referee.narration.facts import catalogue_sentences, fact_list
from referee.narration.refusals import ALSO_MATCHED, refusal_body
from referee.narration.render import (
    CATEGORIES,
    RULE_IDS,
    UNREADABLE_REASONS,
    VIOLATION_CODES,
    Selection,
    Understanding,
    decision_block,
    fact_lines,
    quiet_lines,
    render_answer,
    render_refusal,
)

SENTENCES = catalogue_sentences()
SENTENCE_LINE = re.compile(r"  \[([^\]]+)\] (.*)")
UNDERSTOOD = re.compile(r"Question understood as: (.*)\.")
COMPOUND = re.compile(r"a question this layer does not answer \(categories matched: (.+)\)")
ALSO = re.compile(re.escape(ALSO_MATCHED) + r" (.+)\.")
WITHHELD = re.compile(r"Narration withheld: the output of --llm-command failed these checks: (.+)")
FOOTER = (
    "Not a decision and not a gate. This page advises only; its exit status does not mean the "
    "experiment is valid."
)
CHOSEN_MODEL = (
    "Chosen by: the output of --llm-command (checked for scope, source and coverage, not "
    "relevance).",
    "For each finding narrated below, everything this question permits is printed; the narrator "
    "chose only what leads and which info findings are narrated; the labels are not a ranking of "
    "relevance.",
)
DISCLAIMER = "This is not agreement with the question, and it does not say the effect is real."
SUMMARISED_TAIL = (
    "; how many comparisons or tests it made is in the report's summary_lines, and can be none."
)
UNDERSTOOD_FIXED = {
    "a question this layer does not answer",
    "a summary of the review",
    "what to do next",
    "what was checked",
    "an explanation of a finding, but no single rule was named, so it is answered as a summary",
    "an explanation of a rule that is not one of the nine results rules",
    *(f"an explanation of {rule_id}" for rule_id in RULE_IDS),
    *(f"a question it could not read (reason: {reason})" for reason in UNREADABLE_REASONS),
}
KINDS = {
    "blank",
    "catalogue",
    "chosen",
    "chosen_model",
    "decision",
    "disclaimer",
    "fact",
    "frame",
    "heading",
    "label",
    "listing",
    "not_selected",
    "quiet",
    "refusal",
    "report",
    "understood",
    "verdict",
    "withheld",
}


def canonical_page(
    rep: dict, understanding: Understanding, selection: Selection | None = None
) -> str:
    """The page for `understanding` as the layer's functions build it: no question, no command;
    `selection` None is the fixed rule."""
    facts, decision = fact_list(rep), decision_block(rep)
    if understanding.kind == "answer":
        return render_answer(rep, facts, understanding, decision, selection)
    body = refusal_body(rep, facts, understanding)
    return render_refusal(rep, understanding, decision, body)


def table(rep: dict) -> dict[str, str]:
    """Every fixed line a page of `rep` can hold, with the name of its template."""
    lines: dict[str, str] = {}

    def add(kind: str, *new: str) -> None:
        for line in new:
            if line:
                lines.setdefault(line, kind)

    def title(rule_id: str) -> str:
        return SENTENCES[f"{rule_id}.title"]

    def plural(number: int, word: str) -> str:
        return f"{number} {word}" if number == 1 else f"{number} {word}s"

    facts, counts, taken = fact_list(rep), rep["counts"], rep["as_of"]["time"]
    raised = {finding["rule_id"]: finding["severity"] for finding in rep["findings"]}
    blocking = ", ".join(rep["blocking_rule_ids"]) or "none"
    add(
        "report",
        f"Report of experiment {for_line(rep['experiment_id'])}, export taken "
        f"{'not known' if taken is None else for_line(taken)}.",
    )
    add(
        "verdict",
        f"Verdict: {rep['verdict']}. Blocking rules: {blocking}. Findings: "
        f"{plural(counts['blocker'], 'blocker')}, {plural(counts['warning'], 'warning')}, "
        f"{counts['info']} info.",
    )
    add("chosen", "Chosen by: a fixed rule in the code (everything this question permits).")
    add("chosen_model", *CHOSEN_MODEL)
    add("not_selected", "Not selected by the narrator:")
    add("frame", "The memo's other sections are not part of this page.", FOOTER)
    add("decision", *decision_block(rep))
    add(
        "heading",
        *(f"{rule_id} {severity}: {title(rule_id)}" for rule_id, severity in raised.items()),
    )
    add(
        "listing",
        *(f"  {rule_id} {severity} {title(rule_id)}" for rule_id, severity in raised.items()),
    )
    add(
        "listing",
        *(f"  {rule_id} {severity}: {title(rule_id)}" for rule_id, severity in raised.items()),
    )
    add(
        "listing",
        *(
            f"  {rule_id}{' ' + raised[rule_id] if rule_id in raised else ''}: {title(rule_id)}"
            for rule_id in rep["rules_run"]
        ),
    )
    add(
        "label",
        "Selected:",
        "Findings not narrated:",
        "Rules that ran, each with its title and, if it raised a finding, its severity:",
        "Rules not built are listed under 'Not yet' in docs/rules.md.",
        "The rules that ran raised no finding.",
        "That is not one of the nine results rules this layer reads (the rules not built are "
        "under 'Not yet' in docs/rules.md).",
        *(
            f"Evidence values not shown on this page (the report holds them): "
            f"{found.dropped + found.withheld:,}."
            for found in facts.findings
        ),
    )
    add("fact", *(line for found in facts.findings for line in fact_lines(found, facts.aliases)))
    for rule_id in RULE_IDS:
        *quiet, disclaimer = quiet_lines([rule_id])
        add("quiet", *quiet)
        add("disclaimer", disclaimer)
    for category in CATEGORIES:
        for target in (None, *RULE_IDS):
            understanding = Understanding("refusal", categories=(category,), target=target)
            add("refusal", *refusal_body(rep, facts, understanding))
    for understanding in (
        Understanding("refusal"),
        Understanding("refusal", intent="summary", categories=("stopping",)),
        *(Understanding("unreadable", reason=reason) for reason in UNREADABLE_REASONS),
    ):
        add("refusal", *refusal_body(rep, facts, understanding))
    return lines


def _understood(what: str) -> bool:
    if what in UNDERSTOOD_FIXED:
        return True
    compound = COMPOUND.fullmatch(what)
    if not compound:
        return False
    categories = compound[1].split(", ")
    return all(c in CATEGORIES for c in categories) and categories == sorted(
        set(categories), key=CATEGORIES.index
    )


def _violation(item: str) -> bool:
    """A code of the six and, after it, the ID of a rule or `-`."""
    code, _, rule_id = item.partition(" ")
    return code in VIOLATION_CODES and rule_id in (*RULE_IDS, "-")


def classify(line: str, lines: dict[str, str]) -> str | None:
    """The template of `line` among those of `table`, or None if it is none of them."""
    if not line:
        return "blank"
    if line in lines:
        return lines[line]
    sentence = SENTENCE_LINE.fullmatch(line)
    if sentence and SENTENCES.get(sentence[1]) == sentence[2]:
        return "catalogue"
    understood = UNDERSTOOD.fullmatch(line)
    if understood and _understood(understood[1]):
        return "understood"
    also = ALSO.fullmatch(line)
    if also and all(category in CATEGORIES for category in also[1].split(", ")):
        return "refusal"
    withheld = WITHHELD.fullmatch(line)
    if withheld and all(_violation(item) for item in withheld[1].split(", ")):
        return "withheld"
    return None


def check_quiet_lines(page: str) -> None:
    """Assert that every `raised no finding` line of `page` is followed, in its block, by the
    disclaimer, that RES-004, RES-007 and RES-008 are never bare and that a quiet RES-008 quotes
    `RES-008.why.6` with its ID."""
    lines = page.split("\n")
    quiet = [number for number, line in enumerate(lines) if "raised no finding" in line]
    for number in quiet:
        block = lines[number : lines.index("", number)]
        assert any(line.endswith(DISCLAIMER) for line in block), lines[number]
        rule_id = lines[number].split()[0]
        if rule_id in ("RES-004", "RES-007", "RES-008"):
            assert lines[number].endswith(SUMMARISED_TAIL), lines[number]
        if rule_id == "RES-008":
            assert lines[number + 1].startswith("  [RES-008.why.6] "), lines[number + 1]


def runs_of_the_question(page: str, question: str, canonical: str, size: int = 12) -> list[str]:
    """The runs of `size` characters of `question` that `page` holds and `canonical` does not,
    compared without regard to case."""
    page, canonical, text = page.casefold(), canonical.casefold(), question.casefold()
    runs = (text[start : start + size] for start in range(len(text) - size + 1))
    return [run for run in runs if run in page and run not in canonical]
