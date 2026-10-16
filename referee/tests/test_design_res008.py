"""Design section 21.11 (RES-008 and the figure RES-007 prints) against the code and the studies.

Every figure of the section is in a sentence made here from the code's constants and the saved
studies, so the text cannot say a number the code does not use. The design text is written
around those sentences (`_sentences`); a test checks that each is in it exactly once and that
the section holds no figure outside them.
"""

import json
import random
from fractions import Fraction
from pathlib import Path

import pytest
from cohort_simulation import BASE as COHORT_BASE
from design_figures import figures_outside
from pooled_rates_table import LARGE_EFFECTS, SMALL_EFFECTS
from test_sign_of_the_difference import FEW, PAYING, SD
from test_sign_of_the_difference import _runs as sign_runs

from referee.cohort_effects import (
    BASELINE_LEVEL,
    FADE_COHORTS,
    FADE_FAMILIES,
    FADE_FLAG_RATES,
    FADE_FLAG_RATES_ADDED,
    FADE_MAX_ALLOCATION_RATIO,
    FADE_SIZES,
    POWER,
)
from referee.heavy_tails import (
    DIGITS,
    EQUAL_ARMS_SPLIT,
    FAR_APART_PAYERS,
    FAR_APART_SPLIT,
    KOHAVI_MULTIPLE,
    KURTOSIS_OVER,
    LARGE_EFFECT_FROM,
    SKEWNESS_OVER,
    TOP_PERCENT,
    TOP_SHARE_OVER,
)
from referee.methods import heavy_tail_measures
from referee.pooled_rates import CASES, EXCESS_RATE, NOMINAL_RATE, UNIT, hull, lookup, percent

DOCS = Path(__file__).resolve().parent.parent / "docs"
DESIGN = (DOCS / "design/2026-09-28-referee-experiment-review-design.md").read_text(
    encoding="utf-8"
)
POOLED = json.loads((DOCS / "simulations/pooled_effect_heavy.json").read_text(encoding="utf-8"))
REVENUE_LIKE = ("revenue_mild", "revenue", "revenue_heavy")
CELLS = [cell for cell in POOLED["cells"] if cell["outcome"] in REVENUE_LIKE]


def _pct(rate: float) -> str:
    return percent(round(rate * UNIT))


def _span(low: float, high: float) -> str:
    return f"{_pct(low)} to {_pct(high)}"


def _overall(by_size: dict) -> tuple[float, float]:
    return min(lo for lo, _ in by_size.values()), max(hi for _, hi in by_size.values())


def smallest_group_that_can_show_the_kurtosis_level() -> int:
    """The fewest players in a group whose excess kurtosis can exceed the level: one value
    that differs from all the others is the most skewed a sample of that size can be."""
    n = 2
    while heavy_tail_measures([1.0] + [0.0] * (n - 1)).excess_kurtosis <= KURTOSIS_OVER:
        n += 1
    return n


def _ratio(value: Fraction) -> str:
    return f"{float(value):g}"


def _effects(values: tuple[float, ...]) -> str:
    """Effects as the text writes them: none, or a rise of so many per cent."""
    return " and ".join("none" if v == 0 else f"+{v:.0%}" for v in values)


