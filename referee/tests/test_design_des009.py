"""Design section 21.13 (DES-009 and the DES-003 note for new users) against the code.

The figures of the section are in sentences made here from the code's constants, so that the
text cannot say a number the code does not use. The design text is written around those
sentences (`_sentences`); a test checks that each is in it exactly once and that the section
holds no figure outside them, and another that the claims it makes in its own words are there.
"""

import re
from pathlib import Path

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
    least = cohorts.MIN_COHORTS * cohorts.WEEK_DAYS
    return {
        "severity": f"DES-009 is an {DES_009.severity} rule",
        # the first build's threshold, quoted as history and not as a constant of the code
        "first": "one threshold, 45 players per arm and week",
        "floor_only": f"counted only the floor of {cohorts.FLOOR} players",
        "weeks": (
            f"the window holds fewer than {cohorts.MIN_COHORTS} whole weekly blocks (a plan of "
            f"{least - 1} days or less)"
        ),
        "floor": f"the floor of {cohorts.FLOOR} players an arm and block",
        "knee": f"raised once the arms differ by more than {cohorts.RATIO_FLOOR_KNEE} to 1",
        "median": (
            f"a median of {cohorts.WEEKLY_MEDIAN_MINIMUM} players in the smaller arm on weekly "
            "blocks"
        ),
        "fallback": (
            f"blocks of {cohorts.FALLBACK_BLOCK_DAYS} days on a plan of "
            f"{cohorts.FALLBACK_MIN_PLAN_DAYS} days or more"
        ),
        "ratio": f"arms more than {cohorts.MAX_ALLOCATION_RATIO:.0f} to 1 apart",
        "note": (
            f"{cohorts.MIN_COHORTS} weekly cohorts of new players need {least} days of accrual, "
            f"and {des.WEEKLY_COHORTS_FOR_NEW_USERS} weekly cohorts, "
            f"{des.WEEKLY_COHORTS_FOR_NEW_USERS * des.DAYS_PER_WEEK} days, if the export is taken "
            f"when accrual ends; the outcome window of {des.OUTCOME_WINDOW_DAYS} days follows "
            "each player's assignment"
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


def test_the_design_text_holds_every_sentence_of_the_section_and_no_other_figure() -> None:
    section = " ".join(_section().split())

    for label, phrase in _sentences().items():
        assert section.count(phrase) == 1, (label, phrase)
    assert _figures_outside(section, list(_sentences().values())) == []


CLAIMS = [  # what the section says in its own words about the decisions
    "a forecast from the plan alone and not a finding about data",
    "even if players arrived perfectly evenly",
    "What changed from 21.8 as first written (judgement)",
    "a review of the first build showed that the single figure was wrong",
    "applies the gates of RES-007 itself",
    "a test pins the two to each other at both sides of each gate",
    "the least for even arrivals and not enough",
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
