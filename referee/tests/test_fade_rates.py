"""The measured share of faded effects RES-007 flags, which its note always prints (section 21.11).

`FADE_FLAG_RATES` are checked against the saved study they come from, and the sentence against
the constants, on cohorts the simulations did and did not cover.
"""

import json
import math
import random
from pathlib import Path

import pytest
from cohort_helpers import THREE_ARMS, cohort_context
from results_helpers import TWO_ARMS, Row, at

from referee.cohort_effects import (
    FADE_COHORTS,
    FADE_FAMILIES,
    FADE_FLAG_RATES,
    FADE_FLAG_RATES_ADDED,
    FADE_MAX_ALLOCATION_RATIO,
    FADE_SIZES,
    POWER,
)
from referee.pooled_rates import percent
from referee.results import METRICS
from referee.rules.cohorts import _nearest_size, _outside_simulations, cohort_report

HEAVY = json.loads(
    (Path(__file__).parent.parent / "docs/simulations/cohort_trigger_heavy.json").read_text(
        encoding="utf-8"
    )
)
KINDS = {
    "revenue_like": ("revenue_mild", "revenue", "revenue_heavy"),
    "binary": ("binary",),
    "poisson": ("poisson",),
}
REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 10.0,
    "design__mde_relative": 0.5,
}
PURCHASES = {"primary_metric__name": "purchases_7d", "design__mde_relative": 1.0}


# --- The constants are the saved study ------------------------------------------------------


def _printed(kinds: tuple[str, ...], scenario: str, size: int) -> list[float]:
    return [
        row["both"]
        for row in HEAVY["printed"]
        if row["outcome"] in kinds and row["scenario"] == scenario and row["n"] == size
    ]


def test_the_flag_rates_are_the_lowest_and_highest_of_the_saved_study() -> None:
    assert set(FADE_FLAG_RATES) == set(KINDS) and FADE_SIZES == (100, 300, 1000)
    for kind, by_size in FADE_FLAG_RATES.items():
        assert set(by_size) == set(FADE_SIZES)
        for size, (low, high) in by_size.items():
            found = _printed(KINDS[kind], "printed_shift", size)
            assert len(found) == 2 * len(KINDS[kind])  # 4 and 8 cohorts, each outcome
            assert (low, high) == (min(found), max(found)), (kind, size)


def test_the_rates_with_the_fade_added_to_every_player_are_those_of_the_saved_study() -> None:
    assert set(FADE_FLAG_RATES_ADDED) == {"revenue_like"}
    for size, (low, high) in FADE_FLAG_RATES_ADDED["revenue_like"].items():
        found = _printed(KINDS["revenue_like"], "printed_location", size)
        assert len(found) == 6 and (low, high) == (min(found), max(found)), size


def test_the_study_ran_two_equal_arms_and_four_and_eight_cohorts() -> None:
    rows = [r for r in HEAVY["printed"] if r["scenario"] == "printed_shift"]

    assert {r["arms"] for r in rows} == {2} and all(r["control_n"] == r["n"] for r in rows)
    assert {r["cohorts"] for r in rows} == set(FADE_COHORTS) == {4, 8}


def test_the_trigger_flagged_a_fade_of_the_printed_size_in_fewer_runs_than_the_power_claims() -> (
    None
):
    every_rate = [
        r for by_size in FADE_FLAG_RATES.values() for lo_hi in by_size.values() for r in lo_hi
    ]

    assert max(every_rate) < POWER  # in no simulated case did the trigger reach the 80%
    assert FADE_MAX_ALLOCATION_RATIO == 1.25


def test_every_metric_the_export_holds_has_the_simulated_kinds_that_stand_for_it() -> None:
    assert set(FADE_FAMILIES) == set(METRICS)
    assert all(kind in FADE_FLAG_RATES for kinds in FADE_FAMILIES.values() for kind in kinds)
    assert FADE_FAMILIES["revenue_usd_7d"] == ("revenue_like",)
    assert FADE_FAMILIES["sessions_7d"] == ("poisson",)
    assert FADE_FAMILIES["purchases_7d"] == ("binary", "poisson")  # mostly 0 or 1, but a count


