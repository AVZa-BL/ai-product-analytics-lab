"""A guardrail's breach, measured against the control and against the registered baseline.

The numbers are worked out here from the definitions (a ratio of means with a log-scale
interval; a t or Wilson interval for the arm's own mean or rate) and compared with the module's;
the decisions are checked at their boundaries.
"""

import math
import random

import pytest
from results_helpers import TWO_ARMS, Row, at, build_data, results_spec
from scipy import stats

from referee.guardrails import (
    ALPHA,
    CHANCE_LEVEL,
    SMALL_COUNT,
    TIERS,
    GuardrailTest,
    Harm,
    ReferenceResult,
    _chance_all_alike,
    _mean,
    baseline_reference,
    chance_could_explain,
    control_reference,
    guardrail_tests,
    tier_of,
)
from referee.guardrails import _harm as _raw_harm
from referee.methods import mean_interval, mean_ratio, proportion_interval
from referee.results import ResultsContext

SESSIONS = {
    "name": "sessions_7d",
    "kind": "continuous",
    "baseline": 3.0,
    "baseline_std": 2.0,
    "harmful_direction": "decrease",
    "tolerance_relative": 0.10,
}
PURCHASED = {
    "name": "purchased_7d",
    "kind": "binary",
    "baseline": 0.018,
    "harmful_direction": "increase",
    "tolerance_relative": 0.10,
}
REVENUE = {
    "primary_metric__name": "revenue_usd_7d",
    "primary_metric__kind": "continuous",
    "primary_metric__baseline": 1.0,
    "primary_metric__baseline_std": 10.0,
}


def _context(raw_spec, rows: list[Row], *guardrails: dict, arms=TWO_ARMS) -> ResultsContext:
    spec = results_spec(raw_spec, arms=arms, guardrails=list(guardrails), **REVENUE)
    return ResultsContext.of(spec, build_data(rows))


def _sessions(arm: str, values: list[int]) -> list[Row]:
    return [Row(f"{arm}_{i:05d}", arm, sessions=v) for i, v in enumerate(values)]


def _harm_of(direction: str, change: tuple[float, float, float], *, tolerance: float) -> Harm:
    return _raw_harm(
        direction, change, tolerance=tolerance, reference_value=1.0, measured=(1.0, 0.9, 1.1)
    )


def _spread(mean: float, n: int, half_width: float = 0.3) -> list[float]:
    """`n` values with exactly this mean, half of them `half_width` above it, half below."""
    return [mean + half_width if i % 2 else mean - half_width for i in range(n)]


# --- The two strengths of a breach, at their boundaries -------------------------------------------


@pytest.mark.parametrize(
    ("point", "low", "tolerance", "tier"),
    [
        (0.20, 0.12, 0.10, "shown"),  # the whole interval is beyond the tolerance
        (0.20, 0.10000001, 0.10, "shown"),
        (0.20, 0.10, 0.10, "possible"),  # the interval reaches the tolerance exactly: not beyond
        (0.20, -0.05, 0.10, "possible"),
        (0.10000001, -0.2, 0.10, "possible"),
        (0.10, -0.2, 0.10, "within"),  # at the tolerance is not worse than it
        (0.04, -0.3, 0.10, "within"),
        (-0.5, -0.9, 0.10, "within"),  # the metric got better
    ],
)
def test_a_breach_is_shown_when_the_whole_interval_is_beyond_the_tolerance(
    point: float, low: float, tolerance: float, tier: str
) -> None:
    assert tier_of(point, low, tolerance) == tier


def test_the_tiers_run_from_within_to_shown() -> None:
    assert TIERS == ("within", "possible", "shown")
    assert ALPHA == 0.05 and SMALL_COUNT == 10


@pytest.mark.parametrize(
    ("high", "not_verified"), [(0.099999, False), (0.10, False), (0.100001, True), (0.5, True)]
)
def test_a_comparison_is_not_shown_to_be_safe_only_if_its_interval_is_beyond_the_tolerance(
    high: float, not_verified: bool
) -> None:
    harm = _harm_of("increase", (0.04, -0.2, high), tolerance=0.10)

    assert harm.tier == "within"
    assert harm.not_verified is not_verified


@pytest.mark.parametrize("direction", ["increase", "decrease"])
def test_a_harm_of_either_direction_has_its_ends_in_order(direction: str) -> None:
    harm = _harm_of(direction, (0.12, 0.05, 0.19), tolerance=0.10)

    assert harm.low <= harm.point <= harm.high
    expected = (0.12, 0.05, 0.19) if direction == "increase" else (-0.12, -0.19, -0.05)
    assert (harm.point, harm.low, harm.high) == pytest.approx(expected)


# --- Against the control's observed mean ---------------------------------------------------------


def test_against_the_control_the_harm_is_the_ratio_of_the_means_less_one() -> None:
    arm, control = _spread(2.6, 400), _spread(3.0, 500)

    found = control_reference(arm, control, direction="decrease", tolerance=0.10)

    ratio = mean_ratio(arm, control)
    assert found.reference == "control" and found.reason is None
    harm = found.harm
    assert harm is not None
    assert harm.point == pytest.approx(1 - ratio.ratio, abs=1e-6) and harm.point == pytest.approx(
        0.133333, abs=1e-6
    )
    assert (harm.low, harm.high) == pytest.approx((1 - ratio.ci_high, 1 - ratio.ci_low), abs=1e-6)
    assert harm.reference_value == pytest.approx(3.0) and harm.measured[0] == pytest.approx(
        ratio.ratio
    )
    assert harm.tier == "shown" and not harm.not_verified  # 13% with a narrow interval, tol. 10%


