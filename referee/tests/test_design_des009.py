"""Design section 21.13 (DES-009 and the DES-003 note for new users) against the code.

The figures of the section are in sentences made here from the code's constants, so that the
text cannot say a number the code does not use. The design text is written around those
sentences (`_sentences`); a test checks that each is in it exactly once and that the section
holds no figure outside them, and another that the claims it makes in its own words are there.
"""

import re
from pathlib import Path

import pytest

from referee import cohorts
from referee.rules import ALL_RULES
from referee.rules import design as des

DOCS = Path(__file__).resolve().parent.parent / "docs"
DESIGN = (DOCS / "design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
DES_009 = next(rule for rule in ALL_RULES if rule.id == "DES-009")


def _sentences() -> dict[str, str]:
    """The sentences of section 21.13 that carry figures, made from the code."""
    needed = des.MIN_COHORTS * des.DAYS_PER_WEEK
    return {
        "severity": f"DES-009 is an {DES_009.severity} rule",
        "weeks": (
            f"the planned window holds fewer than {des.MIN_COHORTS} whole weekly blocks (a plan of "
            f"{needed - 1} days or less)"
        ),
        "players": (
            f"the smallest arm is expected to get fewer than {des.EXPECTED_PLAYERS_PER_BLOCK} "
            "players in a block"
        ),
        "block": (
            f"a block is {des.DAYS_PER_WEEK} days, or {des.FALLBACK_BLOCK_DAYS} days on a plan of "
            f"{des.FALLBACK_MIN_PLAN_DAYS} days or more"
        ),
        "floor": f"half as many again as the floor of {cohorts.FLOOR} players",
        "median": f"a median of {cohorts.WEEKLY_MEDIAN_MINIMUM} players",
        "enough": f"{needed} days for the first reason",
        "note": (
            f"{des.WEEKLY_COHORTS_FOR_NEW_USERS} weekly cohorts of new players need "
            f"{des.WEEKLY_COHORTS_FOR_NEW_USERS * des.DAYS_PER_WEEK} days of accrual, and the "
            f"outcome window of {des.OUTCOME_WINDOW_DAYS} days follows each player's assignment"
        ),
    }


def _section() -> str:
    parts = DESIGN.split("\n### 21.13 ")
    assert len(parts) == 2, "section 21.13 is not there exactly once"
    text = parts[1].split("\nDelivered in:")[0]
    assert DESIGN.index("### 21.12 ") < DESIGN.index("### 21.13 ")
    return text


def _figures_outside(text: str, phrases: list[str]) -> list[str]:
    """The figures left in the text once each sentence has been taken out of it, once."""
    for phrase in sorted(phrases, key=len, reverse=True):
        assert text.count(phrase) == 1, phrase
        text = text.replace(phrase, " ", 1)
    for name in ("4b-2", "4c", "des009", "window_holds_fewer_than_3_blocks"):
        text = text.replace(name, " ")
    text = re.sub(r"\b[A-Z]{3}-\d{3}\b", " ", text)  # a rule id
    text = re.sub(r"(?<![\d.])21\.(?:[1-9]|1[0-3])(?![\d%])", " ", text)  # a section reference
    return re.findall(r"\d[\d,.]*%?|\b(?:third|half|quarter|twice|double)\b", text)


def test_the_design_text_holds_every_sentence_of_the_section() -> None:
    section = " ".join(_section().split())

    for label, phrase in _sentences().items():
        assert section.count(phrase) == 1, (label, phrase)


def test_the_design_text_has_no_figure_outside_those_sentences() -> None:
    section = " ".join(_section().split())

    assert _figures_outside(section, list(_sentences().values())) == []


def test_the_check_for_figures_finds_a_figure_that_is_there() -> None:
    sentences = ["a block of 7 days", "45 players"]
    text = f"A: {sentences[0]}. See 21.3, 21.13 and 4b-2 (DES-009). B: {sentences[1]}."

    assert _figures_outside(text, sentences) == []
    for extra, found in [
        (" It fires at 21 days.", ["21"]),
        (" See 21.14 now.", ["21.14"]),
        (" At half of it.", ["half"]),
    ]:
        assert _figures_outside(text + extra, sentences) == found, extra
    with pytest.raises(AssertionError):
        _figures_outside(text, [*sentences, "not in the text"])


def test_the_sentences_follow_the_constants_of_the_code(monkeypatch) -> None:
    import sys

    module = sys.modules[__name__]
    before = _sentences()
    monkeypatch.setattr(des, "EXPECTED_PLAYERS_PER_BLOCK", 44)

    after = _sentences()

    assert after["players"] != before["players"] and set(after) == set(before)
    assert module.des is des


def test_the_constants_are_the_ones_the_section_names() -> None:
    assert (des.MIN_COHORTS, des.EXPECTED_PLAYERS_PER_BLOCK, des.DAYS_PER_WEEK) == (3, 45, 7)
    assert (des.FALLBACK_BLOCK_DAYS, des.FALLBACK_MIN_PLAN_DAYS) == (14, 42)
    assert (cohorts.FLOOR, cohorts.WEEKLY_MEDIAN_MINIMUM) == (30, 60)
    assert des.EXPECTED_PLAYERS_PER_BLOCK == 1.5 * cohorts.FLOOR
    assert DES_009.severity == "info"


CLAIMS = [  # what the section says in its own words about the decisions
    "a forecast from the plan alone and not a finding about data",
    "the cohort check of the results review",
    "the reason code `window_holds_fewer_than_3_blocks`",
    "The block (judgement, a change from 21.8 as first written)",
    '21.8 first wrote "per arm and week"',
    "the smallest allocation of the spec limits every pair that includes it",
    "a weekly plan expecting between the figure and the median may still not be evaluated",
    "The share of eligible units who are exposed",
    "The DES-003 text for new users",
    "The note is evidence, not rule text",
    "A declaration cannot be checked and does not lower any warning",
    "the clean spec of the tests plans three whole weeks",
]


def test_the_section_says_what_was_decided_and_what_is_judgement_in_these_words() -> None:
    section = " ".join(_section().split())

    for claim in CLAIMS:
        assert section.count(claim) == 1, claim
    assert section.count("judgement") >= 2


def test_the_rule_texts_say_what_the_section_says() -> None:
    text = " ".join((DES_009.fires_when + " " + DES_009.why_it_matters).split())

    assert "fewer than 3 whole weekly blocks" in text
    assert "fewer than 45 players in a block" in text
    assert "14 times that for a plan of 42 days or more" in text
    assert "a forecast from the plan, not a finding about the data" in text
