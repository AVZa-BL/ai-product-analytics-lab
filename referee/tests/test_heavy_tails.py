"""The signs of a heavy tail RES-008 looks for, group by group (design section 21.11).

The three predicates are tested at their exact boundaries on numbers; the shapes on groups of
values built by hand, whose skewness and kurtosis can be worked out on paper.
"""

import math
import random
from fractions import Fraction

import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, crowd, results_spec

from referee.heavy_tails import (
    DIGITS,
    EFFECT_CAP,
    EQUAL_ARMS_SPLIT,
    KOHAVI_MULTIPLE,
    KURTOSIS_OVER,
    LIMBS,
    SKEWNESS_OVER,
    TOP_SHARE_OVER,
    Comparison,
    GroupShape,
    compare,
    far_apart,
    group_shape,
    kohavi_minimum,
    kohavi_trips,
    kurtosis_trips,
    nearest_cases,
    not_simulated,
    pair_of,
    pairs,
    share_trips,
    simulated,
)
from referee.pooled_rates import Case, SimulatedRange, hull, lookup
from referee.results import METRIC_FAMILIES, METRICS, ResultsContext

REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 10.0,
}


def test_the_levels_are_the_ones_the_design_names() -> None:
    assert (KOHAVI_MULTIPLE, SKEWNESS_OVER, KURTOSIS_OVER, TOP_SHARE_OVER) == (355, 1, 100, 0.5)
    assert LIMBS == ("kohavi", "kurtosis", "top_share")
    assert EQUAL_ARMS_SPLIT == Fraction(5, 4)


# --- The three predicates, at their boundaries ------------------------------------------------


@pytest.mark.parametrize(
    ("n", "skewness", "trips"),
    [
        (1419, 2.0, True),  # 355 * 4 = 1420 players are wanted
        (1420, 2.0, False),  # exactly as many as wanted
        (1421, 2.0, False),
        (1419, -2.0, True),  # the sign does not matter
        (1420, -2.0, False),
        (798, 1.5, True),  # 355 * 2.25 = 798.75
        (799, 1.5, False),
        (2, 1.0, False),  # a skewness of exactly 1 is not above 1
        (2, -1.0, False),
        (2, 0.999999, False),
        (2, 1.000001, True),  # 355 * 1.000002 is 355.0007
        (355, 1.000001, True),
        (356, 1.000001, False),
        (10, 0.0, False),
        (0, 5.0, True),  # no players is fewer than any number wanted
    ],
)
def test_the_size_rule_trips_below_355_times_the_squared_skewness(
    n: int, skewness: float, trips: bool
) -> None:
    assert kohavi_trips(n, skewness) is trips


def test_the_minimum_is_355_times_the_square_of_the_skewness() -> None:
    assert kohavi_minimum(2.0) == 1420.0
    assert kohavi_minimum(-3.0) == 3195.0
    assert kohavi_minimum(0.0) == 0.0


@pytest.mark.parametrize(
    ("kurtosis", "trips"),
    [(100.0, False), (100.000001, True), (99.999999, False), (-3.0, False), (462.6, True)],
)
def test_the_kurtosis_sign_is_an_excess_kurtosis_above_100(kurtosis: float, trips: bool) -> None:
    assert kurtosis_trips(kurtosis) is trips


@pytest.mark.parametrize(
    ("share", "trips"),
    [(0.5, False), (0.500001, True), (0.499999, False), (0.0, False), (1.0, True)],
)
def test_the_share_sign_is_a_top_share_above_one_half(share: float, trips: bool) -> None:
    assert share_trips(share) is trips


# --- The shape of a group, on values worked out by hand --------------------------------------


def _exponential(n: int) -> list[float]:
    """The n quantiles of an exponential distribution: skewness near 2, kurtosis near 6."""
    return [-math.log(1 - (i + 0.5) / n) for i in range(n)]