def test_a_guardrail_that_may_not_increase_is_read_with_the_signs_the_other_way() -> None:
    arm, control = _spread(3.4, 400), _spread(3.0, 500)  # up 13%: bad if increase is harmful

    up = control_reference(arm, control, direction="increase", tolerance=0.10).harm
    down = control_reference(arm, control, direction="decrease", tolerance=0.10).harm

    assert up is not None and down is not None
    assert up.point == pytest.approx(0.133333, abs=1e-6) and up.tier == "shown"
    assert down.point == pytest.approx(-0.133333, abs=1e-6) and down.tier == "within"
    assert (down.low, down.high) == pytest.approx((-up.high, -up.low), abs=1e-6)


def test_an_interval_that_reaches_inside_the_tolerance_is_only_a_possible_breach() -> None:
    rng = random.Random(1)
    arm = [rng.uniform(0.0, 5.2) for _ in range(60)]
    control = [rng.uniform(0.0, 6.0) for _ in range(60)]
    ratio = mean_ratio(arm, control)
    assert ratio.ratio < 0.88 and ratio.ci_high > 0.92  # past 10% down, interval reaches inside

    harm = control_reference(arm, control, direction="decrease", tolerance=0.10).harm

    assert harm is not None and harm.tier == "possible"
    assert harm.point > 0.10 and harm.low < 0.10 < harm.high


def test_a_point_estimate_within_the_tolerance_is_within_even_if_the_interval_is_not() -> None:
    rng = random.Random(2)
    control = [rng.uniform(0.0, 6.0) for _ in range(40)]
    arm = list(control)  # the same values: no change at all, though 40 players cannot say so

    harm = control_reference(arm, control, direction="decrease", tolerance=0.02).harm

    assert harm is not None and harm.tier == "within" and harm.point < 0.02 < harm.high
    assert harm.not_verified  # the data cannot rule out a breach: said, but not a finding


@pytest.mark.parametrize(
    ("arm", "control", "reason"),
    [
        ([1.0], [1.0, 2.0, 3.0], "variant_b has fewer than 2 players"),
        ([1.0, 2.0], [], "control has fewer than 2 players"),
        ([1.0], [], "variant_b and control have fewer than 2 players"),
        (
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 3.0],
            "the mean of variant_b is not above 0, so the ratio of the means has no logarithm",
        ),
        (
            [1.0, 2.0, 3.0],
            [0.0, 0.0],
            "control's mean is not above 0, so a share of it is undefined",
        ),
        ([0.0, 0.0], [0.0, 0.0], "control's mean is not above 0"),  # control is named first
        ([2.0, 2.0], [3.0, 3.0], "neither variant_b nor control varies"),
        ([1e150, 2e150] * 10, [1e-170, 2e-170] * 10, "too large to represent"),
        ([1.0, 2.0, math.nan], [1.0, 2.0], "not a finite number"),
    ],
)
def test_the_control_reference_says_why_it_could_not_be_measured(arm, control, reason) -> None:
    found = control_reference(
        arm, control, direction="decrease", tolerance=0.10, arm_name="variant_b"
    )

    assert found.harm is None and found.reason is not None and reason in found.reason
    assert "treatment" not in found.reason and "values holds" not in found.reason


def test_an_arm_that_collapsed_to_zero_is_not_called_a_control_of_zero() -> None:
    """Only the log of the ratio fails there; control's mean is positive and a share of it is
    defined, which the reason must not deny."""
    found = control_reference(
        [0.0] * 50, [3.0, 4.0, 2.0, 3.0] * 20, direction="decrease", tolerance=0.10
    )

    assert found.harm is None and found.reason is not None
    assert "control's mean" not in found.reason and "undefined" not in found.reason
    assert "no logarithm" in found.reason


def test_the_control_reference_names_the_arm_it_was_given_and_a_default_otherwise() -> None:
    named = control_reference([1.0], [1.0, 2.0], direction="decrease", tolerance=0.1, arm_name="b")
    plain = control_reference([1.0], [1.0, 2.0], direction="decrease", tolerance=0.1)

    assert named.reason == "b has fewer than 2 players"
    assert plain.reason == "the arm has fewer than 2 players"


# --- Against the registered baseline --------------------------------------------------------------


def test_against_the_baseline_the_harm_is_the_arms_own_mean_against_it() -> None:
    values = _spread(2.5, 100, half_width=1.0)  # mean 2.5, a baseline of 3.0

    found = baseline_reference(
        values, baseline=3.0, kind="continuous", direction="decrease", tolerance=0.10
    )

    own = mean_interval(values)
    margin = stats.t.ppf(0.975, 99) * (1.0 / math.sqrt(100)) * math.sqrt(100 / 99)
    harm = found.harm
    assert harm is not None and harm.reference_value == 3.0
    assert own.ci_high - own.mean == pytest.approx(margin, rel=1e-9)
    assert harm.point == pytest.approx((3.0 - 2.5) / 3.0, abs=1e-6)  # a harm of 16.7%
    assert harm.low == pytest.approx((3.0 - own.ci_high) / 3.0, abs=1e-6)
    assert harm.high == pytest.approx((3.0 - own.ci_low) / 3.0, abs=1e-6)
    assert harm.tier == "shown" and harm.measured == pytest.approx((2.5, own.ci_low, own.ci_high))


