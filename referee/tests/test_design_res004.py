"""Design section 21.12 (RES-004) against the code.

The figures of the section are in sentences made here from the code's constants, so that the
text cannot say a number the code does not use. The design text is written around those
sentences (`_sentences`); a test checks that each is in it exactly once and that the section
holds no figure outside them (`design_figures`), and another that the claims it makes in its own
words are there.
"""

from pathlib import Path

from design_figures import figures_outside

from referee import methods
from referee.guardrails import (
    ALPHA,
    CHANCE_LEVEL,
    CONFIDENCE,
    DIGITS,
    REFERENCES,
    SMALL_COUNT,
    TIERS,
)
from referee.rules import RESULTS_RULES

DOCS = Path(__file__).resolve().parent.parent / "docs"
DESIGN = (DOCS / "design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
RES_004 = next(rule for rule in RESULTS_RULES if rule.id == "RES-004")


def _sentences() -> dict[str, str]:
    """The sentences of section 21.12 that carry figures or decisions, made from the code."""
    severity, escalation = RES_004.severity, RES_004.escalation.to
    return {
        "interval": f"the {CONFIDENCE:.0%} interval for the harm",
        "tiers": (
            f"A breach is shown when the whole {CONFIDENCE:.0%} interval for the harm is "
            "beyond the tolerance, and possible when only the point estimate is"
        ),
        "rounding": (
            f"The harm and its interval are rounded to {DIGITS} places, and the decision is "
            "made on the rounded figures that the evidence shows"
        ),
        "small": (
            f"A binary guardrail with fewer than {SMALL_COUNT} players on one side of its "
            "rate, in the arm or in control, is marked as rough"
        ),
        "alpha": f"each interval is a two-sided {CONFIDENCE:.0%} interval (alpha {ALPHA})",
        "chance": f"a reading is held when that chance is not below {CHANCE_LEVEL:.1%}",
        "severity": (
            f"RES-004 is a {severity}, escalating to a {escalation} when a breach is shown in "
            "at least one comparison"
        ),
        "strengths": f"A shown breach is a {escalation} and a possible one a {severity}",
        "references": (
            f"The tolerance is measured against {len(REFERENCES)} references and the stricter "
            "decides"
        ),
    }


def _section() -> str:
    parts = DESIGN.split("\n### 21.12 ")
    assert len(parts) == 2, "section 21.12 is not there exactly once"
    text = parts[1].split("\n### 21.13 ")[0].split("\nDelivered in:")[0]
    assert DESIGN.index("### 21.11 ") < DESIGN.index("### 21.12 ")
    return text


def _figures_outside(text: str, phrases: list[str]) -> list[str]:
    names = ("4b-2", "4c", "RES-004", "res004", "RES-006", "RES-008", "DES-009", "section 8")
    return figures_outside(text, phrases, names=names, last_section=13)


def test_the_design_text_holds_every_sentence_of_the_section_and_no_other_figure() -> None:
    section = " ".join(_section().split())

    for label, phrase in _sentences().items():
        assert section.count(phrase) == 1, (label, phrase)
    assert _figures_outside(section, list(_sentences().values())) == []


def test_the_constants_are_the_ones_the_section_names() -> None:
    assert (CONFIDENCE, ALPHA, DIGITS, SMALL_COUNT) == (0.95, 0.05, 6, 10)
    assert TIERS == ("within", "possible", "shown")


CLAIMS = [  # what the section says in its own words about the decisions
    "Decided by the user (4b-2)",
    "in two strengths: a breach is shown",
    "The note says when they disagree",
    "a value exactly at the tolerance is not a breach",
    "a point estimate within the tolerance is not a finding",
    "the data cannot rule out a breach",
    "the ratio of the means of the arm and of control, with an interval from the log scale",
    "the arm's own mean with a t interval, or its rate with a Wilson interval",
    "the registered baseline is taken as a constant",
    "`baseline_std` is not used",
    "Control's own place against the registered baseline is in the evidence",
    "a breach against the baseline alone does not show that the arm caused it",
    "Severity (judgement)",
    "This departs from the seed list's blocker",
    "makes the results verdict `invalid`",
    "The intervals are unadjusted",
    "are not the rates of these intervals",
    "It is believed only when chance cannot explain it",
    "players of a revenue arm all at zero",
    "a rise is not held",
    "The price of the hold is power",
    "Counts (sessions, purchases) are not held",
    "taken from the metric's name without looking at the values",
    "thousands at zero are shown",
    "players at a value that nobody in control has are shown at any size",
    "The same test is made for the ratio against control's mean when one of its groups has no "
    "variation",
    "when a fall is harmful and the group has some spread",
    "Where control's own reading was held, the note says so.",
    "and more of its players are at zero than chance explains",
    "unless the reading against control's mean shows the breach too",
    "drawn independently from the other group's distribution",
    "and the rest of those draws are warnings",
    "Groups that are nearly but not exactly alike",
    "can only make a breach possible",
    "an interval with no width",
    "the registered-baseline reading of a revenue-like guardrail",
    "the reading against control's mean is not held",
    "assigned, exposed, and not first exposed after their first purchase",
    "cannot be exceeded",
    "Judgement and not done",
    "no sequential looks",
]


def test_the_section_says_what_was_decided_and_what_is_judgement_in_these_words() -> None:
    section = " ".join(_section().split())

    for claim in CLAIMS:
        assert section.count(claim) == 1, claim
    assert section.count("judgement") >= 3


def test_the_section_names_the_functions_and_the_simulation_that_it_relies_on() -> None:
    section = _section()

    for name in ("mean_ratio", "mean_interval", "proportion_interval"):
        assert f"`methods.{name}`" in section and hasattr(methods, name), name
    assert "`tests/test_guardrails_calibration.py`" in section
    assert (Path(__file__).parent / "test_guardrails_calibration.py").is_file()


def test_the_rule_texts_state_the_decisions_of_the_section() -> None:
    fires, why, escalates = (
        " ".join(text.split())
        for text in (RES_004.fires_when, RES_004.why_it_matters, RES_004.escalation.when)
    )

    assert "The breach is shown when the whole 95% interval is beyond it" in fires
    assert "possible when only the point estimate is" in fires
    assert "strictly" in fires
    assert f"rounded to {DIGITS} places" in fires
    assert "The intervals are unadjusted" in why
    assert "Two kinds of reading can only make a breach possible" in fires
    for text in (fires, escalates):
        assert "an interval with no width" in text
        assert (
            "the registered-baseline reading of a revenue-like guardrail whose fall is harmful"
            in text
        )
