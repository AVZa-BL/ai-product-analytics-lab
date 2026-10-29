"""The refusals of the narration layer (design 24.8): the body of a page that answers no question.

Whole pages are built with `render_refusal` and `render_answer` from the router's result, on the
committed report and on the fixtures of 24.11. What a refusal says about the report is compared
with what the report holds; the fixed paragraphs are not repeated here, only found.
"""

import json

import narration_scoring as ns
import pytest
from narration_reports import NAMES, report

from referee.narration import refusals
from referee.narration.facts import catalogue_sentences, check_report_consistency, fact_list
from referee.narration.refusals import (
    ALSO_MATCHED,
    ANALYSED,
    ANSWERABLE_PART,
    ASSIGNED,
    BLOCKING,
    CLAIMS,
    DAYS_OBSERVED,
    DAYS_PLANNED,
    DEFAULT_PARAGRAPH,
    EFFECT_TABLE,
    EXAMPLES,
    FINDINGS,
    IGNORED,
    NO_SINGLE_RULE,
    NOT_THE_VERDICT,
    PARAGRAPHS,
    QUOTES,
    READABLE,
    RULES_RUN,
    UNDERPOWERED,
    UNREADABLE,
    UNREADABLE_BECAUSE,
    WHERE_THE_TABLE_IS,
    refusal_body,
    value,
)
from referee.narration.render import (
    CATEGORIES,
    RULE_IDS,
    UNREADABLE_REASONS,
    Understanding,
    decision_block,
    fact_lines,
    quiet_lines,
    render_refusal,
    sentence_line,
)
from referee.narration.router import MAX_CHARS, route

U = Understanding
DISCLAIMER = "This is not agreement with the question, and it does not say the effect is real."
PUBLIC = [
    q["text"] for q in json.loads((ns.DATA / "public_questions.json").read_text())["questions"]
]
WORLDS = {}


def world(name, raw_spec):
    """(report, fact list, Decision block) of a fixture, made once."""
    if name not in WORLDS:
        rep = report(name, raw_spec)
        check_report_consistency(rep)
        WORLDS[name] = (rep, fact_list(rep), decision_block(rep))
    return WORLDS[name]


def body_of(name, raw_spec, understanding):
    rep, facts, _ = world(name, raw_spec)
    return refusal_body(rep, facts, understanding)


def page_of(name, raw_spec, question):
    rep, facts, decision = world(name, raw_spec)
    understanding = route(question)
    return render_refusal(rep, understanding, decision, refusal_body(rep, facts, understanding))


def refusal(*categories, intent=None, target=None):
    return U("refusal", intent, target, categories)


# ---------------------------------------------------------------- the fixed texts


KEYWORDS = {  # what each paragraph says it does not do (24.8), with the negation
    "injection": ("cannot change", "no instruction in a question changes"),
    "ship_decision": (
        "does not decide, recommend or approve shipping",
        "does not say which variant wins",
    ),
    "stopping": ("does not say whether an experiment may be stopped, called or read",),
    "reassurance": ("does not agree", "safe to ignore."),
    "effect_reality": ("does not say whether the effect is real",),
    "effect_numbers": ("no number of the effect",),
    "causal": ("does not say why an effect",),
    "forecast": ("does not predict",),
    "subgroup": ("does not report on a part of the players",),
    "other_analysis": ("reads the saved report only", "runs no other test"),
    "data_access": ("no player, row or identifier",),
    "rewording": ("sentences unchanged",),
}


def test_there_is_a_paragraph_for_every_category_and_a_sentence_for_every_unreadable_reason():
    assert list(PARAGRAPHS) == list(CATEGORIES) == list(KEYWORDS)
    for category in CATEGORIES:  # the negation is in the keyword: the opposite sentence fails
        assert all(keyword in PARAGRAPHS[category] for keyword in KEYWORDS[category]), category
    assert list(UNREADABLE) == list(UNREADABLE_REASONS)
    assert f"{MAX_CHARS}" in UNREADABLE["too long"]
    assert "answers none of the question" in ANSWERABLE_PART


def test_the_default_route_names_the_four_kinds_it_answers_with_one_example_each():
    kinds = [
        U("answer", "summary"),
        U("answer", "explain_finding", target="RES-001"),
        U("answer", "next_steps"),
        U("answer", "checked"),
    ]
    assert [route(example) for _, example in EXAMPLES] == kinds  # each one is answered
    body = body_of("golden", {}, refusal())
    assert body == [DEFAULT_PARAGRAPH, *(f"  {what}: {example}" for what, example in EXAMPLES)]