def test_against_the_baseline_a_rate_has_a_wilson_interval() -> None:
    found = baseline_reference(
        [1.0] * 40 + [0.0] * 960,
        baseline=0.018,
        kind="binary",
        direction="increase",
        tolerance=0.10,
    )

    wilson = proportion_interval(40, 1000)
    harm = found.harm
    assert harm is not None
    assert harm.point == pytest.approx((0.04 - 0.018) / 0.018, abs=1e-6)  # 122% up
    assert harm.low == pytest.approx((wilson.ci_low - 0.018) / 0.018, abs=1e-6)
    assert harm.high == pytest.approx((wilson.ci_high - 0.018) / 0.018, abs=1e-6)
    assert harm.tier == "shown"


def test_a_rate_just_past_the_tolerance_with_a_wide_interval_is_possible_only() -> None:
    found = baseline_reference(
        [1.0] * 20 + [0.0] * 980,
        baseline=0.018,
        kind="binary",
        direction="increase",
        tolerance=0.10,
    )

    harm = found.harm
    assert harm is not None and harm.tier == "possible"
    assert 0.10 < harm.point < 0.12 and harm.low < 0 < harm.high


@pytest.mark.parametrize("n", [2, 3, 30, 200, 5000])
def test_a_group_whose_values_are_all_the_same_has_an_interval_with_no_width_and_says_so(
    n: int,
) -> None:
    found = baseline_reference(
        [0.0] * n, baseline=3.0, kind="continuous", direction="decrease", tolerance=0.10
    )

    harm = found.harm
    assert harm is not None and harm.no_variation
    assert (harm.point, harm.low, harm.high) == (1.0, 1.0, 1.0)  # every player has 0 sessions
    assert harm.measured == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("n", [2, 3, 30])
def test_an_interval_with_no_width_is_held_when_there_is_nothing_to_compare_with(n: int) -> None:
    """With no group to compare with, the chance that so many players are all alike cannot be
    worked out, so the reading is held to possible at any size and says it was held back (with
    a comparison group, `chance_all_alike` decides: see the tests below)."""
    harm = baseline_reference(
        [0.0] * n, baseline=3.0, kind="continuous", direction="decrease", tolerance=0.10
    ).harm

    assert harm is not None
    assert harm.tier == "possible" and harm.capped_by == "no_variation"
    assert harm.uncapped_tier == "shown"


def test_a_group_with_the_same_value_beyond_the_tolerance_on_the_good_side_is_not_capped() -> None:
    harm = baseline_reference(
        [4.0] * 30, baseline=3.0, kind="continuous", direction="decrease", tolerance=0.10
    ).harm

    assert harm is not None and harm.no_variation and harm.tier == "within"
    assert harm.capped_by is None and harm.uncapped_tier is None


def test_the_constants_mean_is_the_mean_of_its_values_and_is_not_one_of_them() -> None:
    values = [0.7] * 3  # fsum([0.7] * 3) / 3 is not 0.7 to the last bit

    harm = baseline_reference(
        values, baseline=1.0, kind="continuous", direction="decrease", tolerance=0.1
    ).harm

    assert harm is not None and harm.no_variation
    assert harm.measured == (math.fsum(values) / 3,) * 3


def test_a_share_too_large_to_represent_is_not_measured_rather_than_infinite() -> None:
    values = [1e150, 2e150] * 10  # against a baseline of 1e-300 the share is beyond any float

    found = baseline_reference(
        values, baseline=1e-300, kind="continuous", direction="decrease", tolerance=0.1, group="b"
    )

    assert found.harm is None
    assert found.reason == (
        "the values of b cannot be measured (a value is not a finite number, or is too large "
        "or too small)"
    )


def test_values_too_close_together_to_have_a_spread_are_not_called_the_same_value() -> None:
    values = [1e-170 * (1 + i % 3) for i in range(30)]  # the variance underflows to 0

    found = baseline_reference(
        values, baseline=1e-170, kind="continuous", direction="decrease", tolerance=0.10
    )

    assert found.harm is None
    assert found.reason == "the spread of the group is too small to measure"
    control = control_reference(
        values, [v * 2 for v in values], direction="decrease", tolerance=0.1
    )
    assert control.harm is not None  # the ratio is worked out on the scaled values


# --- A revenue-like metric: the baseline reading may not show a fall by itself --------------------

_RIGHT_SKEWED = [0.0] * 90 + [20.0] * 5 + [1.0] * 5  # mean 1.05, interval 0.18 to 1.92


def _skewed(**more):
    options = {
        "baseline": 3.0,
        "kind": "continuous",
        "direction": "decrease",
        "tolerance": 0.10,
        **more,
    }
    return baseline_reference(_RIGHT_SKEWED, **options)


def test_a_revenue_like_fall_against_the_baseline_is_capped_at_possible() -> None:
    plain, capped = _skewed().harm, _skewed(right_skewed=True).harm

    assert plain is not None and capped is not None
    assert plain.tier == "shown" and plain.capped_by is None
    assert (capped.point, capped.low, capped.high) == (plain.point, plain.low, plain.high)
    assert capped.tier == "possible" and capped.capped_by == "heavy_tail"
    assert capped.uncapped_tier == "shown" and not capped.no_variation