def test_one_player_who_spends_among_a_hundred_shows_two_signs() -> None:
    shape = group_shape("a", [0.0] * 99 + [1.0])

    assert (shape.n, shape.payers, shape.read) == (100, 1, True)
    assert shape.mean == 0.01
    assert shape.skewness == pytest.approx((1 - 2 * 0.01) / math.sqrt(0.01 * 0.99), abs=1e-5)
    assert shape.excess_kurtosis == pytest.approx(100**2 / 99 - 6, abs=1e-5)  # 95.01: not above 100
    assert (shape.top_count, shape.top_share) == (1, 1.0)
    assert shape.limbs == ("kohavi", "top_share")


def test_the_size_rule_alone_trips_on_a_skewed_sample_with_a_light_tail() -> None:
    shape = group_shape("a", _exponential(500))

    assert shape.skewness is not None and 1.5 < shape.skewness < 2.5
    assert shape.kohavi_minimum == round(355 * shape.skewness**2, DIGITS)
    assert shape.n < shape.kohavi_minimum
    assert shape.excess_kurtosis is not None and shape.excess_kurtosis < 20
    assert shape.top_share is not None and shape.top_share < 0.1
    assert shape.limbs == ("kohavi",)


def test_the_kurtosis_alone_trips_on_two_symmetric_outliers() -> None:
    # 998 players at 1000, one at 0 and one at 2000: no skewness, a kurtosis of 1000 / 2 - 3
    shape = group_shape("a", [1000.0] * 998 + [0.0, 2000.0])

    assert shape.skewness == 0.0
    assert shape.excess_kurtosis == pytest.approx(497.0, abs=1e-6)
    assert shape.top_count == 10  # 1% of 1,000 players: the 2000 and nine of 1000
    assert shape.top_share == pytest.approx(11_000 / 1_000_000, abs=1e-9)
    assert shape.limbs == ("kurtosis",)


def test_the_share_alone_trips_on_two_players() -> None:
    shape = group_shape("a", [1.0, 3.0])  # symmetric, the top player holds three quarters

    assert shape.skewness == 0.0 and shape.excess_kurtosis == pytest.approx(-2.0)
    assert (shape.top_count, shape.top_share) == (1, 0.75)
    assert shape.limbs == ("top_share",)


def test_a_group_with_no_sign_has_none() -> None:
    rng = random.Random(1)
    values = [rng.gauss(50.0, 5.0) for _ in range(2000)]

    shape = group_shape("a", values)

    assert shape.read and shape.limbs == ()
    assert shape.payers == 2000


def test_the_measures_are_rounded_and_the_decision_is_made_on_the_rounded_numbers() -> None:
    rng = random.Random(7)
    for _ in range(60):
        n = rng.randint(2, 400)
        sigma = rng.choice([0.5, 1.5, 2.5])
        values = [0.0 if rng.random() < 0.8 else rng.lognormvariate(0, sigma) for _ in range(n)]
        if len(set(values)) < 2 or sum(values) == 0:
            continue
        shape = group_shape("a", values)

        assert shape.skewness == round(shape.skewness, DIGITS)
        assert shape.excess_kurtosis == round(shape.excess_kurtosis, DIGITS)
        assert shape.top_share == round(shape.top_share, DIGITS)
        assert shape.limbs == tuple(
            limb
            for limb, trips in (
                ("kohavi", kohavi_trips(shape.n, shape.skewness)),
                ("kurtosis", kurtosis_trips(shape.excess_kurtosis)),
                ("top_share", share_trips(shape.top_share)),
            )
            if trips
        )


# --- A group that cannot be read says why -----------------------------------------------------


@pytest.mark.parametrize(
    ("values", "reason", "payers", "mean"),
    [
        ([], "too_few_players", 0, None),
        ([5.0], "too_few_players", 1, 5.0),
        ([0.0] * 6, "all_zero", 0, 0.0),
        ([3.0] * 5, "no_variation", 5, 3.0),
        ([0.7] * 3, "no_variation", 3, 0.7),
        ([1.0, -1.0, 2.0], "negative_value", 3, None),
        ([-1.0, -1.0], "negative_value", 2, None),
        ([1.0, math.nan], "not_computable", 2, None),
        ([1.0, math.inf, 0.0], "not_computable", 2, None),
        ([0.0] * 50 + [1e300, 2e300], "not_computable", 2, 5.76923e298),
        ([1e-100, 2e-100, 4e-100], "not_computable", 3, 2.33333e-100),  # tiny, but it has a mean
        ([0.1 + 0.2, 0.3, 0.3], "no_variation", 3, 0.3),  # equal up to rounding noise
        ([1e308] * 3 + [0.0], "not_computable", 3, None),  # the sum is too large to hold
    ],
)
def test_a_group_that_cannot_be_measured_gives_the_reason_and_the_mean_if_it_has_one(
    values: list[float], reason: str, payers: int, mean: float | None
) -> None:
    shape = group_shape("a", values)

    assert shape == GroupShape(arm="a", n=len(values), payers=payers, unread=reason, mean=mean)
    assert not shape.read and shape.limbs == ()
    assert shape.skewness is None and shape.kohavi_minimum is None