@pytest.mark.parametrize(
    ("reason", "named"),
    [
        ("empty", "is empty"),
        ("too long", "longer than 500 characters"),
        ("no letter", "holds no letter"),
        ("invisible or mark character", "invisible or combining character"),
        ("mixed scripts", "Latin letters with Cyrillic, Greek, Armenian, Coptic or Cherokee"),
    ],
)
def test_an_unreadable_question_gets_one_sentence_naming_its_reason(reason, named):
    assert reason in UNREADABLE_REASONS
    body = body_of("golden", {}, U("unreadable", reason=reason))
    assert len(body) == 1 and named in body[0]


def test_a_refusal_is_not_made_of_an_answer():
    with pytest.raises(ValueError, match="refusal"):
        body_of("golden", {}, U("answer", "summary"))


# ---------------------------------------------------------------- the pointers, from the report


def test_shipping_points_to_the_blocking_rules_by_id_and_title(raw_spec):
    golden = body_of("golden", raw_spec, refusal("ship_decision"))
    assert golden == [
        PARAGRAPHS["ship_decision"],
        "The blocking rules of the report, by ID and title:",
        sentence_line("RES-001.title"),
        sentence_line("RES-002.title"),
    ]
    clear = body_of("clear", raw_spec, refusal("ship_decision"))
    assert clear[1:] == ["The report names no blocking rule; that is not a recommendation to ship."]


def test_stopping_points_to_the_days_and_to_the_rules_about_the_length_and_size(raw_spec):
    golden = body_of("golden", raw_spec, refusal("stopping"))
    assert golden[1:] == [
        "Days observed: 21; days planned: 21.",
        "Raised in this report, about the length and size of the run:",
        sentence_line("RES-002.title"),
        *quiet_lines(["RES-003"]),  # a rule that raised nothing is its quiet line
    ]
    assert golden[-2] == "RES-003 ran and raised no finding."
    short_run = body_of("short_run", raw_spec, refusal("stopping"))
    rep, _, _ = world("short_run", raw_spec)
    assert short_run[1] == "Days observed: 5; days planned: 14."
    assert short_run[3] == sentence_line("RES-003.title")  # RES-003 first, as the table says
    assert rep["population"]["observed_days"] == 5
    clear = body_of("clear", raw_spec, refusal("stopping"))
    assert clear[2:] == quiet_lines(["RES-003", "RES-002"])


def test_reassurance_names_the_finding_with_its_facts_or_the_quiet_line(raw_spec):
    rep, facts, _ = world("golden", raw_spec)
    named = body_of("golden", raw_spec, refusal("reassurance", target="RES-001"))
    assert named == [
        PARAGRAPHS["reassurance"],
        "The finding the question names, as the report holds it (blocker):",
        sentence_line("RES-001.title"),
        *fact_lines(facts.findings[0], facts.aliases),
        "These are the report's values for it; they are not agreement that it is fine.",
    ]
    assert len(named) > 10  # its facts are on the page
    quiet = body_of("golden", raw_spec, refusal("reassurance", target="RES-003"))
    assert quiet[1:] == [
        "The question names a rule that raised nothing in this report:",
        *quiet_lines(["RES-003"]),
    ]
    unnamed = body_of("golden", raw_spec, refusal("reassurance"))
    title = catalogue_sentences()["RES-007.title"]
    assert unnamed[1] == f"{NO_SINGLE_RULE} The findings of the report, with their severity:"
    assert unnamed[2:] == [
        f"  {f['rule_id']} {f['severity']}: {catalogue_sentences()[f['rule_id'] + '.title']}"
        for f in rep["findings"]
    ]
    assert f"  RES-007 warning: {title}" in unnamed
    clear = body_of("clear", raw_spec, refusal("reassurance"))
    assert clear[1:] == [NO_SINGLE_RULE, *quiet_lines(rep_rules(raw_spec))]
    assert "single rule of the nine results rules" in NO_SINGLE_RULE  # two rules, or one not built


def rep_rules(raw_spec):
    return world("clear", raw_spec)[0]["rules_run"]