def test_the_cap_for_a_revenue_like_metric_is_only_for_a_fall_that_is_harmful() -> None:
    """For a rise the one-sample t interval errs on the cautious side (it hardly ever lies wholly
    above the true mean), so nothing is held back."""
    rising = baseline_reference(
        [1.0] * 5 + [0.0] * 95,
        baseline=0.005,
        kind="continuous",
        direction="increase",
        tolerance=0.10,
        right_skewed=True,
    ).harm

    assert rising is not None and rising.tier == "shown" and rising.capped_by is None


def test_the_cap_does_not_apply_to_a_rate_or_to_a_point_that_is_only_possible() -> None:
    rate = baseline_reference(
        [0.0] * 1000,
        baseline=0.05,
        kind="binary",
        direction="decrease",
        tolerance=0.10,
        right_skewed=True,
    ).harm
    only_possible = _skewed(right_skewed=True, tolerance=0.50).harm

    assert rate is not None and rate.tier == "shown" and rate.capped_by is None
    assert only_possible is not None and only_possible.tier == "possible"
    assert only_possible.capped_by is None and only_possible.uncapped_tier is None


def test_when_both_caps_apply_the_missing_width_is_the_reason_given() -> None:
    harm = baseline_reference(
        [0.0] * 40,
        baseline=3.0,
        kind="continuous",
        direction="decrease",
        tolerance=0.10,
        right_skewed=True,
    ).harm

    assert harm is not None and harm.capped_by == "no_variation"


def test_a_harm_of_exactly_zero_is_zero_and_not_minus_zero() -> None:
    for direction in ("increase", "decrease"):
        harm = _harm_of(direction, (0.0, 0.0, 0.0), tolerance=0.10)

        assert all(math.copysign(1.0, x) == 1.0 for x in (harm.point, harm.low, harm.high))
    tiny = _harm_of("decrease", (1e-9, 1e-9, 1e-9), tolerance=0.10)
    assert str(tiny.point) == "0.0" and str(tiny.low) == "0.0"


@pytest.mark.parametrize(
    ("point", "tier"), [(0.1000004, "within"), (0.1000006, "possible"), (0.099999, "within")]
)
def test_the_decision_is_made_on_the_figures_rounded_to_six_places(point, tier) -> None:
    harm = _harm_of("increase", (point, -0.5, point + 0.1), tolerance=0.10)

    assert harm.tier == tier and harm.point == round(point, 6)


@pytest.mark.parametrize(
    ("direction", "tolerance", "kind", "baseline", "unreachable"),
    [
        ("decrease", 1.0, "continuous", 3.0, ("control", "baseline")),  # a fall is at most 100%
        ("decrease", 10.0, "binary", 0.02, ("control", "baseline")),  # a tolerance of "10" for 10%
        ("decrease", 0.99, "continuous", 3.0, ()),
        ("increase", 10.0, "continuous", 3.0, ()),  # a mean can rise without limit
        ("increase", 10.0, "binary", 0.02, ()),  # 0.02 x 11 < 1
        ("increase", 1.0, "binary", 0.5, ("baseline",)),  # a rate of 0.5 cannot more than double
        ("increase", 1.5, "binary", 0.5, ("baseline",)),
        ("increase", 0.9, "binary", 0.5, ()),  # 0.5 x 1.9 < 1: reachable
    ],
)
def test_a_tolerance_beyond_the_largest_possible_harm_is_known_without_the_data(
    direction, tolerance, kind, baseline, unreachable
) -> None:
    found = _test(
        None,
        None,
        harmful_direction=direction,
        tolerance=tolerance,
        kind=kind,
        baseline=baseline,
    )

    assert found.unreachable == unreachable


@pytest.mark.parametrize(
    ("values", "baseline", "kind", "reason"),
    [
        ([1.0, 2.0, 3.0], 0.0, "continuous", "the registered baseline is not above 0"),
        ([1.0, 2.0, 3.0], -2.0, "continuous", "the registered baseline is not above 0"),
        ([1.0], 3.0, "continuous", "the group has fewer than 2 players"),
        ([], 3.0, "continuous", "the group has no players"),
        ([], 0.02, "binary", "the group has no players"),
        ([1.0, 2.0, math.nan], 3.0, "continuous", "finite"),
    ],
)
def test_the_baseline_reference_says_why_it_could_not_be_measured(
    values, baseline, kind, reason
) -> None:
    found = baseline_reference(
        values, baseline=baseline, kind=kind, direction="decrease", tolerance=0.10
    )

    assert found.harm is None and found.reason is not None and reason in found.reason


def test_a_single_player_gives_a_rate_but_not_a_mean() -> None:
    rate = baseline_reference(
        [1.0], baseline=0.5, kind="binary", direction="decrease", tolerance=0.10
    )
    mean = baseline_reference(
        [1.0], baseline=0.5, kind="continuous", direction="decrease", tolerance=0.10
    )

    assert rate.harm is not None and mean.harm is None


# --- The two together --------------------------------------------------------------------------


def _harm(tier: str, point: float = 0.2) -> Harm:
    return Harm(
        point=point,
        low=0.0,
        high=0.4,
        tier=tier,  # type: ignore[arg-type]
        not_verified=False,
        reference_value=3.0,
        measured=(2.4, 2.0, 2.8),
    )