# --- Two groups: the comparison the simulations are indexed by --------------------------------


def _shape(arm: str, n: int, payers: int) -> GroupShape:
    return GroupShape(arm=arm, n=n, payers=payers, unread=None)


@pytest.mark.parametrize(
    ("arm_n", "control_n", "split", "larger", "smaller"),
    [
        (100, 100, Fraction(1), "equal", "arm"),  # the same size: the one with fewer payers
        (150, 100, Fraction(3, 2), "arm", "control"),
        (100, 150, Fraction(3, 2), "control", "arm"),
        (969, 926, Fraction(969, 926), "arm", "control"),
        (900, 100, Fraction(9), "arm", "control"),
        (100, 900, Fraction(9), "control", "arm"),
    ],
)
def test_the_smaller_group_is_the_one_with_fewer_players(
    arm_n: int, control_n: int, split: Fraction, larger: str, smaller: str
) -> None:
    found = compare(_shape("arm", arm_n, 7), _shape("control", control_n, 9))

    assert found is not None
    assert (found.split, found.larger, found.smaller) == (split, larger, smaller)
    assert found.payers == (7 if smaller == "arm" else 9)


def test_of_two_groups_of_one_size_the_smaller_has_fewer_players_who_spend() -> None:
    fewer_in_arm = compare(_shape("arm", 100, 7), _shape("control", 100, 9))
    fewer_in_control = compare(_shape("arm", 100, 9), _shape("control", 100, 7))
    tied = compare(_shape("arm", 100, 8), _shape("control", 100, 8))

    assert fewer_in_arm == Comparison(split=Fraction(1), larger="equal", smaller="arm", payers=7)
    assert fewer_in_control == Comparison(
        split=Fraction(1), larger="equal", smaller="control", payers=7
    )
    assert tied == Comparison(split=Fraction(1), larger="equal", smaller="control", payers=8)


@pytest.mark.parametrize(("arm_n", "control_n"), [(0, 5), (5, 0), (0, 0)])
def test_a_group_with_no_players_has_no_comparison(arm_n: int, control_n: int) -> None:
    assert compare(_shape("arm", arm_n, 0), _shape("control", control_n, 0)) is None


def _unread(arm: str, reason: str = "all_zero") -> GroupShape:
    return GroupShape(arm=arm, n=50, payers=0, unread=reason)  # type: ignore[arg-type]


def _read(arm: str, limbs: tuple = ()) -> GroupShape:
    return GroupShape(arm=arm, n=500, payers=60, unread=None, limbs=limbs)


def test_a_pair_trips_when_any_group_that_can_be_read_does() -> None:
    both = pair_of(_read("arm", ("top_share", "kohavi")), _read("control", ("kurtosis", "kohavi")))
    one = pair_of(_unread("arm"), _read("control", ("kohavi",)))

    assert both.status == "tripped" and both.limbs == ("kohavi", "kurtosis", "top_share")
    assert [g.arm for g in both.groups if "kohavi" in g.limbs] == ["arm", "control"]
    assert [g.arm for g in both.groups if "kurtosis" in g.limbs] == ["control"]
    assert one.status == "tripped" and one.limbs == ("kohavi",)
    assert [g.arm for g in one.groups] == ["arm", "control"]


def test_a_pair_is_not_evaluated_only_when_nothing_trips_and_a_group_could_not_be_read() -> None:
    quiet = pair_of(_read("arm"), _read("control"))
    half = pair_of(_unread("arm", "no_variation"), _read("control"))
    none = pair_of(_unread("arm"), _unread("control", "too_few_players"))

    assert (quiet.status, quiet.limbs) == ("not_tripped", ())
    assert (half.status, half.limbs) == ("not_evaluated", ())
    assert (none.status, none.limbs) == ("not_evaluated", ())


