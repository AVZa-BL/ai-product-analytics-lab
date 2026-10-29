"""Fake narrators and corrupted outputs for the output contract (design sections 24.6 and 24.16).

A narrator is a callable from a request to the raw text of a selection. N7b defines the request,
`ModelRequest`, the type `Narrator` and `NarratorError`; nothing here does, so the fakes ignore what
they are asked and are made for one question.

    asks(raw_spec)              # every question that needs a narrator, on the eight fixtures and on
                                # the golden with one finding demoted to info: read only, shared
    fixed(ask), fixed_text(ask)         # all the intent permits for every finding in scope
    subset(ask, seed), subset_text(ask, seed)   # a valid part of it, in a random order
    OPERATORS                   # name -> (code, operator); operator(ask) -> Corrupt or None
    FakeNarrator(text)          # a plain callable that returns `text` and keeps its requests

A `Corrupt` is a text with the exact set of `(code, ID)` that `parse_selection` must report for it.
An operator corrupts `fixed(ask)` in one way, so the violations of the whole are those of the one
corruption; it returns None for a question to which that corruption does not apply. The numbers of
the design (the schema string, the caps) are written out here and not imported, so that a changed
constant in the contract is a failing operator.
"""

import copy
import hashlib
import json
import random
from collections.abc import Callable
from typing import NamedTuple

from narration_reports import NAMES, report

from referee.narration.facts import FactList, check_report_consistency, fact_list
from referee.narration.render import (
    Understanding,
    findings_in_scope,
    needs_narrator,
    offered,
    sentence_ids,
)

SCHEMA = "referee-narration-output/1"


class Ask(NamedTuple):
    """A question that needs a narrator: the report that passed the check, its fact list and what
    the router made of the question."""

    name: str
    report: dict
    facts: FactList
    understanding: Understanding

    @property
    def intent(self) -> str:
        return self.understanding.answered_as

    @property
    def scope(self) -> list[str]:
        return findings_in_scope(self.report, self.understanding)

    @property
    def severity(self) -> dict[str, str]:
        return {finding["rule_id"]: finding["severity"] for finding in self.report["findings"]}

    @property
    def fact_ids(self) -> dict[str, list[str]]:
        return {found.rule_id: [fact.id for fact in found.facts] for found in self.facts.findings}


def _with_info(rep: dict) -> dict:
    """`rep` with its RES-008 finding demoted to info (as in test_narration_render) and the counts,
    the order of the findings and the evidence changed to match, so that it passes the check."""
    rep = copy.deepcopy(rep)
    finding = next(f for f in rep["findings"] if f["rule_id"] == "RES-008")
    finding["evidence"]["summary"].update(largest_simulated_rate=0.04, floor_ranges=0)
    finding["severity"] = "info"
    rep["findings"].remove(finding)
    rep["findings"].append(finding)
    rep["counts"].update(warning=rep["counts"]["warning"] - 1, info=1)
    check_report_consistency(rep)
    return rep


_ASKS: dict[str, list[Ask]] = {}


def asks(raw_spec: dict) -> list[Ask]:
    """Summary, next steps, an explanation with no target (answered as a summary) and the
    explanation of each finding, on each report that has a finding (`clear` has none, and `checked`
    and a quiet rule need no narrator)."""
    key = hashlib.sha256(json.dumps(raw_spec, sort_keys=True).encode()).hexdigest()
    if key not in _ASKS:
        reports = {name: report(name, raw_spec) for name in NAMES}
        reports["golden_with_info"] = _with_info(reports["golden"])
        made = []
        for name, rep in reports.items():
            found = fact_list(rep)
            raised = [finding["rule_id"] for finding in rep["findings"]]
            for label, understanding in [
                ("summary", Understanding("answer", "summary")),
                ("next_steps", Understanding("answer", "next_steps")),
                # no single rule named: answered as a summary
                ("no_target", Understanding("answer", "explain_finding", as_summary=True)),
                *[
                    (rule_id, Understanding("answer", "explain_finding", target=rule_id))
                    for rule_id in raised
                ],
            ]:
                if needs_narrator(rep, understanding):
                    made.append(Ask(f"{name}/{label}", rep, found, understanding))
        _ASKS[key] = made
    return _ASKS[key]


# --- Valid outputs ----------------------------------------------------------------------------


def fixed(ask: Ask) -> dict:
    """The output that selects, for every finding in scope, all the intent offers."""
    with_facts = offered(ask.intent).facts
    return {
        "schema": SCHEMA,
        "findings": [
            {
                "id": rule_id,
                "facts": ask.fact_ids[rule_id] if with_facts else [],
                "sentences": list(sentence_ids(rule_id, ask.intent)),
            }
            for rule_id in ask.scope
        ],
    }