def _test(control: Harm | None, against_baseline: Harm | None, own: Harm | None = None, **more):
    def result(name, harm):
        return ReferenceResult(
            reference=name, harm=harm, reason=None if harm else "could not be measured"
        )

    fields = {
        "arm": "variant_b",
        "guardrail": "sessions_7d",
        "kind": "continuous",
        "harmful_direction": "decrease",
        "tolerance": 0.10,
        "baseline": 3.0,
        "n_arm": 500,
        "n_control": 500,
        "mean_arm": 2.4,
        "mean_control": 3.0,
        "events_arm": None,
        "events_control": None,
    }
    return GuardrailTest(
        **{**fields, **more},
        control=result("control", control),
        baseline_reference=result("baseline", against_baseline),
        control_on_baseline=result("baseline", own),
    )


@pytest.mark.parametrize(
    ("control", "baseline", "tier", "status", "decided_by", "agree"),
    [
        ("shown", "shown", "shown", "breach_shown", ("control", "baseline"), True),
        ("shown", "possible", "shown", "breach_shown", ("control",), False),
        ("possible", "shown", "shown", "breach_shown", ("baseline",), False),
        ("possible", "within", "possible", "breach_possible", ("control",), False),
        ("within", "possible", "possible", "breach_possible", ("baseline",), False),
        ("possible", "possible", "possible", "breach_possible", ("control", "baseline"), True),
        ("within", "within", "within", "within_tolerance", ("control", "baseline"), True),
        (None, "shown", "shown", "breach_shown", ("baseline",), None),
        ("possible", None, "possible", "breach_possible", ("control",), None),
        (None, "within", "within", "within_tolerance", ("baseline",), None),
    ],
)
def test_the_stricter_reference_decides_and_the_other_is_named(
    control, baseline, tier, status, decided_by, agree
) -> None:
    found = _test(_harm(control) if control else None, _harm(baseline) if baseline else None)

    assert found.tier == tier and found.status == status
    assert found.decided_by == decided_by and found.references_agree is agree


def test_when_neither_reference_could_be_measured_the_comparison_is_not_evaluated() -> None:
    found = _test(None, None)

    assert found.tier is None and found.status == "not_evaluated"
    assert found.decided_by == () and found.references_agree is None


@pytest.mark.parametrize(
    ("own", "moved"), [("shown", True), ("possible", True), ("within", False), (None, False)]
)
def test_a_control_beyond_the_baselines_tolerance_means_the_baseline_has_moved(own, moved) -> None:
    found = _test(_harm("within"), _harm("shown"), _harm(own) if own else None)

    assert found.baseline_has_moved is moved


@pytest.mark.parametrize(
    ("events_arm", "events_control", "n", "small"),
    [
        (SMALL_COUNT, SMALL_COUNT, 1000, False),
        (SMALL_COUNT - 1, 100, 1000, True),
        (100, SMALL_COUNT - 1, 1000, True),
        (100, 100, 105, True),  # fewer than 10 players without the outcome
        (500, 500, 1000, False),
    ],
)
def test_a_binary_guardrail_with_few_players_on_either_side_of_its_rate_is_rough(
    events_arm, events_control, n, small
) -> None:
    found = _test(
        None,
        None,
        kind="binary",
        n_arm=n,
        n_control=n,
        events_arm=events_arm,
        events_control=events_control,
    )

    assert found.small_counts is small
    assert _test(None, None, events_arm=1, events_control=1).small_counts is False  # continuous


# --- Reading a context ----------------------------------------------------------------------


def test_every_arm_but_control_is_read_on_every_guardrail_in_the_specs_order(raw_spec) -> None:
    rows = (
        _sessions("control", [3] * 50 + [4] * 50)
        + _sessions("variant_b", [3] * 40 + [4] * 60)
        + [Row(f"p_{i}", "control", purchases=i % 2) for i in range(10)]
    )
    context = _context(raw_spec, rows, SESSIONS, PURCHASED)

    tests = guardrail_tests(context)

    assert [(t.guardrail, t.arm) for t in tests] == [
        ("sessions_7d", "variant_b"),
        ("purchased_7d", "variant_b"),
    ]
    assert tests[0].kind == "continuous" and tests[1].kind == "binary"
    assert tests[0].events_arm is None and tests[1].events_arm is not None


def test_a_spec_without_guardrails_has_no_tests(raw_spec) -> None:
    context = _context(raw_spec, _sessions("control", [3, 4]) + _sessions("variant_b", [3, 5]))

    assert guardrail_tests(context) == []


def test_three_arms_give_a_test_each_and_share_the_controls_own_position(raw_spec) -> None:
    rows = (
        _sessions("control", [3, 4, 2, 5] * 30)
        + _sessions("variant_b", [3, 4, 2, 5] * 30)
        + _sessions("variant_c", [1, 2, 1, 2] * 30)
    )
    spec = results_spec(raw_spec, guardrails=[SESSIONS], **REVENUE)  # the three-arm default
    tests = guardrail_tests(ResultsContext.of(spec, build_data(rows)))

    assert [t.arm for t in tests] == ["variant_b", "variant_c"]
    assert tests[0].control_on_baseline is tests[1].control_on_baseline
    assert tests[0].status == "within_tolerance" and tests[1].status == "breach_shown"


