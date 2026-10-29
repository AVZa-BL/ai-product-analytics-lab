"""What a narrator may return (design section 24.6): identifiers, checked for scope, source and
coverage, never relevance.

    parse_selection(text, report, facts, understanding) -> Selection    # or raises OutputError

`text` is the decoded `str` a narrator returned; `report`, `facts` and `understanding` are those of
the page it will be printed on (a report that passed the check and its fact list). The result is
what `render_answer` takes: `{finding ID: Chosen(sentences, facts)}`. There is no retry and no
repair, and the output is never printed or kept: an `OutputError` holds `violations`, a list of
`(code, finding ID)` as `render_withheld` takes them, and nothing of the text. The ID is that of a
finding of the report and `-` otherwise, so a string of the output reaches no message, no violation
and no exception chain.

The text is one JSON object, `{"schema": "referee-narration-output/1", "findings": [{"id": ...,
"facts": [...], "sentences": [...]}]}`, of identifiers only; its depth of 4 is that shape, so a
deeper value is a value of the wrong type. A violation of the shape (`schema`) is all that is
reported then, since no entry can be read; the entries of a text of the right shape are judged
against what the intent offers (`offered`, `sentence_ids`, `findings_in_scope` of `render` and the
fact list; nothing is restated here), and all the violations found are reported:

    scope       an entry for a rule that is not a finding in scope (judged by that alone)
    duplicate   a finding ID twice, or a fact or sentence ID twice in an entry
    fact        a fact ID the entry's finding is not offered
    source      a sentence ID the entry's finding is not offered
    coverage    no entry for a blocker or warning (for an explanation: for its target, whatever its
                severity), no entry at all, or an entry without a sentence of each kind offered

Violations are listed without repeats, by code in the order of `VIOLATION_CODES` and then by ID
(`-` first), whatever the order of the entries: the narrator's order is never used.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from referee.narration.facts import FactList
from referee.narration.render import (
    VIOLATION_CODES,
    Chosen,
    Selection,
    Understanding,
    findings_in_scope,
    offered,
    sentence_ids,
)

SCHEMA = "referee-narration-output/1"
MAX_CHARS = 32 * 1024  # of the whole text
MAX_FACTS = 64  # fact IDs in an entry
MAX_SENTENCES = 16  # sentence IDs in an entry
MAX_ID_CHARS = 64  # in an identifier


class OutputError(ValueError):
    """The output of a narrator broke the contract. `violations` is the list of `(code, ID)`, the
    message only those codes and IDs."""

    def __init__(self, violations: list[tuple[str, str]]) -> None:
        self.violations = violations
        super().__init__(", ".join(f"{code} {rule_id}" for code, rule_id in violations))


def _no_number(_text: str) -> None:
    raise ValueError("a number")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("a repeated key")
    return dict(pairs)


def _decode(text: str) -> object:
    """The JSON value of `text`, or None, which is no output either, for a text that is too long,
    is not JSON, repeats a key, holds a number, or is nested beyond the parser's limit."""
    if len(text) > MAX_CHARS:
        return None
    try:
        return json.loads(
            text,
            object_pairs_hook=_object,
            parse_int=_no_number,
            parse_float=_no_number,
            parse_constant=_no_number,
        )
    except (ValueError, RecursionError):
        return None


def _identifier(value: object) -> bool:
    """A string of at most 64 characters with no lone surrogate."""
    if not isinstance(value, str) or len(value) > MAX_ID_CHARS:
        return False
    try:
        value.encode()
    except UnicodeEncodeError:
        return False
    return True


def _identifiers(value: object, most: int) -> bool:
    return isinstance(value, list) and len(value) <= most and all(map(_identifier, value))


def _well_formed(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and set(entry) == {"id", "facts", "sentences"}
        and _identifier(entry["id"])
        and _identifiers(entry["facts"], MAX_FACTS)
        and _identifiers(entry["sentences"], MAX_SENTENCES)
    )


def _shown(rule_id: object, severity: dict[str, str]) -> str:
    """The ID of a finding of the report, `-` for anything else (any string of the output)."""
    return rule_id if isinstance(rule_id, str) and rule_id in severity else "-"


def _judge(
    entries: list[dict[str, Any]],
    report: dict[str, Any],
    severity: dict[str, str],
    facts: FactList,
    understanding: Understanding,
) -> set[tuple[str, str]]:
    """Scope, duplicates, facts, sources and coverage of entries of the right shape."""
    fact_ids = {found.rule_id: {fact.id for fact in found.facts} for found in facts.findings}
    scope, intent = findings_in_scope(report, understanding), understanding.answered_as
    ids = [entry["id"] for entry in entries]
    found = {
        ("duplicate", _shown(rule_id, severity)) for rule_id, n in Counter(ids).items() if n > 1
    }
    if not entries:
        found.add(("coverage", "-"))
    for rule_id in scope:  # an explanation needs its target, whatever its severity
        if rule_id not in ids and (intent == "explain_finding" or severity[rule_id] != "info"):
            found.add(("coverage", rule_id))
    for entry in entries:
        rule_id = entry["id"]
        shown = _shown(rule_id, severity)
        if rule_id not in scope:
            found.add(("scope", shown))
            continue
        sentences, chosen_facts = entry["sentences"], entry["facts"]
        wanted = sentence_ids(rule_id, intent)
        allowed = fact_ids[rule_id] if offered(intent).facts else set()
        if not allowed.issuperset(chosen_facts):
            found.add(("fact", shown))
        if not set(wanted).issuperset(sentences):
            found.add(("source", shown))
        if len(set(chosen_facts)) < len(chosen_facts) or len(set(sentences)) < len(sentences):
            found.add(("duplicate", shown))
        # the kind is the middle part of RES-001.why.1; wanted holds the kinds the intent offers
        if {s.split(".")[1] for s in sentences if s in wanted} != {s.split(".")[1] for s in wanted}:
            found.add(("coverage", shown))
    return found


def parse_selection(
    text: str,
    report: dict[str, Any],
    facts: FactList,
    understanding: Understanding,
) -> Selection:
    """The selection `text` makes, or `OutputError` listing every violation found. Never any other
    exception, whatever the `str`; the arguments must be those of one page, as `render_answer`'s."""
    data = _decode(text)
    severity = {finding["rule_id"]: finding["severity"] for finding in report["findings"]}
    if not (
        isinstance(data, dict)
        and set(data) == {"schema", "findings"}
        and data["schema"] == SCHEMA
        and isinstance(data["findings"], list)
    ):
        raise OutputError([("schema", "-")])
    entries = data["findings"]
    found = {
        ("schema", _shown(entry.get("id") if isinstance(entry, dict) else None, severity))
        for entry in entries
        if not _well_formed(entry)
    }
    if not found:  # the shape comes first: only entries of the right shape are judged
        found = _judge(entries, report, severity, facts, understanding)
    if found:
        order = {code: number for number, code in enumerate(VIOLATION_CODES)}
        raise OutputError(sorted(found, key=lambda violation: (order[violation[0]], violation[1])))
    return {
        entry["id"]: Chosen(frozenset(entry["sentences"]), frozenset(entry["facts"]))
        for entry in entries
    }