@pytest.mark.parametrize(
    ("players", "size"),
    [(100, 100), (173, 100), (174, 300), (300, 300), (547, 300), (548, 1000), (1000, 1000)],
)
def test_the_nearest_simulated_size_is_the_nearest_in_log_scale(players: int, size: int) -> None:
    assert _nearest_size(players) == size
    assert math.isclose(math.sqrt(100 * 300), 173.2, abs_tol=0.05)
    assert math.isclose(math.sqrt(300 * 1000), 547.7, abs_tol=0.05)


# --- The sentence --------------------------------------------------------------------------------


def _rows(arm: str, blocks: int, players: int, make) -> list[Row]:
    rng = random.Random(f"{arm}{players}")
    return [
        Row(
            f"{arm}_{block:02d}_{i:04d}",
            arm,
            assigned_at=at(7 * block),
            exposed_at=at(7 * block, 1),
            **make(rng),
        )
        for block in range(blocks)
        for i in range(players)
    ]


def _revenue(rng: random.Random) -> dict:
    return {"revenue": rng.lognormvariate(1.0, 1.5) if rng.random() < 0.13 else 0.0}


def _purchases(rng: random.Random) -> dict:
    return {"purchases": int(rng.random() < 0.10)}


def _poisson(rng: random.Random) -> dict:
    return {"sessions": sum(rng.random() < 0.1 for _ in range(100))}


def _note(raw_spec, make, *, blocks=4, players=100, arms=TWO_ARMS, rows=None, **more) -> str:
    if rows is None:
        rows = _rows("control", blocks, players, make) + _rows("variant_b", blocks, players, make)
    context = cohort_context(raw_spec, rows, days=7 * blocks, arms=arms, **more)
    report = cohort_report(context, None)
    return next(n for n in report["notes"] if n.startswith("arm variant_b, metric"))


def _text(rate: tuple[float, float]) -> str:
    return f"{percent(round(rate[0] * 100_000))} to {percent(round(rate[1] * 100_000))}"


def test_a_count_metric_inside_the_simulated_design_is_given_the_poisson_rates(raw_spec) -> None:
    note = _note(raw_spec, _poisson, players=300)

    assert "not flagged" in note
    assert (
        f"flagged a fade of exactly this size in {_text(FADE_FLAG_RATES['poisson'][300])} of runs "
        "for counts simulated as Poisson: below the 80% in every case simulated."
    ) in note
    assert (
        "with 300 players an arm in a cohort, the nearest size to this test's; a count or a "
        "size between those simulated counts as inside here, and this test has 4 cohorts and "
        "about 300 players an arm)"
    ) in " ".join(note.split())
    assert "4 and 8 cohorts" in note and "which needs the log-ratio scale as well" in note
    assert "The effect in those simulations multiplied" not in note
    assert note.index("The usual power calculation") < note.index("In Referee's simulations")
    assert "The step was not simulated, and the test could have missed anything smaller." in note


def test_a_revenue_metric_inside_the_design_is_given_the_revenue_rates_and_the_mechanism(
    raw_spec,
) -> None:
    note = _note(raw_spec, _revenue, players=100, **REVENUE)

    assert (
        f"in {_text(FADE_FLAG_RATES['revenue_like'][100])} of runs for revenue-like metrics: "
        "below the 80% in every case simulated."
    ) in note
    assert "multiplied what the players who spend spend" in note
    assert f"the rate was {_text(FADE_FLAG_RATES_ADDED['revenue_like'][100])}." in note