def test_only_the_analysed_players_are_read_and_their_means_and_counts_are_given(raw_spec) -> None:
    rows = _sessions("control", [3] * 60 + [5] * 40) + _sessions("variant_b", [2] * 70 + [4] * 30)
    # first exposed after their first purchase: not analysed (design section 21.3)
    late = Row("late_000", "variant_b", sessions=1000, purchases=1, first_purchase_at=at())
    context = _context(raw_spec, rows + [late], SESSIONS)

    (found,) = guardrail_tests(context)

    assert (found.n_arm, found.n_control) == (100, 100)
    assert found.mean_arm == pytest.approx(2.6) and found.mean_control == pytest.approx(3.8)
    assert (found.baseline, found.tolerance, found.harmful_direction) == (3.0, 0.10, "decrease")


def test_a_breach_against_the_baseline_that_the_control_shares_is_marked_as_a_moved_baseline(
    raw_spec,
) -> None:
    # both arms sit near 2 sessions against a registered baseline of 3: the baseline moved
    rows = _sessions("control", [2, 2, 3, 1] * 60) + _sessions("variant_b", [2, 2, 3, 1] * 60)
    context = _context(raw_spec, rows, SESSIONS)

    (found,) = guardrail_tests(context)

    assert found.control.harm is not None and found.control.harm.tier == "within"
    assert found.baseline_reference.harm is not None
    assert found.baseline_reference.harm.tier == "shown"
    assert found.status == "breach_shown" and found.decided_by == ("baseline",)
    assert found.references_agree is False and found.baseline_has_moved


def test_a_real_regression_is_seen_by_both_references(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [2, 3, 1, 2] * 80)
    context = _context(raw_spec, rows, SESSIONS)

    (found,) = guardrail_tests(context)

    assert found.control.harm is not None and found.control.harm.tier == "shown"
    assert found.baseline_reference.harm is not None
    assert found.baseline_reference.harm.tier == "shown"
    assert found.references_agree is True and not found.baseline_has_moved
    assert found.decided_by == ("control", "baseline")


def test_an_arm_with_one_player_is_not_evaluated_on_either_reference(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1])
    context = _context(raw_spec, rows, SESSIONS)

    (found,) = guardrail_tests(context)

    assert found.status == "not_evaluated"
    assert found.control.reason == "variant_b has fewer than 2 players"
    assert found.baseline_reference.reason == "variant_b has fewer than 2 players"


def test_a_tiny_registered_baseline_is_still_a_baseline(raw_spec) -> None:
    tiny = {**SESSIONS, "baseline": 0.0001}
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1, 2, 1, 2] * 20)

    (found,) = guardrail_tests(_context(raw_spec, rows, tiny))

    assert found.baseline_reference.harm is not None
    assert found.baseline_reference.harm.tier == "within"  # the arm is far above the baseline


def test_a_registered_baseline_that_is_not_above_zero_is_not_a_share_of_anything(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 20) + _sessions("variant_b", [1, 2, 1, 2] * 20)

    (found,) = guardrail_tests(_context(raw_spec, rows, {**SESSIONS, "baseline": 0.0}))

    assert (
        found.baseline_reference.harm is None and "not above 0" in found.baseline_reference.reason
    )
    assert found.control.harm is not None and found.status == "breach_shown"  # the control decides


def test_the_guardrail_tests_do_not_depend_on_where_control_is_in_the_spec(raw_spec) -> None:
    rows = _sessions("control", [3, 4, 2, 3] * 80) + _sessions("variant_b", [2, 3, 1, 2] * 80)

    first = guardrail_tests(_context(raw_spec, rows, SESSIONS))
    swapped = guardrail_tests(_context(raw_spec, rows, SESSIONS, arms=list(reversed(TWO_ARMS))))

    assert first == swapped


# --- Whether an interval with no width is believed ------------------------------------------------

_CONTROL_2_PERCENT = [0.0] * 294 + [10.0] * 6  # 2% of control's players buy


def _all_zero(n: int, against=None):
    return baseline_reference(
        [0.0] * n,
        baseline=0.2,
        kind="continuous",
        direction="decrease",
        tolerance=0.10,
        against=against,
    ).harm


def test_the_chance_of_so_many_players_alike_is_the_share_at_that_value_to_the_power() -> None:
    other = [0.0] * 98 + [5.0] * 2

    assert _chance_all_alike([0.0] * 3, other) == pytest.approx(0.98**3)
    assert _chance_all_alike([5.0] * 2, other) == pytest.approx(0.02**2)
    assert _chance_all_alike([7.0] * 5, other) == 0.0  # nobody in the other group has it
    assert _chance_all_alike([0.0] * 5, []) == 1.0  # nothing to compare with: nothing concluded
    assert _chance_all_alike([0.1 + 0.2] * 2, [0.3] * 4 + [1.0] * 4) == pytest.approx(0.25)


@pytest.mark.parametrize(("n", "held"), [(3, True), (30, True), (200, False), (300, False)])
def test_players_all_at_zero_are_believed_when_chance_cannot_explain_them(n, held) -> None:
    """With 2 in 100 players buying, 30 players are all at 0 more than half of the time, and 200
    in under 2% of samples (0.98 to the 200th is 0.0176)."""
    harm = _all_zero(n, against=_CONTROL_2_PERCENT)

    assert harm is not None and harm.no_variation and harm.constant_group == "arm"
    assert harm.chance_all_alike == pytest.approx(0.98**n)
    assert (harm.tier, harm.capped_by) == (
        ("possible", "no_variation") if held else ("shown", None)
    )
    assert harm.uncapped_tier == ("shown" if held else None)