def _mapping() -> str:
    """Which simulated kind stands for which metric, from the code's table."""
    kinds = {
        "revenue_like": "the revenue-like outcomes",
        "binary": "the binary outcome",
        "poisson": "the Poisson outcome",
    }
    parts = [
        f"`{metric}` for {' and '.join(kinds[family] for family in families)}"
        for metric, families in FADE_FAMILIES.items()
    ]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _words(number: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four"}[number]


def _sign_sentence() -> str:
    """What the seeded check of `test_sign_of_the_difference.py` found, worked out again."""
    wrong_sign, excludes_zero, _ = sign_runs(smaller=FEW, sd=SD)
    return (
        f"a seeded check ({PAYING:.0%} of players spend, the arm the smaller group at 3 to 1 "
        f"with +20%, {FEW} players in the smaller group, about {round(FEW * PAYING)} of them "
        "who spend; `tests/test_sign_of_the_difference.py`) found the group with the higher "
        f"mean seen to be the one with the lower true mean in {wrong_sign.mean():.0%} of runs, "
        f"and in {wrong_sign[excludes_zero].mean():.0%} of the {excludes_zero.sum()} runs in "
        "which Welch's interval excluded 0 (one seed: read them as large, not as exact)"
    )


def _unequal_sentence() -> str:
    """How often the range over both orders reaches above the level, on the table's grid."""
    points = above = 0
    for effects in ("small", "large"):
        grid = {(c.split, c.payers) for c in CASES if c.effects == effects and c.larger != "equal"}
        for split, payers in sorted(grid):
            both = hull(
                lookup(effects, "arm", split, payers), lookup(effects, "control", split, payers)
            )
            points += 1
            above += both.high > EXCESS_RATE
    return (
        f"the range over both orders reaches above {_pct(EXCESS_RATE / UNIT)} at {above} of the "
        f"{points} combinations of split and players who spend that the table holds for groups "
        "of unequal size"
    )


def _equal_sentence() -> str:
    small = max(c.high for c in CASES if c.effects == "small" and c.larger == "equal")
    large = min(c.high for c in CASES if c.effects == "large" and c.larger == "equal")
    return (
        f"the highest rate of any case for equal groups is {_pct(small / UNIT)} with none and "
        f"+20%, and at least {_pct(large / UNIT)} with +50% and +100%"
    )


def _sparse_sentence() -> str:
    rows = [c for c in CASES if c.effects == "large"]
    counts = len({c.payers for c in rows})
    splits = len({c.split for c in rows})
    return (
        "the grid for `large` effects is sparse "
        f"({_words(counts)} numbers of players who spend, {_words(splits)} splits)"
    )


def _sentences() -> dict[str, str]:
    """The sentences of section 21.11 that carry figures, made from the code and the studies."""
    ladder = sum(cell["effect"] in (0.5, 1.0) for cell in CELLS)
    fewest = smallest_group_that_can_show_the_kurtosis_level()
    revenue, binary, poisson = (
        _overall(FADE_FLAG_RATES[kind]) for kind in ("revenue_like", "binary", "poisson")
    )
    added = _overall(FADE_FLAG_RATES_ADDED["revenue_like"])
    sizes = ", ".join(f"{size:,}" for size in FADE_SIZES[:-1]) + f" and {FADE_SIZES[-1]:,}"
    binary_rate = f"{COHORT_BASE['binary']:.0%}"
    return {
        "signs": (
            f"(K) a sample skewness above {SKEWNESS_OVER} in size in a group of fewer than "
            f"{KOHAVI_MULTIPLE} times the square of that skewness in players, the rule of thumb "
            "of Kohavi, Deng, Longbotham and Xu (2014); (E) an excess kurtosis above "
            f"{KURTOSIS_OVER}; (T) the top {TOP_PERCENT}% of the group's players holding more "
            f"than {TOP_SHARE_OVER:.0%} of the total"
        ),
        "rounding": (
            f"The skewness, kurtosis and share are rounded to {DIGITS} places, and the decision "
            "is made on the rounded figures that the evidence shows."
        ),
        "inert": (
            f"K or E fired in every replication of every one of the {len(CELLS)} revenue-like "
            "cells of the pooled study (T can only add to them), so that study cannot place the "
            f"levels {KURTOSIS_OVER} and {TOP_SHARE_OVER:.0%}, which are judgement, and E cannot "
            f"fire in a group of fewer than {fewest} players, since the most a group of "
            f"{fewest - 1} players can show is below {KURTOSIS_OVER}"
        ),
        "kohavi": (
            "Kohavi et al. built their rule to keep the total error of a 95% interval for one "
            "mean within 4% to 6% at the size it asks for, and they say that when the two groups "
            "have the same distribution and equal sizes it gives no useful bound; the finding "
            f"says so for groups within {_ratio(EQUAL_ARMS_SPLIT)} to 1 of each other in size, "
            "with the rates the study found"
        ),
        "effects": (f"(`small`: {_effects(SMALL_EFFECTS)}; `large`: {_effects(LARGE_EFFECTS)})"),
        "interval": f"Welch's {1 - POOLED['alpha']:.0%} interval",
        "power": (
            f"the {POWER:.0%} is the power calculation's claim, which takes the standard errors "
            "as known and the spread of the arm as unchanged by the effect"
        ),
        "capping": (
            "Kohavi et al. report, in a paper that Referee's author read in a saved extract, "
            "that capping revenue per user cut its skewness from about 18 to about 5"
        ),
        "equalish": f'groups "about equal in size" (up to {_ratio(EQUAL_ARMS_SPLIT)} to 1)',
        "table": (
            f"{len(CASES)} cases from the {len(CELLS)} revenue-like cells of the study ("
            f"the {ladder} of the ladder, +50% and +100%, included)"
        ),
        "severity": (
            "The default severity is info, with an escalation to warning when the range for "
            "the effects nearer the difference seen reaches above "
            f"{_pct(EXCESS_RATE / UNIT)} (1.5 times the "
            f"{_pct(NOMINAL_RATE / UNIT)[:-3]}% an interval of this level should fail in) or "
            "that comparison is beyond the simulated cases in a direction in which the rates "
            "rose"
        ),
        "nearer": (
            "The effects are nearer +50% and +100% from a difference seen of "
            f"{LARGE_EFFECT_FROM:.0%} (the higher mean over the lower one, which is how the "
            "simulations measure an effect), halfway from +20% to +50%, and nearer none and "
            "+20% below it"
        ),
        "far": (
            "The cases on the two sides of a comparison are far apart when their players who "
            f"spend differ by {FAR_APART_PAYERS} times or their splits by "
            f"{_ratio(FAR_APART_SPLIT)} times"
        ),
        "fade": (
            "the share of runs in which the trigger flagged a fade of exactly the size printed "
            f"(21.5), by the kind of metric, over {FADE_COHORTS[0]} and {FADE_COHORTS[1]} cohorts "
            f"and the three sizes of {sizes} players an arm in a cohort taken together: "
            f"revenue-like metrics {_span(*revenue)}, a binary metric at a rate of {binary_rate} "
            f"{_span(*binary)}, counts simulated as Poisson {_span(*poisson)}, and "
            f"{_span(*added)} for revenue-like metrics when the same amount is added to every "
            "player"
        ),
        "fade_size": (
            "A finding prints the range of the size nearest its own in logs, for example "
            f"{_span(*FADE_FLAG_RATES['revenue_like'][FADE_SIZES[0]])} for revenue-like metrics "
            f"at {FADE_SIZES[0]} players an arm in a cohort"
        ),
        "guard": (
            "The rate is quoted only inside the design that was simulated: two arms of equal "
            f"size (up to {FADE_MAX_ALLOCATION_RATIO} to 1, a limit chosen and not simulated), "
            f"{FADE_COHORTS[0]} or {FADE_COHORTS[1]} cohorts, {sizes.replace(' and ', ' or ')} "
            "players an arm in a cohort and a control baseline that does not move (the p value "
            "of the test that the control's mean is the same in every cohort is "
            f"{BASELINE_LEVEL} or more, or cannot be worked out)"
        ),
        "orientation": (
            f"Groups about equal in size (up to {_ratio(EQUAL_ARMS_SPLIT)} to 1) are placed "
            "among the cases of groups of the same size; for other groups the range is the "
            "lowest and the highest of the ranges for the arm the larger group and for control "
            "the larger group, because the sample cannot be relied on to show which group has "
            "the higher mean (the arm, in the simulated cases; with many players who spend it "
            "can, and the range is then wider than it needs to be); near 1.25 to 1 the rate "
            "can be higher than the equal cases show when the larger group is the one with the "
            "lower mean"
        ),
        "sign": _sign_sentence(),
        "unequal": _unequal_sentence(),
        "equal_highs": _equal_sentence(),
        "sparse": _sparse_sentence(),
        "mapping": _mapping(),
        "judge": (
            "The test of whether a design is inside the one simulated is a continuous range, so "
            f"a number of cohorts between {FADE_COHORTS[0]} and {FADE_COHORTS[1]} and a size "
            f"between {FADE_SIZES[0]:,} and {FADE_SIZES[-1]:,} players an arm count as inside "
            "although only the numbers and sizes named above were simulated; a control baseline "
            "moves when the p value of the test that its mean is the same in every cohort is "
            f"below {BASELINE_LEVEL}, and does not move when that p value cannot be worked out; "
            f"and the binary row is a rate of {binary_rate}, quoted without comparing it with "
            "the rate of the metric"
        ),
        "added": (
            f"{_span(*added)} for revenue-like metrics when the same amount is added to every "
            "player"
        ),
    }


def _section() -> str:
    parts = DESIGN.split("\n### 21.11 ")
    assert len(parts) == 2, "section 21.11 is not there exactly once"
    text = parts[1].split("\n### 21.12 ")[0].split("\nDelivered in:")[0]
    assert DESIGN.index("### 21.10 ") < DESIGN.index("### 21.11 ")
    return text


def _figures_outside(text: str, phrases: list[str]) -> list[str]:
    names = ("4b-2", "4c", "RES-007", "RES-008", "res008", "top-1%", "7d", "section 8")
    ordinal = r"(?<!\d)(5|95)th\b"  # of a percentile
    return figures_outside(text, phrases, names=names, patterns=(ordinal,), last_section=11)


def test_the_design_text_holds_every_sentence_of_the_section() -> None:
    section = " ".join(_section().split())

    for label, phrase in _sentences().items():
        if label != "added":  # a part of the sentence about the fade
            assert section.count(phrase) == 1, (label, phrase)


def test_the_design_text_has_no_figure_outside_those_sentences() -> None:
    phrases = [p for label, p in _sentences().items() if label != "added"]
    section = " ".join(_section().split())

    assert _figures_outside(section, phrases) == []


# --- The figures the sentences rest on ----------------------------------------------------------


def test_a_group_of_fewer_than_105_players_cannot_show_an_excess_kurtosis_above_100() -> None:
    assert smallest_group_that_can_show_the_kurtosis_level() == 105
    assert heavy_tail_measures([1.0] + [0.0] * 103).excess_kurtosis == pytest.approx(
        99.0097, abs=1e-4
    )
    rng = random.Random(3)
    for _ in range(3000):  # the most skewed sample of 104 values is one different from the rest
        values = [
            0.0 if rng.random() < rng.choice([0.5, 0.9, 0.99]) else rng.lognormvariate(0, 3)
            for _ in range(104)
        ]
        if len(set(values)) > 1 and sum(values) > 0:
            assert heavy_tail_measures(values).excess_kurtosis <= 99.0098


def test_the_pooled_study_has_the_revenue_like_cells_and_the_ladder_the_text_counts() -> None:
    assert len(CELLS) == 439 and sum(cell["effect"] in (0.5, 1.0) for cell in CELLS) == 40
    assert len(CASES) == 100


def test_the_rates_are_the_shares_of_the_saved_studies_whatever_the_rounding() -> None:
    sentences = _sentences()

    assert sentences["effects"] == "(`small`: none and +20%; `large`: +50% and +100%)"
    assert sentences["interval"] == "Welch's 95% interval" and "80%" in sentences["power"]
    assert "6.0% to 53.6%" in sentences["fade"] and "36.3% to 65.4%" in sentences["fade"]
    assert "70.4% to 77.1%" in sentences["fade"] and sentences["added"] == (
        "42.9% to 67.0% for revenue-like metrics when the same amount is added to every player"
    )
    assert "above 7.5% (1.5 times the 5% an interval" in sentences["severity"]


CLAIMS = [  # what the section says in its own words about the decisions
    "RES-008 fires at every split between the arms, equal arms included; it shows no bootstrap "
    "interval; and the size its rates are read by is the number of players who spend",
    "the smaller group being the one with fewer analysed players (of two of the same size, the "
    "one with fewer players who spend, then control)",
    "A pair with no sign and a group that could not be read is counted as not evaluated and "
    "does not fire the rule alone",
    "the range is called a floor",
    "only where the highest rates of the table rose in that direction",
    "The rule cannot see the true effect, so a range for each of the two sets of effects is "
    "always printed",
    "only where the highest rates of the table rose in that direction by more than a point",
    "The finding prints the difference seen (the arm less control) as a share of control's "
    "mean, and when the arm's mean is lower the effect in the terms of the simulations, and "
    "Welch's interval for it, before anything else",
    "the range for the nearer effects is put first, and it is the one the severity reads",
    "which the sample does not show, and the finding says none",
    "the verdict follows the data seen",
    "An info finding is listed and leaves the results verdict at `clear`",
    "adds the nearest case, or all the cases at the same nearest distance, beside the range, "
    "which still sets the severity",
    "the evidence says which with `read_as`, `equal` or `both_orders`, and the cells of a "
    "range read both ways round are counted once",
    "so a difference close to it can switch which range sets the severity, and the finding says so",
    "reading unequal groups in both orders instead of by the sign of the difference seen",
    "failed less often than the others in nearly every setting where both kinds of sample "
    "were common",
    "It also supersedes the plans in the first paragraph and the first bullet of 21.10",
    "Only for `revenue_usd_7d`",
    "no error rate was measured for it, because the Welch interval of a count metric was not "
    "simulated",
    "Severity (judgement, to be confirmed)",
    "This departs from the seed list's warning",
    "A quiet RES-008 is not a pass",
    'The sentence "a little optimistic" is gone: the rates replace it',
    "The step was not simulated",
    "A group is read on its own: with fewer than two players, every value zero, every value "
    "the same, a negative value, or values that are not finite or are too large or too small "
    "to measure",
    'gets its signs, called "skewed" when only K shows',
    "for specs that randomise and analyse one class of independent players (`player` or "
    "`user`, or `device` for both: the test of RES-007, shared)",
    "with `small` effects and groups of unequal size, most made the larger group look better "
    "than it is",
    "with `large` effects and groups of about equal size, most understated the gap between "
    "the groups",
    "the range includes the order in which the larger group has the lower mean, where the "
    "rates were highest",
    "Judgement and not shown. The levels of E and T; the severity and its level",
    "the mapping of metrics to simulated kinds; quoting no rate for a count metric",
    "Not shown: the rate among the runs in which a sign shows",
    "Referee has not measured how well that works",
    "Which simulated kind stands for which metric is a judgement",
    "the p value of the test that the control's mean is the same in every cohort",
    "When the means cannot be compared (a mean is missing, or both are zero), both ranges count",
]


def test_the_section_says_what_was_decided_and_what_is_judgement_in_these_words() -> None:
    section = " ".join(_section().split())

    for claim in CLAIMS:
        assert section.count(claim) == 1, claim
    assert section.count("judgement") >= 4