def test_a_pair_carries_its_comparison() -> None:
    found = pair_of(_read("arm"), GroupShape(arm="control", n=250, payers=30, unread=None))

    assert found.comparison == Comparison(
        split=Fraction(2), larger="arm", smaller="control", payers=30
    )


# --- Reading a context ------------------------------------------------------------------------


def _spenders(arm: str, revenues: list[float]) -> list[Row]:
    return [Row(f"{arm}_{i:04d}", arm, revenue=value) for i, value in enumerate(revenues)]


def _context(raw_spec, rows: list[Row], **more) -> ResultsContext:
    spec = results_spec(raw_spec, arms=TWO_ARMS, **{**REVENUE, **more})
    return ResultsContext.of(spec, build_data(rows))


def test_the_pairs_of_a_metric_are_every_arm_but_control_in_the_spec_order(raw_spec) -> None:
    arms = [
        {"name": "control", "allocation": 0.4, "is_control": True},
        {"name": "variant_b", "allocation": 0.3},
        {"name": "variant_c", "allocation": 0.3},
    ]
    spec = results_spec(raw_spec, arms=arms, **REVENUE)
    rows = _spenders("variant_c", [0.0, 0.0, 1.0, 3.0]) + _spenders("control", [0.0, 1.0, 1.0, 2.0])
    rows += _spenders("variant_b", [0.0, 0.0, 4.0, 8.0])
    context = ResultsContext.of(spec, build_data(rows))

    found = pairs(context, METRICS["revenue_usd_7d"])

    assert [(p.arm.arm, p.control.arm) for p in found] == [
        ("variant_b", "control"),
        ("variant_c", "control"),
    ]
    assert [p.arm.mean for p in found] == [3.0, 1.0]
    assert found[0].control.mean == 1.0
    assert found[0].control == found[1].control


def test_only_the_analysed_players_are_read(raw_spec) -> None:
    rows = crowd("control", 10, revenue=0.0)
    rows += crowd("control", 5, prefix="c_unexposed", exposed_at=None, revenue=900.0)
    rows += crowd(
        "control",
        4,
        prefix="c_late",
        revenue=700.0,
        purchases=1,
        first_purchase_at=at(0, 1),
        exposed_at=at(0, 2),
    )
    rows += crowd("variant_b", 10, revenue=1.0)
    context = _context(raw_spec, rows)

    (found,) = pairs(context, METRICS["revenue_usd_7d"])

    assert found.control.n == 10 and found.control.payers == 0
    assert found.control.unread == "all_zero"
    assert found.arm.n == 10 and found.arm.unread == "no_variation"
    assert found.status == "not_evaluated"


def test_a_metric_that_is_not_the_primary_one_is_read_by_its_own_values(raw_spec) -> None:
    rows = [
        Row(f"c{i}", "control", sessions=s, revenue=0.0) for i, s in enumerate([1, 2, 3, 4, 5, 6])
    ]
    rows += [Row(f"b{i}", "variant_b", sessions=s) for i, s in enumerate([2, 2, 2, 2, 3, 40])]
    context = _context(raw_spec, rows)

    (found,) = pairs(context, METRICS["sessions_7d"])

    assert found.control.mean == 3.5 and found.arm.mean == pytest.approx(51 / 6)
    assert found.control.limbs == () and found.arm.limbs == ("kohavi", "top_share")


# --- When the simulated rates may be quoted ---------------------------------------------------


def test_every_metric_the_export_holds_has_a_family() -> None:
    assert set(METRIC_FAMILIES) == set(METRICS)
    assert {name for name, kind in METRIC_FAMILIES.items() if kind == "binary"} == {
        name for name, metric in METRICS.items() if metric.kind == "binary"
    }
    assert METRIC_FAMILIES["revenue_usd_7d"] == "revenue_like"
    assert METRIC_FAMILIES["sessions_7d"] == METRIC_FAMILIES["purchases_7d"] == "count"


