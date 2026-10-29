"""The output contract of the narration layer (design section 24.6).

`narration_fakes` makes the outputs: the fixed selection and seeded subsets, which must be accepted
and printed, and one corruption for each case of the table of 24.6, which must be rejected with
exactly the violations its operator names.
"""

import json
import random

import pytest
from narration_fakes import OPERATORS, FakeNarrator, asks, fixed, fixed_text, subset, subset_text

from referee.narration.output import OutputError, offered_ids, parse_selection
from referee.narration.render import (
    VIOLATION_CODES,
    Chosen,
    Understanding,
    decision_block,
    render_answer,
    render_withheld,
)

_DECISIONS: dict[int, tuple[str, ...]] = {}


def decision(rep: dict) -> tuple[str, ...]:
    """The Decision block of a report, made once (the reports are shared and read only)."""
    if id(rep) not in _DECISIONS:
        _DECISIONS[id(rep)] = decision_block(rep)
    return _DECISIONS[id(rep)]


def chosen(obj: dict) -> dict[str, Chosen]:
    return {
        entry["id"]: Chosen(frozenset(entry["sentences"]), frozenset(entry["facts"]))
        for entry in obj["findings"]
    }


def without_labels(page: str) -> list[str]:
    """The lines of a page but the `Chosen by` lines of the fixed rule and of the model path."""
    return [
        line
        for line in page.split("\n")
        if not line.startswith(("Chosen by:", "For each finding narrated below"))
    ]


# --- Valid outputs ----------------------------------------------------------------------------


def test_the_fixed_selection_is_accepted_and_prints_the_page_of_the_fixed_rule(
    raw_spec: dict,
) -> None:
    for ask in asks(raw_spec):
        narrator = FakeNarrator(fixed_text(ask))
        selection = parse_selection(narrator(None), ask.report, ask.facts, ask.understanding)
        assert narrator.requests == [None]
        assert selection == chosen(fixed(ask)), ask.name

        args = (ask.report, ask.facts, ask.understanding, decision(ask.report))
        assert without_labels(render_answer(*args, selection)) == without_labels(
            render_answer(*args)
        ), ask.name


def variety(ask, obj: dict) -> set[str]:
    """What is different in the subset `obj` from the fixed output, so that a generator that stops
    producing a kind of difference is seen."""
    whole = {entry["id"]: entry for entry in fixed(ask)["findings"]}
    kept = [entry["id"] for entry in obj["findings"]]
    seen = set()
    if len(kept) < len(whole):
        seen.add("an info finding left out")
    if ask.intent != "explain_finding" and any(ask.severity[rule_id] == "info" for rule_id in kept):
        seen.add("an info finding kept beside others")
    if kept != [rule_id for rule_id in whole if rule_id in kept]:
        seen.add("entries not in report order")
    for entry in obj["findings"]:
        offered = whole[entry["id"]]
        kinds = [sentence_id.split(".")[1] for sentence_id in entry["sentences"]]
        if len(entry["sentences"]) < len(offered["sentences"]):
            seen.add("a part of the sentences")
        if offered["facts"] and not entry["facts"]:
            seen.add("no fact led")
        if 0 < len(entry["facts"]) < len(offered["facts"]):
            seen.add("a part of the facts")
        if kinds != sorted(kinds, reverse=True):  # not all the reasons before the advice
            seen.add("advice before a reason")
    return seen


def test_seeded_subsets_that_keep_every_blocker_and_warning_are_accepted_and_printed(
    raw_spec: dict,
) -> None:
    todo, seen = asks(raw_spec), set()
    for seed in range(600):  # about 12 for each of the 48 questions
        ask = todo[seed % len(todo)]
        obj = subset(ask, seed)
        selection = parse_selection(
            subset_text(ask, seed), ask.report, ask.facts, ask.understanding
        )
        assert selection == chosen(obj), (ask.name, seed)
        render_answer(ask.report, ask.facts, ask.understanding, decision(ask.report), selection)
        seen |= variety(ask, obj)
    assert len(seen) == 7, seen


def test_white_space_after_the_object_is_accepted_up_to_32_KiB(raw_spec: dict) -> None:
    ask = asks(raw_spec)[0]
    for text in [
        fixed_text(ask) + "\n",
        fixed_text(ask) + " \t\r\n",
        fixed_text(ask).ljust(32 * 1024),  # the operator over_32_KiB is one character more
    ]:
        selection = parse_selection(text, ask.report, ask.facts, ask.understanding)
        assert selection == chosen(fixed(ask))
    assert len(text) == 32768