def fixed_text(ask: Ask) -> str:
    return json.dumps(fixed(ask))


def subset(ask: Ask, seed: int) -> dict:
    """A valid output: every blocker and warning (and an explanation's target) with a random part of
    what is offered, a sentence of each kind at least; each info finding in or out; the entries
    and the IDs in a random order."""
    rng = random.Random(seed)
    entries = []
    for entry in fixed(ask)["findings"]:
        if (
            ask.severity[entry["id"]] == "info"
            and ask.intent != "explain_finding"
            and rng.random() < 0.5
        ):
            continue
        kinds: dict[str, list[str]] = {}
        for sentence_id in entry["sentences"]:
            kinds.setdefault(sentence_id.split(".")[1], []).append(sentence_id)
        sentences = [
            sentence_id
            for group in kinds.values()
            for sentence_id in rng.sample(group, rng.randint(1, len(group)))
        ]
        rng.shuffle(sentences)
        facts = rng.sample(entry["facts"], rng.randint(0, len(entry["facts"])))
        entries.append({"id": entry["id"], "facts": facts, "sentences": sentences})
    rng.shuffle(entries)
    return {"schema": SCHEMA, "findings": entries}


def subset_text(ask: Ask, seed: int) -> str:
    return json.dumps(subset(ask, seed))