def test_players_all_at_a_value_that_control_never_has_are_believed_at_any_size() -> None:
    sessions = [3.0, 4.0, 2.0, 3.0] * 25  # nobody has 0 sessions

    harm = baseline_reference(
        [0.0] * 5,
        baseline=3.0,
        kind="continuous",
        direction="decrease",
        tolerance=0.1,
        against=sessions,
    ).harm

    assert harm is not None and harm.chance_all_alike == 0.0 and harm.tier == "shown"


def test_without_a_comparison_group_an_interval_with_no_width_is_always_held() -> None:
    harm = _all_zero(5000, against=None)

    assert harm is not None and harm.chance_all_alike is None
    assert (harm.tier, harm.capped_by) == ("possible", "no_variation")


@pytest.mark.parametrize(
    ("chance", "tier"),
    [(CHANCE_LEVEL, "possible"), (CHANCE_LEVEL * 0.999, "shown"), (1.0, "possible")],
)
def test_chance_that_is_not_below_the_level_holds_the_reading(chance, tier) -> None:
    harm = _raw_harm(
        "increase",
        (0.5, 0.4, 0.6),
        tolerance=0.10,
        reference_value=1.0,
        measured=(1.5, 1.4, 1.6),
        constant_group="arm",
        chance_all_alike=chance,
    )

    assert harm.tier == tier


def test_the_level_of_chance_is_one_tail_of_the_interval() -> None:
    assert CHANCE_LEVEL == ALPHA / 2 == 0.025


def test_a_constant_arm_in_the_ratio_to_control_is_held_when_chance_explains_it() -> None:
    control = [2.0, 3.0, 3.0, 3.0, 4.0] * 20  # one in five has exactly 2 sessions

    held = control_reference([2.0, 2.0], control, direction="decrease", tolerance=0.1)
    believed = control_reference([2.0] * 6, control, direction="decrease", tolerance=0.1)

    assert held.harm is not None and believed.harm is not None
    assert held.harm.constant_group == "arm" and held.harm.chance_all_alike == pytest.approx(0.04)
    assert (held.harm.tier, held.harm.capped_by) == ("possible", "no_variation")
    assert held.harm.uncapped_tier == "shown"
    assert believed.harm.chance_all_alike == pytest.approx(0.2**6)
    assert (believed.harm.tier, believed.harm.capped_by) == ("shown", None)


def test_a_constant_control_is_held_in_the_same_way_and_named() -> None:
    arm = [2.0, 3.0, 3.0, 3.0] * 25  # a quarter of the arm is at control's value

    believed = control_reference(arm, [2.0] * 30, direction="increase", tolerance=0.1)
    held = control_reference(arm, [2.0] * 2, direction="increase", tolerance=0.1)
    nobody = control_reference(arm, [4.0] * 3, direction="decrease", tolerance=0.1)

    assert believed.harm is not None and held.harm is not None and nobody.harm is not None
    assert believed.harm.constant_group == "control" and nobody.harm.chance_all_alike == 0.0
    assert believed.harm.chance_all_alike == pytest.approx(0.25**30)
    assert (believed.harm.tier, believed.harm.capped_by) == ("shown", None)
    assert held.harm.chance_all_alike == pytest.approx(0.25**2)
    assert (held.harm.tier, held.harm.capped_by) == ("possible", "no_variation")


def test_groups_that_both_vary_are_never_held_for_want_of_width() -> None:
    found = control_reference(
        [2.0, 3.0, 2.0, 3.0] * 10, [4.0, 5.0, 4.0, 5.0] * 10, direction="decrease", tolerance=0.1
    )

    assert found.harm is not None and found.harm.constant_group is None
    assert found.harm.chance_all_alike is None and not found.harm.no_variation


# --- The end of an interval past what is possible --------------------------------------------


@pytest.mark.parametrize(("tolerance", "not_verified"), [(1.0, False), (1.5, False), (0.9, True)])
def test_an_interval_past_the_whole_of_the_reference_does_not_leave_a_breach_open(
    tolerance, not_verified
) -> None:
    """A t interval of a non-negative mean can run below 0; the fall it allows is then more than
    the whole of the baseline, which no fall can be."""
    values = [0.0] * 98 + [100.0] * 2  # mean 2.0 with an interval from below 0

    harm = baseline_reference(
        values, baseline=2.0, kind="continuous", direction="decrease", tolerance=tolerance
    ).harm

    assert harm is not None and harm.tier == "within" and harm.high > 1.0
    assert harm.not_verified is not_verified


def test_a_rise_has_no_such_bound() -> None:
    values = [0.0] * 98 + [100.0] * 2

    harm = baseline_reference(
        values, baseline=2.0, kind="continuous", direction="increase", tolerance=1.0
    ).harm

    assert harm is not None and harm.tier == "within" and harm.high > 1.0 and harm.not_verified


# --- Rounded figures decide, at both ends -----------------------------------------------------


@pytest.mark.parametrize(("low", "tier"), [(0.1000004, "possible"), (0.1000006, "shown")])
def test_the_tier_is_decided_on_the_rounded_low_end(low, tier) -> None:
    harm = _harm_of("increase", (0.5, low, 0.9), tolerance=0.10)

    assert harm.tier == tier and harm.low == round(low, 6)