def test_purchases_are_given_the_binary_and_the_poisson_rates_side_by_side(raw_spec) -> None:
    note = _note(raw_spec, _purchases, players=300, **PURCHASES)

    binary, poisson = FADE_FLAG_RATES["binary"][300], FADE_FLAG_RATES["poisson"][300]
    assert (
        f"in {_text(binary)} of runs for a binary metric at a rate of 10% and in {_text(poisson)} "
        "of runs for counts simulated as Poisson: below the 80% in every case simulated."
    ) in note


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"players": 80}, "cohorts of about 80 players an arm"),
        ({"players": 1200}, "cohorts of about 1,200 players an arm"),
        ({"blocks": 3, "players": 300}, "3 cohorts"),
        ({"blocks": 9, "players": 100}, "9 cohorts"),
    ],
)
def test_a_test_outside_the_simulated_cohorts_says_so_and_gives_no_rate_for_it(
    raw_spec, kwargs: dict, reason: str
) -> None:
    note = _note(raw_spec, _poisson, **kwargs)

    assert (
        f"This test has {reason}, so what share of runs would flag a fade of this size is not "
        "known here"
    ) in note
    assert (
        "in the cases simulated the trigger flagged a fade of this size in "
        f"{_text((0.7043333333333334, 0.7706666666666667))} of runs for counts simulated as "
        "Poisson."
    ) in note
    assert "Referee simulated the trigger only for two arms of the same size" in note
    assert "In Referee's simulations (design section 21.5" not in note


def test_several_arms_unequal_arms_and_a_moving_baseline_are_each_outside_the_design(
    raw_spec,
) -> None:
    rows = (
        _rows("control", 4, 300, _poisson)
        + _rows("variant_b", 4, 300, _poisson)
        + _rows("variant_c", 4, 300, _poisson)
    )
    three = _note(raw_spec, _poisson, rows=rows, arms=THREE_ARMS)
    unequal = _note(
        raw_spec,
        _poisson,
        rows=_rows("control", 4, 300, _poisson) + _rows("variant_b", 4, 100, _poisson),
    )

    assert "This test has 2 arms against control" in three
    assert "This test has arms that differ in size by about 3 to 1" in unequal


def test_a_metric_no_simulation_stands_for_is_said_not_to_have_been_simulated(
    raw_spec, monkeypatch
) -> None:
    from referee.rules import cohorts

    entry = {"metric": "revenue_usd_7d", "design": {}, "control_baseline": {"moves": False}}
    without = {k: v for k, v in FADE_FAMILIES.items() if k != "revenue_usd_7d"}
    monkeypatch.setattr(cohorts, "FADE_FAMILIES", without)  # a copy: the table keeps its order

    text = cohorts._fade_rates(entry)

    assert list(FADE_FAMILIES)[0] == "revenue_usd_7d"
    assert "Referee did not simulate this kind of metric, so it does not know what share" in text


def test_the_reasons_an_experiment_is_outside_the_design_are_listed_in_one_order() -> None:
    entry = {
        "design": {
            "non_control_arms": 3,
            "cohorts": 10,
            "players_an_arm_median": 50,
            "allocation_ratio": 1.5,
        },
        "control_baseline": {"moves": True},
    }

    assert _outside_simulations(entry) == [
        "3 arms against control",
        "arms that differ in size by about 1.5 to 1",
        "10 cohorts",
        "cohorts of about 50 players an arm",
        "a control baseline that moves between the cohorts",
    ]
    inside = {
        **entry,
        "design": {
            **entry["design"],
            "non_control_arms": 1,
            "cohorts": 4,
            "players_an_arm_median": 100,
            "allocation_ratio": 1.25,
        },
        "control_baseline": {"moves": False},
    }
    assert _outside_simulations(inside) == []


def test_the_sentence_names_no_cause_and_is_ascii(raw_spec) -> None:
    for note in (
        _note(raw_spec, _poisson, players=300),
        _note(raw_spec, _revenue, players=100, **REVENUE),
        _note(raw_spec, _poisson, players=80),
    ):
        assert note.isascii() and not any(w in note.lower() for w in ("stable", "novelty", "decay"))
        assert "a little optimistic" not in note