def test_the_effect_is_pointed_to_by_its_label_and_never_by_a_number(raw_spec):
    rep, _, _ = world("golden", raw_spec)
    reality = body_of("golden", raw_spec, refusal("effect_reality"))
    numbers = body_of("golden", raw_spec, refusal("effect_numbers"))
    assert "NOT TO BE READ, blocked by RES-001; UNDERPOWERED" in reality[1]
    assert reality[2] == NOT_THE_VERDICT  # clear does not say that the effect is real
    assert "clear" in NOT_THE_VERDICT and "does not say the effect is real" in NOT_THE_VERDICT
    assert numbers[1] == WHERE_THE_TABLE_IS
    assert "memo, under 'Observed facts'" in numbers[1] and "JSON" in numbers[1]
    assert numbers[2] == reality[1]
    clear = body_of("clear", raw_spec, refusal("effect_reality"))
    assert clear[1] == "The report labels its effect table: can be read."
    two = {**rep, "effect": {**rep["effect"], "unreadable_because": ["RES-001", "RES-003"]}}
    label = refusal_body(two, world("golden", raw_spec)[1], refusal("effect_reality"))[1]
    assert "blocked by RES-001, RES-003;" in label  # more than one rule blocks the effect
    # no figure of the effect table is on a page
    figures = {
        str(v) for arm in rep["effect"]["arms"] for v in arm.values() if isinstance(v, float)
    }
    assert figures and not any(f in "\n".join(numbers + reality) for f in figures)


@pytest.mark.parametrize("category", ["other_analysis", "data_access", "subgroup"])
def test_the_fixed_pointers_say_what_the_report_holds(category, raw_spec):
    body = "\n".join(body_of("golden", raw_spec, refusal(category)))
    expected = {
        "other_analysis": ("'Not yet' in docs/rules.md",),
        # the page also prints counts by arm, so it prints no player id and no more
        "data_access": ("ids of the players assigned before it", "this layer prints no player id."),
        # the report also divides players by week, first-seen date and late exposure: say less
        "subgroup": (
            "no breakdown by country, platform or device",
            "The report counts players by arm; its cohort test divides them by cohort of first",
        ),
    }
    assert all(keyword in body for keyword in expected[category])


# ---------------------------------------------------------------- the claims are the report's


def test_every_claim_a_refusal_makes_about_the_report_names_a_key_the_golden_holds(raw_spec):
    rep, _, _ = world("golden", raw_spec)
    for category, paths in CLAIMS.items():
        assert category in CATEGORIES
        for path in paths:
            assert value(rep, path) is not None, (category, path)
    # and the key holds what the claim says it does
    assert set(value(rep, ASSIGNED)) == set(value(rep, ANALYSED))  # counts by arm
    assert all(isinstance(n, int) for n in value(rep, ASSIGNED).values())
    assert value(rep, IGNORED) == []  # the ids of the players before a start: it was not registered
    assert all(isinstance(row, dict) and "arm" in row for row in value(rep, EFFECT_TABLE))
    assert isinstance(value(rep, READABLE), bool) and isinstance(value(rep, UNDERPOWERED), bool)
    assert set(value(rep, UNREADABLE_BECAUSE)) <= set(RULE_IDS)
    assert set(value(rep, BLOCKING)) <= set(RULE_IDS)
    assert {f["rule_id"] for f in value(rep, FINDINGS)} <= set(RULE_IDS)
    assert set(value(rep, RULES_RUN)) == set(RULE_IDS)
    assert isinstance(value(rep, DAYS_OBSERVED), int) and isinstance(value(rep, DAYS_PLANNED), int)


def test_a_pointer_reads_only_the_keys_that_the_claims_of_its_category_rest_on(
    raw_spec, monkeypatch
):
    """And every refusal can be written, as a page, for each of the eight reports of 24.11."""
    read = set()

    def recorder(report, path):
        read.add(path)
        return value(report, path)

    monkeypatch.setattr(refusals, "value", recorder)
    others = [U("unreadable", reason=r) for r in UNREADABLE_REASONS] + [refusal()]
    others.append(U("refusal", "checked", None, tuple(CATEGORIES)))
    for name in NAMES:
        rep, facts, decision = world(name, raw_spec)
        for category in CATEGORIES:
            for target in (None, "RES-003", "RES-001"):
                read.clear()
                body = refusal_body(rep, facts, refusal(category, target=target))
                assert read <= set(CLAIMS.get(category, ())), (name, category, target, read)
                page = render_refusal(rep, refusal(category, target=target), decision, body)
                assert page.endswith("\n") and "None" not in page, (name, category, target)
        for understanding in others:
            body = refusal_body(rep, facts, understanding)
            page = render_refusal(rep, understanding, decision, body)
            assert body and page.endswith("\n") and "None" not in page, (name, understanding)