@pytest.mark.parametrize(("high", "not_verified"), [(0.1000004, False), (0.1000006, True)])
def test_not_verified_is_decided_on_the_rounded_high_end(high, not_verified) -> None:
    harm = _harm_of("increase", (0.04, -0.2, high), tolerance=0.10)

    assert harm.tier == "within" and harm.not_verified is not_verified


# --- Numbers that cannot be represented -------------------------------------------------------


def test_the_mean_of_a_group_is_none_unless_it_can_be_represented() -> None:
    assert _mean([1.0, 2.0]) == 1.5
    assert _mean([]) is None
    assert _mean([math.inf, 1.0]) is None
    assert _mean([1.7e308, 1e308, 1.5e308]) is None  # the sum overflows and they differ
    assert _mean([1.7e308] * 30) == 1.7e308  # the sum overflows, and their mean is their value


@pytest.mark.parametrize(
    ("arm", "control"),
    [
        ([1e-180, 2e-180] * 10, [1e150, 2e150] * 10),  # the ratio is far below any float
        ([1.92e150, 2.88e150] * 10, [1e-158, 2e-158] * 10),
        ([0.0] * 30, [1.7e308] * 30),
    ],
)
def test_a_ratio_beyond_the_floats_is_not_measured_and_is_not_blamed_on_a_zero_mean(
    arm, control
) -> None:
    found = control_reference(arm, control, direction="decrease", tolerance=0.1)

    assert found.reason is not None
    assert "control's mean is not above 0" not in found.reason
    if found.harm is None:
        assert "cannot be measured" in found.reason or "no logarithm" in found.reason


def test_a_constant_group_whose_sum_overflows_is_measured_at_its_value_and_not_at_zero() -> None:
    found = baseline_reference(
        [1.7e308] * 30, baseline=1.0, kind="continuous", direction="decrease", tolerance=0.1
    )

    assert found.harm is not None and found.harm.no_variation
    assert found.harm.measured == (1.7e308,) * 3 and found.harm.tier == "within"


def test_values_that_differ_and_are_too_large_to_square_are_not_measured() -> None:
    found = baseline_reference(
        [1.7e308, 1e308] * 15, baseline=1.0, kind="continuous", direction="decrease", tolerance=0.1
    )

    assert found.harm is None and "cannot be measured" in (found.reason or "")


def test_a_rate_of_values_that_are_not_finite_is_not_measured() -> None:
    found = baseline_reference(
        [math.inf] + [0.0] * 29, baseline=0.1, kind="binary", direction="increase", tolerance=0.1
    )

    assert found.harm is None and "cannot be measured" in (found.reason or "")


def test_an_empty_group_has_no_rate_to_be_rough() -> None:
    found = _test(
        None, None, kind="binary", n_arm=500, n_control=0, events_arm=250, events_control=0
    )

    assert found.small_counts is False


def test_the_own_reading_of_control_names_control_as_the_group_with_no_width() -> None:
    own = baseline_reference(
        [3.0] * 10,
        baseline=3.0,
        kind="continuous",
        direction="decrease",
        tolerance=0.1,
        group="control",
    )
    arm = baseline_reference(
        [3.0] * 10, baseline=3.0, kind="continuous", direction="decrease", tolerance=0.1, group="b"
    )

    assert own.harm is not None and own.harm.constant_group == "control"
    assert arm.harm is not None and arm.harm.constant_group == "arm"


def test_the_chance_could_explain_unless_it_is_known_and_below_the_level() -> None:
    assert chance_could_explain(None) and chance_could_explain(1.0)
    assert chance_could_explain(CHANCE_LEVEL) and not chance_could_explain(CHANCE_LEVEL * 0.999)
    assert not chance_could_explain(0.0)


def test_controls_own_reading_is_judged_against_the_arms_and_not_held_always() -> None:
    """100 control players all at 0 are as much a collapse of the baseline as 99 at 0 and one
    at 1: with arms that have nobody at 0 neither is held."""
    rows_arm = [3.0, 4.0, 2.0, 3.0] * 25

    def own(control):
        return baseline_reference(
            control,
            baseline=3.0,
            kind="continuous",
            direction="decrease",
            tolerance=0.1,
            group="control",
            against=rows_arm,
        ).harm

    all_zero, nearly = own([0.0] * 100), own([0.0] * 99 + [1.0])

    assert all_zero is not None and nearly is not None
    assert all_zero.tier == nearly.tier == "shown" and all_zero.capped_by is None


def test_controls_own_place_is_compared_with_the_arms_and_not_with_itself(raw_spec) -> None:
    """Two control players at 5 sessions: one arm player in ten has 5, so two alike is one time
    in a hundred. Counted with control's own two players it would be one in sixteen."""
    rows = _sessions("control", [5, 5]) + _sessions("variant_b", [5] + [1] * 9)
    guardrail = {**SESSIONS, "harmful_direction": "increase"}

    (found,) = guardrail_tests(_context(raw_spec, rows, guardrail))

    own = found.control_on_baseline.harm
    assert own is not None and own.constant_group == "control"
    assert own.chance_all_alike == pytest.approx(0.1**2)
    assert (own.tier, own.capped_by) == ("shown", None)