def _comparison(split: Fraction = Fraction(2), larger="arm", payers: int = 30) -> Comparison:
    return Comparison(split=split, larger=larger, smaller="control", payers=payers)


@pytest.mark.parametrize(
    ("metric", "unit", "comparison", "reason"),
    [
        ("revenue_usd_7d", "player", _comparison(), None),
        ("revenue_usd_7d", "user", _comparison(), None),
        ("revenue_usd_7d", "device", _comparison(), "unit_not_independent"),  # analysis: player
        ("revenue_usd_7d", "session", _comparison(), "unit_not_independent"),
        ("sessions_7d", "player", _comparison(), "metric_not_simulated"),
        ("purchases_7d", "session", _comparison(), "metric_not_simulated"),
        ("revenue_usd_7d", "player", None, "a_group_has_no_players"),
        ("revenue_usd_7d", "player", _comparison(payers=0), "no_players_who_spend"),
    ],
)
def test_the_rates_are_quoted_for_revenue_of_independent_players_who_spend(
    raw_spec, metric: str, unit: str, comparison, reason
) -> None:
    primary = {**REVENUE, "primary_metric__name": metric}
    context = _context(
        raw_spec,
        crowd("control", 4, revenue=1.0) + crowd("variant_b", 4, revenue=2.0),
        population__randomization_unit=unit,
        **{k: v for k, v in primary.items() if k.startswith("primary_metric")},
    )

    assert not_simulated(context, METRICS[metric], comparison) == reason


def test_unequal_groups_are_read_in_both_orders_so_the_range_is_the_hull_of_both() -> None:
    for larger in ("arm", "control"):  # the same range whichever group is the larger
        comparison = _comparison(Fraction(3), larger, 39)

        found = simulated(comparison)

        for effects in ("small", "large"):
            assert found[effects] == hull(
                lookup(effects, "arm", Fraction(3), 39), lookup(effects, "control", Fraction(3), 39)
            )
            assert found[effects].larger == "either"


def test_groups_about_equal_in_size_are_placed_among_the_cases_of_groups_of_one_size() -> None:
    for split, larger in (
        (Fraction(1), "equal"),
        (Fraction(21, 20), "arm"),
        (EQUAL_ARMS_SPLIT, "control"),
    ):
        comparison = Comparison(split=split, larger=larger, smaller="control", payers=39)

        assert comparison.placed_as_equal and comparison.placed_split == 1
        found = simulated(comparison)
        assert found["small"] == lookup("small", "equal", Fraction(1), 39)
        assert found["large"] == lookup("large", "equal", Fraction(1), 39)
    beyond = Comparison(split=Fraction(1251, 1000), larger="arm", smaller="control", payers=39)
    assert not beyond.placed_as_equal and beyond.placed_split == Fraction(1251, 1000)
    assert simulated(beyond)["small"].larger == "either"


# --- Which effects are nearer, which case is nearest ----------------------------------------------


def _meaned(arm: str, n: int, payers: int, mean: float | None) -> GroupShape:
    return GroupShape(arm=arm, n=n, payers=payers, unread=None, mean=mean)


@pytest.mark.parametrize(
    ("arm_mean", "control_mean", "effect", "nearer"),
    [
        (1.1, 1.0, 0.1, "small"),
        (1.349, 1.0, 0.349, "small"),
        (1.35, 1.0, 0.35, "large"),
        (1.0, 1.35, 0.35, "large"),  # the other way round: the same two groups, the same effect
        (1.0, 1.349, 0.349, "small"),
        (0.8, 1.0, 0.25, "small"),  # -20% of control's mean is +25% in the terms of the study
        (0.74, 1.0, 0.351351, "large"),  # -26% of control's mean is +35% in those terms
        (2.0, 1.0, 1.0, "large"),
        (1.0, 0.0, None, "large"),  # a lower mean of 0: an effect without bound
        (0.0, 1.0, None, "large"),
        (0.0, 0.0, None, None),
        (None, 1.0, None, None),
        (1.0, None, None, None),
    ],
)
def test_the_effects_nearer_the_difference_seen_are_found_as_the_study_measures_them(
    arm_mean, control_mean, effect, nearer
) -> None:
    pair = pair_of(_meaned("arm", 500, 60, arm_mean), _meaned("control", 500, 60, control_mean))

    assert pair.effect_seen == effect and pair.nearer_effects == nearer