def test_what_the_sheet_will_be_built_from_is_what_the_fixed_output_selects(raw_spec: dict) -> None:
    for ask in asks(raw_spec):
        offer = offered_ids(ask.report, ask.facts, ask.understanding)
        wanted = {
            entry["id"]: (tuple(entry["sentences"]), frozenset(entry["facts"]))
            for entry in fixed(ask)["findings"]
        }
        assert {rule_id: tuple(found) for rule_id, found in offer.items()} == wanted, ask.name
        assert list(offer) == ask.scope, ask.name


@pytest.mark.parametrize("kind", ["none", "int", "bytes", "bytearray"])
def test_anything_but_a_str_is_a_programming_error_not_an_output(raw_spec: dict, kind: str) -> None:
    ask = asks(raw_spec)[0]
    given = {
        "none": None,
        "int": 5,
        "bytes": fixed_text(ask).encode(),  # json would read these
        "bytearray": bytearray(fixed_text(ask).encode()),
    }[kind]
    with pytest.raises(TypeError):
        parse_selection(given, ask.report, ask.facts, ask.understanding)


# --- Corruptions ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(OPERATORS))
def test_a_corruption_is_rejected_with_the_violations_of_its_operator_and_no_others(
    raw_spec: dict, name: str
) -> None:
    code, operator = OPERATORS[name]
    applied = 0
    for ask in asks(raw_spec):
        made = operator(ask)
        if made is None:
            continue
        applied += 1
        with pytest.raises(OutputError) as caught:
            parse_selection(made.text, ask.report, ask.facts, ask.understanding)
        violations = caught.value.violations
        assert set(violations) == made.expected, ask.name
        assert code in {violation[0] for violation in violations}, ask.name
    assert applied  # an operator that applies to no question guards nothing


def test_every_code_of_the_design_has_an_operator() -> None:
    assert {code for code, _ in OPERATORS.values()} == set(VIOLATION_CODES)


def test_the_depth_bomb_is_deeper_than_the_json_parser_goes(raw_spec: dict) -> None:
    with pytest.raises(RecursionError):  # so that the corruption tests the catching of it
        json.loads(OPERATORS["depth_bomb"][1](asks(raw_spec)[0]).text)


# --- Whatever the str ---------------------------------------------------------------------------

PIECES = [
    *'{}[]",:-.0123456789eE \n\t\\u/',
    "true",
    "false",
    "null",
    "NaN",
    "Infinity",
    "\ud800",
    "\udc00",
    "\x00",
    "\u202e",
    "schema",
    "findings",
    "id",
    "facts",
    "sentences",
    "RES-001",
    "RES-001.why.1",
    "RES-001.p_value",
    "referee-narration-output/1",
]


def junk(rng: random.Random, todo: list) -> tuple:
    """A question and a str for it: random, or its fixed output edited at random (not at all, now
    and then), or a random JSON value."""
    ask, kind = rng.choice(todo), rng.randrange(3)
    if kind == 0:
        return ask, "".join(rng.choice(PIECES) for _ in range(rng.randrange(80)))
    if kind == 1:
        text = fixed_text(ask)
        for _ in range(rng.randint(0, 3)):
            at, to = sorted(rng.randrange(len(text) + 1) for _ in range(2))
            text = rng.choice(
                [
                    text[:at] + text[to:],  # a part deleted
                    text[:to] + text[at:to] + text[to:],  # a part repeated
                    text[:at] + rng.choice(PIECES) + text[at:],
                    text[:at],  # cut short
                ]
            )
        return ask, text

    def value(depth: int = 0) -> object:
        if depth > 5 or rng.random() < 0.4:
            return rng.choice([None, True, 1, 1.5, "", "RES-001", rng.choice(PIECES), [], {}])
        if rng.random() < 0.5:
            return [value(depth + 1) for _ in range(rng.randrange(4))]
        keys = ["schema", "findings", "id", "facts", "sentences", rng.choice(PIECES)]
        return {rng.choice(keys): value(depth + 1) for _ in range(rng.randrange(4))}

    return ask, json.dumps(value(), ensure_ascii=rng.random() < 0.5)


