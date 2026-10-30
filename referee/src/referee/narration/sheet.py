"""The sheet of the model path and the egress assertion (design section 24.4).

    request = build_request(report, facts, understanding)    # a ModelRequest, or EgressError

The sheet is what the narrator is shown: canonical JSON of the task (the closed intent and the
canonical target, never the question), an alias for each arm (`A1` for the control, then `A2`, `A3`
in the order of the fact list) and, for each finding in scope, its rule ID, severity and title, the
sentences the intent offers by ID with their text, and the facts it offers by ID with their label
and value. It is built from `offered_ids`, the scope the output check judges against, so that the
two cannot disagree. It holds no verdict, effect table or population block. Counts, p values, rates
and allocations are in it, and leave with the request; the aliases hide the arms' names and nothing
else.

Before a request is made the egress assertion compares the report with the sheet. Every token of a
string of the report, a key included (a run of letters, digits and underscores, case folded), that
is not in the vocabulary of the sheet, which is all that code writes into it (catalogue text, the
allowlist, the roles, the aliases, the labels), must not be among the tokens of the sheet; if one
is, the request is not made (`EgressError`, a failure inside Referee). A leak of a word that is
also in the vocabulary (an arm named `control`) is invisible to this, and the canary test of the
sheet is the proof for it.
"""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Any

from referee.narration.facts import (
    ALLOWLIST,
    SEVERITIES,
    FactList,
    catalogue_sentences,
)
from referee.narration.narrator import ModelRequest
from referee.narration.output import SCHEMA, offered_ids
from referee.narration.render import INTENTS, Understanding

MAX_TOKENS = 4096  # of the answer: an entry of 64 facts and 16 sentences is about a thousand

SYSTEM = (
    "You select identifiers from a sheet. The sheet is the user message: JSON that lists, for each "
    "finding of the review of an experiment, its sentences and facts, each with an identifier. "
    f"Answer with ONLY one JSON object of schema {SCHEMA} and nothing else: "
    f'{{"schema": "{SCHEMA}", "findings": [{{"id": <rule_id>, "facts": [<fact id>, ...], '
    '"sentences": [<sentence id>, ...]}]}. '
    "Every value is an identifier copied from the sheet. There is no field for text, and no "
    "number, explanation or refusal. Give an entry for every blocker and warning and for the "
    "task's target, each with at least one sentence of every kind (why, do) that the sheet lists "
    "for it; an info finding may be left out. What you select leads the page and code prints "
    "the rest after it."
)

# The words code writes into the sheet besides the catalogue text and the allowlist.
WORDS = (
    "task intent target arms alias role control variant findings rule_id severity title "
    "sentences id text facts label value"
)

_TOKEN = re.compile(r"\w+")


class EgressError(ValueError):
    """A word of the report that code did not write is in the sheet: nothing is sent."""


def tokens(node: object) -> set[str]:
    """The tokens, case folded, of every string of a JSON value and of every key."""
    found: set[str] = set()
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.update(_TOKEN.findall(item.casefold()))
        elif isinstance(item, dict):
            stack.extend(item)
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            stack.extend(item)
    return found


@cache
def _written_by_code() -> frozenset[str]:
    """The tokens of the catalogue (sentence IDs included), the allowlist (paths, labels and words),
    the intents and severities, and the words of the sheet itself: all that a sheet holds."""
    table = [
        (path, admitted.label, admitted.words)
        for rules in ALLOWLIST.values()
        for path, admitted in rules.items()
    ]
    return frozenset(tokens([catalogue_sentences(), table, INTENTS, SEVERITIES, WORDS]))


def vocabulary(facts: FactList) -> set[str]:
    """Everything code writes into a sheet for this report: the above and the arms' aliases."""
    return set(_written_by_code()) | tokens(list(facts.aliases.values()))


def check_egress(report: object, sheet: object, words: set[str]) -> None:
    """Raise `EgressError` if a token of `report` that is not in `words` is among those of `sheet`.
    The tokens are not in the message: they are the report's."""
    if (tokens(report) - words) & tokens(sheet):
        raise EgressError("a word of the report reached the sheet")


def sheet(report: dict[str, Any], facts: FactList, understanding: Understanding) -> dict[str, Any]:
    """The sheet for an understanding of kind answer whose scope has a finding."""
    offer = offered_ids(report, facts, understanding)
    text = catalogue_sentences()
    severity = {finding["rule_id"]: finding["severity"] for finding in report["findings"]}
    found = {item.rule_id: item.facts for item in facts.findings}
    return {
        "task": {"intent": understanding.answered_as, "target": understanding.target},
        "arms": [
            {"alias": alias, "role": "variant" if number > 1 else "control"}
            for number, alias in enumerate(facts.aliases.values(), 1)
        ],
        "findings": [
            {
                "rule_id": rule_id,
                "severity": severity[rule_id],
                "title": text[f"{rule_id}.title"],
                "sentences": [{"id": sid, "text": text[sid]} for sid in offered.sentences],
                "facts": [
                    {"id": fact.id, "label": fact.label, "value": fact.value}
                    for fact in found[rule_id]
                    if fact.id in offered.facts
                ],
            }
            for rule_id, offered in offer.items()
        ],
    }


def build_request(
    report: dict[str, Any], facts: FactList, understanding: Understanding
) -> ModelRequest:
    """The request for a question that needs a narrator. The question is not an argument: the
    model sees the intent and the target the router made of it, nothing else."""
    made = sheet(report, facts, understanding)
    check_egress(report, made, vocabulary(facts))
    user = json.dumps(made, sort_keys=True, separators=(",", ":"))
    return ModelRequest(SYSTEM, user, MAX_TOKENS)