def test_the_sentence_says_what_the_power_calculation_assumes_and_which_cohorts_were_simulated(
    raw_spec,
) -> None:
    inside = _note(raw_spec, _poisson, players=300)
    outside = _note(raw_spec, _poisson, players=80)

    for note in (inside, outside):
        assert (
            "That figure takes the standard errors as known and the effect as leaving the spread "
            "of the arm unchanged."
        ) in note
    assert (
        "4 or 8 cohorts and 100, 300 or 1,000 players an arm in a cohort (a count or a size "
        "between those counts as inside here)"
    ) in outside
    assert "(a test within 1.25 to 1 counts as the same here), a control baseline" in outside


def test_the_ratio_of_unequal_arms_is_rounded_up_to_two_places() -> None:
    entry = {
        "design": {
            "non_control_arms": 1,
            "cohorts": 5,
            "players_an_arm_median": 300,
            "allocation_ratio": 1.333,
        },
        "control_baseline": {"moves": False},
    }

    assert _outside_simulations(entry) == ["arms that differ in size by about 1.34 to 1"]


@pytest.mark.parametrize(
    ("change", "outside"),
    [
        ({"players_an_arm_median": 99}, True),
        ({"players_an_arm_median": 99.5}, True),
        ({"players_an_arm_median": 100}, False),
        ({"players_an_arm_median": 1000}, False),
        ({"players_an_arm_median": 1000.5}, True),
        ({"cohorts": 3}, True),
        ({"cohorts": 4}, False),
        ({"cohorts": 6}, False),  # between the 4 and the 8 simulated: inside, a judgement
        ({"cohorts": 8}, False),
        ({"cohorts": 9}, True),
        ({"allocation_ratio": 1.25}, False),
        ({"allocation_ratio": 1.2501}, True),
        ({"allocation_ratio": None}, False),
        ({"non_control_arms": 1}, False),
        ({"non_control_arms": 2}, True),
    ],
)
def test_the_limits_of_the_simulated_design_are_inclusive(change: dict, outside: bool) -> None:
    design = {
        "non_control_arms": 1,
        "cohorts": 5,
        "players_an_arm_median": 300,
        "allocation_ratio": 1.0,
        **change,
    }

    found = _outside_simulations({"design": design, "control_baseline": {"moves": False}})

    assert bool(found) is outside


def test_the_players_an_arm_are_the_median_over_the_cohorts_of_the_smaller_arm(raw_spec) -> None:
    def note_for(sizes: list[int]) -> str:
        rows = []
        for block, size in enumerate(sizes):
            rng = random.Random(block)
            for arm in ("control", "variant_b"):
                rows += [
                    Row(
                        f"{arm}_{block:02d}_{i:04d}",
                        arm,
                        assigned_at=at(7 * block),
                        exposed_at=at(7 * block, 1),
                        **_poisson(rng),
                    )
                    for i in range(size)
                ]
        return _note(raw_spec, _poisson, blocks=len(sizes), rows=rows)

    inside = note_for([50, 120, 130, 900])  # median 125, mean 300: inside
    outside = note_for([50, 60, 130, 900])  # median 95, mean 285: outside by the median
    halved = note_for([50, 120, 125, 900])  # median 122.5: a half is shown to one decimal

    assert "and about 125 players an arm)" in inside
    assert "and about 122.5 players an arm)" in halved
    assert "In Referee's simulations (design" in inside
    assert "cohorts of about 95 players an arm" in outside


@pytest.mark.parametrize(
    ("ratio", "text"), [(2.2, "2.2"), (4.4, "4.4"), (1.333, "1.34"), (3.0, "3")]
)
def test_a_ratio_is_rounded_up_to_two_places_without_the_error_of_a_float(
    ratio: float, text: str
) -> None:
    entry = {
        "design": {
            "non_control_arms": 1,
            "cohorts": 5,
            "players_an_arm_median": 300,
            "allocation_ratio": ratio,
        },
        "control_baseline": {"moves": False},
    }

    assert _outside_simulations(entry) == [f"arms that differ in size by about {text} to 1"]