def test_no_str_makes_parse_selection_raise_anything_but_an_output_error(raw_spec: dict) -> None:
    todo, rng, accepted = asks(raw_spec), random.Random(20261029), 0
    cases = [(todo[0], text) for text in ["", " ", "{}", "[]", '"', "\ud800", "9" * 40_000]]
    cases += [(todo[0], "[" * 100_000), (todo[0], '{"a":' * 50_000)]
    cases += [junk(rng, todo) for _ in range(4_000)]
    for ask, text in cases:
        try:
            selection = parse_selection(text, ask.report, ask.facts, ask.understanding)
        except OutputError as error:
            by_code = [(VIOLATION_CODES.index(code), rule_id) for code, rule_id in error.violations]
            assert by_code == sorted(set(by_code))  # in the fixed order, without repeats
            assert all(rule_id in ["-", *ask.severity] for _, rule_id in error.violations)
            render_withheld(ask.report, ask.understanding, decision(ask.report), error.violations)
        else:
            accepted += 1
            assert set(selection) <= set(ask.scope)
    assert 100 < accepted < len(cases) // 2


# --- Nothing of the output is echoed ----------------------------------------------------------

CANARY = "canary-7f3a9c"


def edited(edit):
    """A text maker: the fixed output of a question after `edit`."""

    def text_of(ask) -> str:
        obj = fixed(ask)
        edit(obj)
        return json.dumps(obj)

    return text_of


@pytest.mark.parametrize(
    "text_of",
    [
        edited(lambda o: o["findings"][0].update(id=CANARY)),  # an entry for no rule
        edited(lambda o: o["findings"][0]["facts"].append(CANARY)),
        edited(lambda o: o["findings"][0].update({CANARY: "x"})),  # a key that is not allowed
        lambda ask: CANARY,  # not JSON: the parser's own error holds the text it could not read
    ],
)
def test_no_string_of_the_output_reaches_the_error_its_violations_or_its_chain(
    raw_spec: dict, text_of
) -> None:
    ask = asks(raw_spec)[0]
    with pytest.raises(OutputError) as caught:
        parse_selection(text_of(ask), ask.report, ask.facts, ask.understanding)
    error = caught.value
    for shown in (str(error), repr(error), repr(error.violations), "".join(error.args)):
        assert CANARY not in shown
    assert error.__context__ is None and error.__cause__ is None


# --- The violations: once, by code, then by ID --------------------------------------------------


def test_violations_are_listed_once_by_code_then_by_id_whatever_the_order_of_the_entries(
    raw_spec: dict,
) -> None:
    ask = next(a for a in asks(raw_spec) if a.name == "golden/summary")
    entries = {entry["id"]: entry for entry in fixed(ask)["findings"]}
    entries["RES-001"]["facts"] = ["x", "x"]  # a fact twice, and not offered by a summary
    entries["RES-001"]["sentences"] += ["y", "z"]  # two sources, one violation
    entries["RES-007"]["sentences"] = []  # no reason
    del entries["RES-002"]  # no entry for a blocker
    wanted = [
        ("scope", "-"),  # two entries for rules that are not findings, one violation
        ("duplicate", "RES-001"),  # twice a fact, once a finding
        ("duplicate", "RES-012"),
        ("fact", "RES-001"),
        ("source", "RES-001"),
        ("coverage", "RES-002"),
        ("coverage", "RES-007"),
    ]
    extra = [
        {"id": "ZZZ-1", "facts": [], "sentences": []},
        {"id": "ZZZ-2", "facts": [], "sentences": []},
        dict(entries["RES-012"]),
    ]
    rng = random.Random(1)
    for _ in range(10):
        listed = [*entries.values(), *extra]
        rng.shuffle(listed)
        text = json.dumps({"schema": fixed(ask)["schema"], "findings": listed})
        with pytest.raises(OutputError) as caught:
            parse_selection(text, ask.report, ask.facts, ask.understanding)
        assert caught.value.violations == wanted


# --- What no narrator can satisfy ---------------------------------------------------------------


@pytest.mark.parametrize(
    "understanding",
    [
        Understanding("answer", "checked"),
        Understanding("answer", "explain_finding", target="RES-003"),  # raised no finding
        Understanding("refusal", categories=("stopping",)),
    ],
)
def test_a_question_that_needs_no_narrator_accepts_no_output(
    raw_spec: dict, understanding: Understanding
) -> None:
    ask = next(a for a in asks(raw_spec) if a.name == "golden/summary")
    for text, wanted in [
        (fixed_text(ask), [("scope", entry["id"]) for entry in fixed(ask)["findings"]]),
        (json.dumps({"schema": fixed(ask)["schema"], "findings": []}), [("coverage", "-")]),
    ]:
        with pytest.raises(OutputError) as caught:
            parse_selection(text, ask.report, ask.facts, understanding)
        assert caught.value.violations == wanted