def test_swapping_which_group_is_control_does_not_change_the_effects_nearer() -> None:
    for first, second in ((1.2, 1.0), (1.43, 1.0), (1.34999, 1.0), (7.0, 2.0)):
        one = pair_of(_meaned("arm", 500, 60, first), _meaned("control", 500, 60, second))
        other = pair_of(_meaned("arm", 500, 60, second), _meaned("control", 500, 60, first))

        assert (one.effect_seen, one.nearer_effects) == (other.effect_seen, other.nearer_effects)


def test_the_effect_nearer_is_decided_on_the_figure_the_evidence_shows() -> None:
    just_under = pair_of(_meaned("arm", 500, 60, 1.3499996), _meaned("control", 500, 60, 1.0))
    over = pair_of(_meaned("arm", 500, 60, 1.35), _meaned("control", 500, 60, 1.0))

    assert just_under.effect_seen == 0.35 and just_under.nearer_effects == "large"
    assert over.effect_seen == 0.35 and over.nearer_effects == "large"


@pytest.mark.parametrize(
    ("arm_mean", "control_mean", "relative", "effect", "nearer"),
    [
        (1.1, 1.0, 0.1, 0.1, "small"),
        (0.64, 1.0, -0.36, 0.5625, "large"),  # -36% of control's mean is +56% as the study has it
        (2.7, 2.0, 0.35, 0.35, "large"),
        (1.0, 0.0, None, None, "large"),  # control's mean is 0: no share of it
        (0.0, 2.0, -1.0, None, "large"),  # the arm's is: -100%, an effect without bound
        (1.0, None, None, None, None),
        (3e6, 1.0, None, None, "large"),  # beyond what is measured: without bound
        (1.0, 3e6, -1.0, None, "large"),
    ],
)
def test_the_difference_seen_is_a_share_of_control_s_mean_found_from_the_means_shown(
    arm_mean, control_mean, relative, effect, nearer
) -> None:
    pair = pair_of(_meaned("arm", 500, 60, arm_mean), _meaned("control", 500, 60, control_mean))

    assert pair.relative_difference == relative or pair.relative_difference == pytest.approx(
        relative, abs=1e-5
    )
    if effect is None:
        assert pair.effect_seen is None
    else:
        assert pair.effect_seen == pytest.approx(effect, rel=1e-5) or effect > EFFECT_CAP
    assert pair.nearer_effects == nearer
    # it does not need the interval: the means are the evidence
    assert pair_of(_read("arm"), _read("control")).relative_difference is None  # no mean at all


def test_the_nearest_case_is_the_one_least_far_in_the_logs_of_the_split_and_the_players() -> None:
    found = lookup("large", "equal", Fraction(1), 129)
    comparison = Comparison(split=Fraction(1), larger="equal", smaller="control", payers=129)

    assert {c.payers for c in found.cases} == {13, 130}
    assert [c.payers for c in nearest_cases(found, comparison)] == [130]
    low = Comparison(split=Fraction(1), larger="equal", smaller="control", payers=15)
    assert [c.payers for c in nearest_cases(lookup("large", "equal", Fraction(1), 15), low)] == [13]
    # the split counts as much as the players: 3 to 1 against 1 to 1 for a comparison of 2 to 1
    mixed = Comparison(split=Fraction(2), larger="arm", smaller="control", payers=13)
    (nearest,) = nearest_cases(lookup("large", "arm", Fraction(2), 13), mixed)
    assert nearest.split == Fraction(3)


def test_cases_at_the_same_distance_are_all_nearest_and_a_range_read_both_ways_has_both() -> None:
    comparison = _comparison(Fraction(19), "arm", 117)
    found = simulated(comparison)["large"]

    nearest = nearest_cases(found, comparison)

    assert {(c.larger, c.split, c.payers) for c in nearest} == {
        ("arm", Fraction(9), 130),
        ("control", Fraction(9), 130),
    }
    assert max(c.high for c in nearest) > min(c.high for c in nearest)  # the orders differ
    # groups about equal in size are placed at 1 to 1, so the split of the comparison is not used
    near_equal = Comparison(split=Fraction(21, 20), larger="arm", smaller="control", payers=13)
    (case,) = nearest_cases(simulated(near_equal)["large"], near_equal)
    assert (case.larger, case.split, case.payers) == ("equal", Fraction(1), 13)