class FakeNarrator:
    """A narrator: a plain callable from a request, whatever it is, to the raw text `text`. It keeps
    the requests it was given, so that a test can count its calls."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[object] = []

    def __call__(self, request: object) -> str:
        self.requests.append(request)
        return self.text


# --- Corruptions ------------------------------------------------------------------------------


class Corrupt(NamedTuple):
    """A corrupted output and the violations it must give, exactly."""

    text: str
    expected: frozenset[tuple[str, str]]


Operator = Callable[[Ask], Corrupt | None]
OPERATORS: dict[str, tuple[str, Operator]] = {}  # name -> (the code it is made for, operator)


def _operator(code: str) -> Callable[[Operator], Operator]:
    def register(function: Operator) -> Operator:
        OPERATORS[function.__name__] = (code, function)
        return function

    return register


def _made(output: object, *violations: tuple[str, str]) -> Corrupt:
    text = output if isinstance(output, str) else json.dumps(output)
    return Corrupt(text, frozenset(violations))


def _first(ask: Ask) -> tuple[dict, dict]:
    obj = fixed(ask)
    return obj, obj["findings"][0]


def _other(ask: Ask) -> str | None:
    """A finding of the report that is not the first one in scope."""
    return next((rule for rule in ask.severity if rule != ask.scope[0]), None)


# The whole text is not an output: no entry can be read, so the violation has no finding.
def _text_operator(name: str, make: Callable[[Ask], str | dict | list]) -> None:
    OPERATORS[name] = ("schema", lambda ask: _made(make(ask), ("schema", "-")))


def _with(obj: dict, **changes: object) -> dict:
    return {**obj, **changes}


def _without(obj: dict, key: str) -> dict:
    return {k: v for k, v in obj.items() if k != key}


def _raw(ask: Ask, raw: str) -> str:
    """The fixed output with `raw`, as written, for the first fact ID."""
    obj, entry = _first(ask)
    entry["facts"] = ["@"]
    return json.dumps(obj).replace('"@"', raw)


for _name, _make in {
    "extra_top_key": lambda ask: _with(fixed(ask), note="x"),
    "missing_schema_key": lambda ask: _without(fixed(ask), "schema"),
    "missing_findings_key": lambda ask: _without(fixed(ask), "findings"),
    "wrong_schema_string": lambda ask: _with(fixed(ask), schema="referee-narration-output/2"),
    "findings_not_a_list": lambda ask: _with(fixed(ask), findings={}),
    "top_level_a_list_of_the_keys": lambda ask: ["schema", "findings"],
    "duplicate_top_key": lambda ask: fixed_text(ask).replace(
        '{"schema": ', '{"schema": "", "schema": ', 1
    ),
    "duplicate_entry_key": lambda ask: fixed_text(ask).replace(
        f'{{"id": "{ask.scope[0]}"', f'{{"id": "{ask.scope[0]}", "id": "{ask.scope[0]}"', 1
    ),
    "an_integer": lambda ask: _raw(ask, "1"),
    "a_float": lambda ask: _raw(ask, "1.5"),
    "a_5000_digit_integer": lambda ask: _raw(ask, "9" * 5000),
    "a_float_beyond_the_range": lambda ask: _raw(ask, "1e999"),
    "nan": lambda ask: _raw(ask, "NaN"),
    "infinity": lambda ask: _raw(ask, "Infinity"),
    "trailing_text": lambda ask: fixed_text(ask) + " done",
    "code_fence": lambda ask: f"```json\n{fixed_text(ask)}\n```",
    "not_json": lambda ask: "I cannot choose among these.",
    "depth_bomb": lambda ask: "[" * 20_000,
    "over_32_KiB": lambda ask: fixed_text(ask).ljust(32 * 1024 + 1),  # white space is not the fault
}.items():
    _text_operator(_name, _make)


def _entry_operator(name: str, edit: Callable[[dict], object], shown: bool) -> None:
    """The first entry after `edit`; a violation of its shape shows its finding if it has an ID."""

    def operator(ask: Ask) -> Corrupt:
        obj, entry = _first(ask)
        rule_id = entry["id"]
        edit(entry)
        return _made(obj, ("schema", rule_id if shown else "-"))

    OPERATORS[name] = ("schema", operator)


for _name, _edit in {
    "more_than_64_facts": lambda e: e.update(facts=[f"f{k}" for k in range(65)]),
    "more_than_16_sentences": lambda e: e.update(sentences=[f"s{k}" for k in range(17)]),
    "an_over_long_fact_id": lambda e: e["facts"].append("f" * 65),
    "an_over_long_sentence_id": lambda e: e["sentences"].append("s" * 65),
    "an_unhashable_fact_id": lambda e: e["facts"].append({"a": "b"}),
    "an_unhashable_sentence_id": lambda e: e["sentences"].append(["a"]),
    "a_fact_id_nested_5_deep": lambda e: e["facts"].append([[[["a"]]]]),
    "a_lone_surrogate_escaped": lambda e: e["facts"].append("\ud800"),
    "missing_facts_key": lambda e: e.pop("facts"),
    "missing_sentences_key": lambda e: e.pop("sentences"),
    "an_extra_entry_key": lambda e: e.update(text="Selected."),
    "facts_not_a_list": lambda e: e.update(facts="x"),
    "sentences_not_a_list": lambda e: e.update(sentences={}),
}.items():
    _entry_operator(_name, _edit, shown=True)

for _name, _edit in {
    "an_over_long_entry_id": lambda e: e.update(id="r" * 65),
    "an_unhashable_entry_id": lambda e: e.update(id=[e["id"]]),
    "missing_id_key": lambda e: e.pop("id"),
}.items():
    _entry_operator(_name, _edit, shown=False)


@_operator("schema")
def an_entry_that_is_a_string(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    obj["findings"][0] = entry["id"]
    return _made(obj, ("schema", "-"))


@_operator("schema")
def an_entry_that_is_a_list_of_the_keys(ask: Ask) -> Corrupt:
    obj, _ = _first(ask)
    obj["findings"][0] = ["id", "facts", "sentences"]
    return _made(obj, ("schema", "-"))


# The caps themselves are not violations of shape: an entry with 64 facts, 16 sentences or an
# identifier of 64 characters is judged on what it selects.
@_operator("fact")
def facts_at_the_cap(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["facts"] += [f"f{k}" for k in range(64 - len(entry["facts"]))]
    return _made(obj, ("fact", entry["id"]))


@_operator("source")
def sentences_at_the_cap(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["sentences"] += [f"s{k}" for k in range(16 - len(entry["sentences"]))]
    return _made(obj, ("source", entry["id"]))


@_operator("fact")
def a_fact_id_of_64_characters(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["facts"].append("f" * 64)
    return _made(obj, ("fact", entry["id"]))


@_operator("scope")
def an_entry_for_an_unknown_rule(ask: Ask) -> Corrupt:
    obj, _ = _first(ask)
    obj["findings"].append({"id": "ZZZ-123", "facts": [], "sentences": []})
    return _made(obj, ("scope", "-"))


@_operator("scope")
def an_entry_for_a_rule_that_raised_nothing(ask: Ask) -> Corrupt | None:
    quiet = next((rule for rule in ask.report["rules_run"] if rule not in ask.severity), None)
    if quiet is None:
        return None
    obj, _ = _first(ask)
    entry = {"id": quiet, "facts": [], "sentences": list(sentence_ids(quiet, ask.intent))}
    obj["findings"].append(entry)
    return _made(obj, ("scope", "-"))


def _entry_for(ask: Ask, rule_id: str) -> dict:
    """What the explanation of `rule_id` would offer, as an entry."""
    return {
        "id": rule_id,
        "facts": ask.fact_ids[rule_id],
        "sentences": list(sentence_ids(rule_id, "explain_finding")),
    }


@_operator("scope")
def an_explanation_that_names_another_finding_instead(ask: Ask) -> Corrupt | None:
    other = _other(ask)
    if ask.intent != "explain_finding" or other is None:
        return None
    obj, _ = _first(ask)
    obj["findings"] = [_entry_for(ask, other)]
    return _made(obj, ("scope", other), ("coverage", ask.scope[0]))


@_operator("duplicate")
def the_same_finding_twice(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    obj["findings"].append(copy.deepcopy(entry))
    return _made(obj, ("duplicate", entry["id"]))


@_operator("duplicate")
def the_same_fact_twice(ask: Ask) -> Corrupt | None:
    obj, entry = _first(ask)
    if not entry["facts"]:  # the intent offers no facts
        return None
    entry["facts"].append(entry["facts"][0])
    return _made(obj, ("duplicate", entry["id"]))


@_operator("duplicate")
def the_same_sentence_twice(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["sentences"].append(entry["sentences"][0])
    return _made(obj, ("duplicate", entry["id"]))


@_operator("fact")
def a_fact_id_not_in_the_sheet(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["facts"].append(f"{entry['id']}.no_such_fact")
    return _made(obj, ("fact", entry["id"]))


@_operator("fact")
def a_fact_id_of_another_finding(ask: Ask) -> Corrupt | None:
    other = _other(ask)
    if ask.intent != "explain_finding" or other is None:
        return None
    obj, entry = _first(ask)
    entry["facts"].append(ask.fact_ids[other][0])
    return _made(obj, ("fact", entry["id"]))


@_operator("fact")
def a_fact_id_the_intent_does_not_offer(ask: Ask) -> Corrupt | None:
    obj, entry = _first(ask)
    if ask.intent == "explain_finding":
        return None
    entry["facts"].append(ask.fact_ids[entry["id"]][0])
    return _made(obj, ("fact", entry["id"]))


@_operator("source")
def a_sentence_id_not_in_the_sheet(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    entry["sentences"].append(f"{entry['id']}.why.99")
    return _made(obj, ("source", entry["id"]))


@_operator("source")
def a_sentence_id_of_another_finding(ask: Ask) -> Corrupt | None:
    other = _other(ask)
    if other is None:
        return None
    obj, entry = _first(ask)
    entry["sentences"].append(f"{other}.{'do' if ask.intent == 'next_steps' else 'why'}.1")
    return _made(obj, ("source", entry["id"]))


@_operator("source")
def a_sentence_id_the_intent_does_not_offer(ask: Ask) -> Corrupt:
    obj, entry = _first(ask)
    # the advice for a summary, the reason for next steps, and for an explanation the title
    unoffered = {"summary": "do.1", "next_steps": "why.1", "explain_finding": "title"}[ask.intent]
    entry["sentences"].append(f"{entry['id']}.{unoffered}")
    return _made(obj, ("source", entry["id"]))


def _without_entry_for(ask: Ask, severity: str) -> Corrupt | None:
    obj = fixed(ask)
    gone = next((e["id"] for e in obj["findings"] if ask.severity[e["id"]] == severity), None)
    if gone is None:
        return None
    obj["findings"] = [entry for entry in obj["findings"] if entry["id"] != gone]
    expected = {("coverage", gone)}
    if not obj["findings"]:  # no entry at all
        expected.add(("coverage", "-"))
    return _made(obj, *expected)


@_operator("coverage")
def no_entry_for_a_blocker(ask: Ask) -> Corrupt | None:
    return _without_entry_for(ask, "blocker")


@_operator("coverage")
def no_entry_for_a_warning(ask: Ask) -> Corrupt | None:
    return _without_entry_for(ask, "warning")


def _without_kind(ask: Ask, kind: str) -> Corrupt | None:
    obj, entry = _first(ask)
    kept = [sentence for sentence in entry["sentences"] if sentence.split(".")[1] != kind]
    if len(kept) == len(entry["sentences"]):  # the intent does not offer this kind
        return None
    entry["sentences"] = kept
    return _made(obj, ("coverage", entry["id"]))


@_operator("coverage")
def an_entry_with_no_reason(ask: Ask) -> Corrupt | None:
    return _without_kind(ask, "why")


@_operator("coverage")
def an_entry_with_no_advice(ask: Ask) -> Corrupt | None:
    return _without_kind(ask, "do")


@_operator("coverage")
def no_entry_at_all(ask: Ask) -> Corrupt:
    needed = [
        rule_id
        for rule_id in ask.scope
        if ask.intent == "explain_finding" or ask.severity[rule_id] != "info"
    ]
    return _made(_with(fixed(ask), findings=[]), *[("coverage", r) for r in [*needed, "-"]])


@_operator("coverage")
def an_info_target_without_its_entry(ask: Ask) -> Corrupt | None:
    if ask.intent != "explain_finding" or ask.severity[ask.scope[0]] != "info":
        return None
    return _made(_with(fixed(ask), findings=[]), ("coverage", ask.scope[0]), ("coverage", "-"))