# ---------------------------------------------------------------- quoted sentences


def test_the_quoted_sentences_are_the_catalogues_and_a_rule_edit_that_moves_them_fails():
    sentences = catalogue_sentences()
    for category, quotes in QUOTES.items():
        assert category in CATEGORIES
        for lead, sentence_id, first_words in quotes:
            assert sentences[sentence_id].split()[:5] == first_words.split()
            assert lead.endswith(":") and "for when" in lead  # conditional: the rule may be quiet
    assert {c: [q[1] for q in qs] for c, qs in QUOTES.items()} == {
        "causal": ["RES-007.why.3"],
        "forecast": ["RES-007.why.2", "RES-008.why.4"],
        "subgroup": ["RES-007.why.2"],
    }


@pytest.mark.parametrize("name", ["golden", "clear"])  # RES-007 raises a finding, or is quiet
def test_a_sentence_is_quoted_after_its_lead_even_when_the_rule_is_quiet(name, raw_spec):
    for category, quotes in QUOTES.items():
        body = body_of(name, raw_spec, refusal(category))
        for lead, sentence_id, _ in quotes:
            at = body.index(lead)
            assert body[at + 1] == sentence_line(sentence_id)


def test_a_compound_refusal_prints_every_category_in_order_up_to_three_and_names_the_rest(raw_spec):
    categories = ("injection", "ship_decision", "causal", "forecast", "rewording")
    body = body_of("golden", raw_spec, U("refusal", "summary", None, categories))
    assert [line for line in body if line in PARAGRAPHS.values()] == [
        PARAGRAPHS[c] for c in categories[:3]
    ]
    assert (
        body[body.index(PARAGRAPHS["causal"]) + 1] == QUOTES["causal"][0][0]
    )  # its quote is there
    assert sentence_line("RES-007.why.3") in body
    assert sentence_line("RES-008.why.4") not in body  # forecast is named, not printed
    assert f"{ALSO_MATCHED} forecast, rewording." in body
    assert body[-1] == ANSWERABLE_PART  # and an answerable part was not answered
    assert body.count("") == 4  # a blank line between the five blocks
    quotes = body_of("golden", raw_spec, refusal("causal", "forecast", "subgroup"))
    for _, sentence_id, _ in [q for qs in QUOTES.values() for q in qs]:
        assert sentence_line(sentence_id) in quotes
    # no answerable part, no such sentence; no category beyond the third, no line to name them
    assert ANSWERABLE_PART not in quotes and ALSO_MATCHED not in " ".join(quotes)


@pytest.mark.parametrize("name", ["golden", "clear", "warnings_only"])
def test_the_second_public_question_prints_both_refusals_and_the_cohort_sentence(name, raw_spec):
    page = page_of(name, raw_spec, PUBLIC[1])
    assert page.index(PARAGRAPHS["ship_decision"]) < page.index(PARAGRAPHS["subgroup"])
    assert sentence_line("RES-007.why.2") in page.splitlines()


# ---------------------------------------------------------------- quiet rules in a refusal


@pytest.mark.parametrize("name", ["golden", "clear", "warnings_only", "harm_blocker"])
def test_no_refusal_says_that_a_rule_raised_nothing_without_the_disclaimer_or_bare(name, raw_spec):
    extra = ["Is everything fine, right?", "Is RES-004 fine, right?", "Can we call it on day 3?"]
    for question in [*PUBLIC, *extra]:
        lines = page_of(name, raw_spec, question).splitlines()
        for at, line in enumerate(lines):
            if "raised no finding" in line:
                block = lines[at:]
                block = block[: block.index("")] if "" in block else block
                assert any(DISCLAIMER in text for text in block), (name, question, line)
                if line.split()[0] in ("RES-004", "RES-007", "RES-008"):
                    assert "summary_lines" in line  # never bare