@pytest.mark.parametrize(
    ("effects", "larger", "split", "payers", "far"),
    [
        ("large", "arm", Fraction(3), 129, True),  # 13 and 130 players who spend
        ("large", "arm", Fraction(2), 130, True),  # 1 to 1 and 3 to 1
        ("small", "arm", Fraction(3), 50, False),  # 39 and 90 at one split
        ("small", "arm", Fraction(5, 4), 130, False),  # 1 to 1 and 1.5 to 1
        ("small", "control", Fraction(3), 130, False),  # on the grid: its own case
        ("small", "arm", Fraction(3), 20, False),  # 13 and 30: a factor of 2.3
        ("small", "arm", Fraction(3), 11, False),  # 9 and 13
    ],
)
def test_cases_are_far_apart_at_five_times_the_players_or_two_and_a_half_times_the_split(
    effects: str, larger: str, split: Fraction, payers: int, far: bool
) -> None:
    assert far_apart(lookup(effects, larger, split, payers)) is far


@pytest.mark.parametrize(
    ("skewness", "kurtosis", "share", "limbs"),
    [
        (1.0000004, 100.0000004, 0.5000004, ()),  # each rounds to the level: no sign
        (1.0000006, 100.0000006, 0.5000006, ("kohavi", "kurtosis", "top_share")),  # to above it
        (-1.0000006, 99.9999996, 0.4999996, ("kohavi",)),
        (-1.0000004, 100.0000004, 0.5000004, ()),
    ],
)
def test_the_decision_is_made_on_the_figures_rounded_to_six_places(
    monkeypatch, skewness: float, kurtosis: float, share: float, limbs: tuple
) -> None:
    from referee import heavy_tails
    from referee.methods import HeavyTail

    def measured(values, *, top_percent):
        return HeavyTail(
            n=len(values),
            skewness=skewness,
            excess_kurtosis=kurtosis,
            top_percent=top_percent,
            top_count=1,
            top_share=share,
        )

    monkeypatch.setattr(heavy_tails, "heavy_tail_measures", measured)

    shape = group_shape("a", [0.0, 1.0, 2.0])  # 3 players: fewer than 355 times the square asks

    assert shape.limbs == limbs
    assert shape.skewness == round(skewness, DIGITS) and shape.excess_kurtosis == round(
        kurtosis, DIGITS
    )


def _range_of(*cases: tuple[Fraction, int]) -> SimulatedRange:
    rows = tuple(
        Case("small", "arm", split, payers, 1000, 2000, 6, 3, 20000, 0) for split, payers in cases
    )
    return SimulatedRange(
        effects="small", larger="arm", low=1000, high=2000, cases=rows, extrapolated=(), rising=()
    )


@pytest.mark.parametrize(
    ("cases", "far"),
    [
        (((Fraction(2), 20), (Fraction(2), 100)), True),  # exactly 5 times the players
        (((Fraction(2), 20), (Fraction(2), 99)), False),
        (((Fraction(1), 50), (Fraction(5, 2), 50)), True),  # exactly 2.5 times the split
        (((Fraction(1), 50), (Fraction(249, 100), 50)), False),
        (((Fraction(2), 50),), False),  # one case: nothing to be far from
    ],
)
def test_the_limits_of_far_apart_are_inclusive(cases: tuple, far: bool) -> None:
    assert far_apart(_range_of(*cases)) is far


def test_the_size_rule_is_decided_on_the_minimum_the_evidence_shows() -> None:
    skewness = math.sqrt(556.0000004 / KOHAVI_MULTIPLE)  # 355 times its square: 556.0000004

    assert kohavi_minimum(skewness) > 556 and round(kohavi_minimum(skewness), DIGITS) == 556
    assert not kohavi_trips(556, skewness)  # the evidence says 556: 556 players are not fewer
    assert kohavi_trips(555, skewness)
