"""The cohort-trigger simulation measures what the rule computes (design section 21.5)."""

import inspect
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
import scipy
from cohort_simulation import (
    BASE,
    EQUAL_PLAYERS,
    FLOOR_MULTIPLES,
    HEAVY_COHORTS,
    LEVEL,
    LOCATION_OUTCOMES,
    LOG_SD,
    NULL_SCENARIOS,
    OUTCOMES,
    PAYING,
    REPLICATION,
    SCENARIOS,
    SHAPE_SIZES,
    SHIFT_COHORTS,
    SHIFT_OUTCOMES,
    SHIFT_PLAYERS,
    SPEND_SD,
    SPLITS,
    TAILED,
    Cell,
    _printed_chunk,
    cell_flags,
    draw,
    flags,
    grid,
    heavy_grid,
    means,
    null_se_shift,
    p_values,
    population_sd,
    printed_grid,
    printed_shifts,
    render,
    run_cell,
    run_printed,
    shape_sample,
    study,
    tail_shapes,
)
from scipy import stats

from referee.cohort_effects import (
    NULL_FLAG_RATE_MAX,
    NULL_FLAG_RATE_MEAN,
    POWER,
    CohortTest,
    _scale_test,
    detectable_shifts,
    low_information,
    registered_mde,
    trigger,
)
from referee.cohorts import raised_floor
from referee.methods import cohort_detectable_shift, heavy_tail_measures

pytestmark = pytest.mark.study  # re-runs simulations; run with `pytest -m study`


def _real(arm: np.ndarray, control: np.ndarray) -> dict[str, np.ndarray]:
    """The same four p values from the rule's own code, replication by replication."""
    reps, k, _ = arm.shape
    out = {name: np.full(reps, np.nan) for name in ("q_abs", "s_abs", "q_log", "s_log")}
    blocks = list(range(k))
    for r in range(reps):
        treatment = {b: list(arm[r, b]) for b in blocks}
        reference = {b: list(control[r, b]) for b in blocks}
        for scale, q, s in (("absolute", "q_abs", "s_abs"), ("log_ratio", "q_log", "s_log")):
            found = _scale_test(scale, blocks, treatment, reference).heterogeneity
            if found is not None:
                out[q][r], out[s][r] = found.q_p_value, found.slope_p_value
    return out


def _real_trigger(arm: np.ndarray, control: np.ndarray, arms: int) -> np.ndarray:
    """Whether the rule's own `trigger` flags each replication."""
    reps, k, _ = arm.shape
    blocks = list(range(k))
    flagged = np.zeros(reps, bool)
    for r in range(reps):
        treatment = {b: list(arm[r, b]) for b in blocks}
        reference = {b: list(control[r, b]) for b in blocks}
        test = CohortTest(
            arm="a",
            control="c",
            metric="m",
            block_days=7,
            absolute=_scale_test("absolute", blocks, treatment, reference),
            log_ratio=_scale_test("log_ratio", blocks, treatment, reference),
        )
        flagged[r] = trigger(test, arms - 1).flagged
    return flagged


@pytest.mark.parametrize("arms", [2, 3, 5])
@pytest.mark.parametrize("outcome", OUTCOMES)
def test_the_simulated_flags_are_the_rules_own_trigger(outcome: str, arms: int) -> None:
    cell = Cell(outcome, 6, 150 if outcome == "lognormal" else 40, arms, "fade")
    control_mean, (arm_mean, *_) = means(cell)
    rng = np.random.default_rng(13)
    control = draw(outcome, control_mean, cell.n, rng, 150)
    arm = draw(outcome, arm_mean * 1.0, cell.n, rng, 150)

    ours = flags(p_values(arm, control), cell.level)["both"]
    real = _real_trigger(arm, control, arms)

    assert (ours == real).all()
    if outcome != "binary":  # a fade is too faint for 40 binary players a cohort
        assert 10 < real.sum() < 150  # a mixture of flagged and not, so the check bites


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("scenario", ["zero", "relative_drift", "fade"])
def test_the_vectorised_p_values_are_the_rules_own(outcome: str, scenario: str) -> None:
    cell = Cell(outcome, 5, 40, 2, scenario)
    control_mean, (arm_mean,) = means(cell)
    rng = np.random.default_rng(7)
    control = draw(outcome, control_mean, cell.n, rng, 40)
    arm = draw(outcome, arm_mean, cell.n, rng, 40)

    ours, real = p_values(arm, control), _real(arm, control)

    for name in ours:
        np.testing.assert_allclose(ours[name], real[name], rtol=1e-9, atol=0, equal_nan=True)


def test_cohorts_that_give_no_estimate_are_left_out_exactly_as_the_rule_leaves_them_out() -> None:
    rng = np.random.default_rng(11)
    cell = Cell("binary", 6, 30, 2, "zero")
    control_mean, (arm_mean,) = means(cell)
    control = draw("binary", control_mean * 0.15, cell.n, rng, 120)  # rates near 1.5%: many zeros
    arm = draw("binary", arm_mean * 0.15, cell.n, rng, 120)
    # Force the three cases: no variation, a zero mean in one arm, and everything fine.
    control[0, 1, :], arm[0, 1, :] = 0.0, 0.0
    control[1, 2, :], arm[1, 2, :] = 0.0, rng.random(30) < 0.3
    ours, real = p_values(arm, control), _real(arm, control)

    assert np.isnan(ours["q_log"]).sum() > 5  # the cases were reached
    for name in ours:
        np.testing.assert_allclose(ours[name], real[name], rtol=1e-9, atol=0, equal_nan=True)
        assert (np.isnan(ours[name]) == np.isnan(real[name])).all()


def test_the_flags_follow_the_rule_q_or_slope_on_each_scale_and_both_scales() -> None:
    p = {
        "q_abs": np.array([0.01, 0.5, 0.01, 0.5, np.nan]),
        "s_abs": np.array([0.5, 0.01, 0.5, 0.5, 0.5]),
        "q_log": np.array([0.01, 0.01, 0.5, 0.5, 0.01]),
        "s_log": np.array([0.5, 0.5, 0.5, 0.5, 0.01]),
    }

    found = flags(p, 0.025)

    assert found["absolute"].tolist() == [True, True, True, False, False]
    assert found["relative"].tolist() == [True, True, False, False, True]
    assert found["both"].tolist() == [True, True, False, False, False]
    assert found["q_both"].tolist() == [True, False, False, False, False]
    assert flags(p, 0.005)["both"].tolist() == [False] * 5  # nothing is below 0.005


def test_a_level_is_a_strict_threshold() -> None:
    p = dict.fromkeys(("q_abs", "s_abs", "q_log", "s_log"), np.array([0.025]))

    at_level, above = flags(p, 0.025), flags(p, 0.0250001)

    for name in ("q_abs", "s_abs", "q_log", "s_log", "absolute", "relative", "both", "q_both"):
        assert at_level[name].tolist() == [False], name
        assert above[name].tolist() == [True], name


# --- The streams and the scenarios ------------------------------------------------------------


def test_the_first_replications_of_a_cell_are_the_same_whatever_the_total() -> None:
    cell = Cell("poisson", 4, 30, 3, "relative_drift")

    short = cell_flags(cell, 250, seed=5)
    long = cell_flags(cell, 700, seed=5)

    for name in short:
        assert short[name].shape == (250, 2) and long[name].shape == (700, 2)
        assert (short[name] == long[name][:250]).all()


def test_a_run_is_reproducible_and_depends_on_the_seed_and_the_cell() -> None:
    cell = Cell("normal", 4, 30, 2, "zero")

    assert run_cell(cell, 500, 3) == run_cell(cell, 500, 3)
    assert run_cell(cell, 500, 3) != run_cell(cell, 500, 4)
    assert run_cell(cell, 500, 3) != run_cell(Cell("normal", 4, 30, 2, "relative"), 500, 3)


def test_the_level_is_divided_by_the_number_of_non_control_arms() -> None:
    from referee.cohort_effects import TRIGGER_LEVEL

    assert LEVEL == TRIGGER_LEVEL == 0.025
    assert Cell("normal", 4, 30, 2, "zero").level == LEVEL
    assert Cell("normal", 4, 30, 3, "zero").level == LEVEL / 2
    assert Cell("normal", 4, 30, 5, "zero").level == LEVEL / 4


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_each_outcome_is_drawn_with_the_mean_it_is_given(outcome: str) -> None:
    mean = np.array([BASE[outcome], 2 * BASE[outcome] if outcome != "binary" else 0.3])
    sample = draw(outcome, mean, 400, np.random.default_rng(1), 200)

    assert sample.shape == (200, 2, 400)
    observed = sample.mean(axis=(0, 2))
    np.testing.assert_allclose(observed, mean, rtol=0.03)


def test_the_outcomes_have_the_shapes_they_are_named_for() -> None:
    rng = np.random.default_rng(2)
    rows = {o: draw(o, np.array([BASE[o]]), 4000, rng, 50).reshape(-1) for o in OUTCOMES}

    assert rows["normal"].std() == pytest.approx(4.0, rel=0.03)
    assert rows["poisson"].var() == pytest.approx(BASE["poisson"], rel=0.05)
    assert set(np.unique(rows["binary"])) == {0.0, 1.0}
    skew = ((rows["lognormal"] - rows["lognormal"].mean()) ** 3).mean() / rows[
        "lognormal"
    ].std() ** 3
    assert skew > 3 and (rows["lognormal"] > 0).all()
    assert (rows["poisson"] == np.round(rows["poisson"])).all()


def test_the_scenarios_set_the_control_and_arm_means_they_describe() -> None:
    def pair(scenario: str, outcome: str = "normal", k: int = 5):
        control, (arm,) = means(Cell(outcome, k, 30, 2, scenario))
        return control, arm

    base = BASE["normal"]
    control, arm = pair("zero")
    assert (control == base).all() and (arm == control).all()
    control, arm = pair("relative")
    assert (control == base).all() and arm == pytest.approx(base * 1.2)
    control, arm = pair("relative_drift")
    assert control[0] == pytest.approx(0.7 * base) and control[-1] == pytest.approx(1.3 * base)
    assert arm == pytest.approx(control * 1.2)
    control, arm = pair("absolute_drift")
    assert arm - control == pytest.approx(0.2 * base)
    control, arm = pair("fade")
    assert (control == base).all()
    assert arm[0] == pytest.approx(1.4 * base) and arm[-1] == pytest.approx(base)
    assert np.diff(arm / control).max() < 0
    assert means(Cell("binary", 4, 30, 3, "relative"))[1][1] == pytest.approx([0.12] * 4)
    with pytest.raises(ValueError, match="unknown scenario"):
        means(Cell("normal", 4, 30, 2, "wobble"))
    with pytest.raises(ValueError, match="unknown outcome"):
        draw("cauchy", np.array([1.0]), 5, np.random.default_rng(0), 2)


def test_every_variant_of_a_three_arm_cell_has_its_own_draws() -> None:
    cell = Cell("normal", 4, 100, 3, "zero")
    found = cell_flags(cell, 2000, seed=9)

    both = found["both"]
    assert both.shape == (2000, 2)
    assert abs(float(np.corrcoef(both[:, 0], both[:, 1])[0, 1])) < 0.3  # shared control only
    assert not math.isclose(float(both[:, 0].mean()), 0.0)


# --- The committed study, and a re-run of some of its cells ---------------------------------------

DOCS = Path(__file__).resolve().parent.parent / "docs"
NULL = json.loads((DOCS / "simulations/cohort_trigger_null.json").read_text(encoding="utf-8"))
FADE = json.loads((DOCS / "simulations/cohort_trigger_fade.json").read_text(encoding="utf-8"))


def _cells(data: dict, **match):
    keep = lambda value, wanted: value in wanted if isinstance(wanted, tuple) else value == wanted  # noqa: E731
    return [c for c in data["cells"] if all(keep(c[k], v) for k, v in match.items())]


def test_the_study_covers_the_whole_grid_with_the_settings_it_says() -> None:
    assert (NULL["reps"], NULL["seed"], FADE["reps"], FADE["seed"]) == (5000, 20261211) * 2
    assert len(NULL["cells"]) == 4 * 4 * 3 * 2 * 4 and len(FADE["cells"]) == 4 * 4 * 3 * 2
    assert {c["scenario"] for c in NULL["cells"]} == set(NULL_SCENARIOS)
    assert {c["scenario"] for c in FADE["cells"]} == {"fade"}
    assert {c["reps"] for c in NULL["cells"] + FADE["cells"]} == {5000}
    assert (
        len({(c["outcome"], c["cohorts"], c["n"], c["arms"], c["scenario"]) for c in NULL["cells"]})
        == 384
    )


def test_the_null_flag_rates_the_findings_quote_are_the_mean_and_maximum_of_the_study() -> None:
    stable = _cells(NULL, arms=2, scenario=("zero", "relative"))
    rates = [c["both"] for c in stable]

    assert len(rates) == 96
    assert NULL_FLAG_RATE_MEAN == round(sum(rates) / len(rates), 4)
    assert NULL_FLAG_RATE_MAX == max(rates)


CHECKED = [
    (Cell("normal", 4, 100, 2, "zero"), ("both", "absolute", "relative")),
    (Cell("poisson", 8, 100, 2, "zero"), ("both", "q_both")),
    (Cell("normal", 8, 100, 3, "zero"), ("both", "any_arm_both")),
    (Cell("lognormal", 8, 30, 2, "zero"), ("both", "relative")),
    (Cell("normal", 8, 100, 2, "relative_drift"), ("both", "absolute")),
    (Cell("normal", 8, 100, 2, "absolute_drift"), ("both", "relative")),
    (Cell("poisson", 8, 100, 2, "fade"), ("both", "q_both", "absolute")),
]


@pytest.mark.parametrize(("cell", "names"), CHECKED, ids=lambda x: getattr(x, "scenario", ""))
def test_a_rerun_of_a_cell_agrees_with_the_committed_study(
    cell: Cell, names: tuple[str, ...]
) -> None:
    data = FADE if cell.scenario == "fade" else NULL
    (stored,) = _cells(
        data,
        outcome=cell.outcome,
        cohorts=cell.cohorts,
        n=cell.n,
        arms=cell.arms,
        scenario=cell.scenario,
    )
    reps = 2000
    rerun = run_cell(cell, reps, seed=20261299)  # another seed: an independent sample

    for name in names:
        p = stored[name]
        spread = math.sqrt(max(p * (1 - p), 1e-4) * (1 / reps + 1 / stored["reps"]))
        assert abs(rerun[name] - p) <= 4.5 * spread + 0.002, (name, rerun[name], p)


# --- Unequal arms -------------------------------------------------------------------------------

# (variant, control) players per cohort; the small equal cases are where a cohort has no spread
UNEQUAL = [(120, 40), (40, 120), (60, 60), (90, 10), (3, 3), (4, 4)]


@pytest.mark.parametrize(("n_arm", "n_control"), UNEQUAL)
@pytest.mark.parametrize("outcome", ["normal", "revenue_mild"])
def test_the_vectorised_p_values_are_the_rules_own_when_the_arms_differ_in_size(
    outcome: str, n_arm: int, n_control: int
) -> None:
    cell = Cell(outcome, 5, n_arm, 2, "relative_drift", control_n=n_control)
    control_mean, (arm_mean,) = means(cell)
    rng = np.random.default_rng(17)
    control = draw(outcome, control_mean, cell.control_players, rng, 40)
    arm = draw(outcome, arm_mean, cell.n, rng, 40)

    ours, real = p_values(arm, control), _real(arm, control)

    assert arm.shape[-1] == n_arm and control.shape[-1] == n_control
    for name in ours:
        np.testing.assert_allclose(ours[name], real[name], rtol=1e-9, atol=0, equal_nan=True)
    finite = np.isfinite(ours["q_abs"]).sum()  # the comparison has numbers in it
    if min(n_arm, n_control) >= 10:
        assert finite > 20
    elif outcome == "normal":  # a few players, and the spread of a revenue cohort is often nil
        assert finite > 5


def test_two_players_in_each_arm_of_a_cohort_give_no_estimate_in_either_implementation() -> None:
    cell = Cell("normal", 5, 2, 2, "relative_drift", control_n=2)
    control_mean, (arm_mean,) = means(cell)
    rng = np.random.default_rng(3)
    control = draw("normal", control_mean, 2, rng, 20)
    arm = draw("normal", arm_mean, 2, rng, 20)

    ours, real = p_values(arm, control), _real(arm, control)

    for name in ours:  # the degrees of freedom are at most 2 there: the correction does not exist
        assert np.isnan(ours[name]).all() and np.isnan(real[name]).all(), name


@pytest.mark.parametrize(("n_arm", "n_control"), [(240, 80), (80, 240), (150, 150)])
@pytest.mark.parametrize("outcome", ["normal", "revenue_mild", "revenue", "revenue_heavy"])
def test_the_simulated_flags_are_the_rules_own_trigger_when_the_arms_differ_in_size(
    outcome: str, n_arm: int, n_control: int
) -> None:
    cell = Cell(outcome, 6, n_arm, 2, "null_se_shift", control_n=n_control)
    control_mean, (arm_mean,) = means(cell)
    rng = np.random.default_rng(23)
    control = draw(outcome, control_mean, n_control, rng, 150)
    arm = draw(outcome, arm_mean, n_arm, rng, 150)

    ours = flags(p_values(arm, control), cell.level)["both"]
    real = _real_trigger(arm, control, 2)

    assert (ours == real).all()
    assert 10 < real.sum() < 140  # a mixture of flagged and not, so the check bites


def test_a_cell_draws_each_arm_at_its_own_size_and_control_first() -> None:
    cell = Cell("normal", 4, 40, 2, "fade", control_n=120)
    control_mean, (arm_mean,) = means(cell)
    chunks = cell.seed_sequence(5).spawn(2)
    expected = []
    for stream, size in zip(chunks, (250, 50), strict=True):
        rng = np.random.default_rng(stream)
        control = draw("normal", control_mean, 120, rng, size)
        arm = draw("normal", arm_mean, 40, rng, size)
        expected.append(flags(p_values(arm, control), cell.level)["both"])

    found = cell_flags(cell, 300, seed=5)["both"][:, 0]

    assert (found == np.concatenate(expected)).all()
    assert found.sum() > 20 and found.sum() < 300


def test_a_cell_knows_its_control_size_and_its_split() -> None:
    assert Cell("normal", 4, 30, 2, "zero").control_players == 30
    assert Cell("normal", 4, 30, 2, "zero").ratio == 1.0
    assert Cell("normal", 4, 30, 2, "zero", control_n=90).control_players == 90
    assert Cell("normal", 4, 30, 2, "zero", control_n=90).ratio == 3.0
    assert Cell("normal", 4, 90, 2, "zero", control_n=30).ratio == 3.0


def test_a_control_size_changes_the_stream_of_a_cell() -> None:
    plain = Cell("normal", 4, 30, 2, "zero")
    explicit = Cell("normal", 4, 30, 2, "zero", control_n=30)
    other = Cell("normal", 4, 30, 2, "zero", control_n=60)

    def first(cell: Cell) -> float:
        return float(np.random.default_rng(cell.seed_sequence(7)).random())

    assert len({first(plain), first(explicit), first(other)}) == 3


# --- The heavy-tailed outcomes -----------------------------------------------------------------


@pytest.mark.parametrize("outcome", TAILED)
def test_a_tailed_outcome_is_zero_for_most_players_and_lognormal_for_the_rest(outcome: str) -> None:
    sample = draw(outcome, np.array([BASE[outcome]]), 100_000, np.random.default_rng(3), 4)
    values = sample.reshape(-1)
    paying = values[values > 0]
    spend_sd = SPEND_SD[outcome]

    assert len(paying) / len(values) == pytest.approx(PAYING, abs=0.003)
    assert np.log(paying).std() == pytest.approx(spend_sd, rel=0.02)
    mean_of_log = np.log(BASE[outcome] / PAYING) - spend_sd**2 / 2
    assert np.log(paying).mean() == pytest.approx(mean_of_log, abs=0.03)
    assert (values >= 0).all()


def test_a_tailed_outcome_takes_the_mean_it_is_given_in_each_cohort() -> None:
    mean = np.array([3.0, 6.0])
    sample = draw("revenue_mild", mean, 200_000, np.random.default_rng(4), 2)

    observed = sample.mean(axis=(0, 2))

    np.testing.assert_allclose(observed, mean, rtol=0.05)
    assert means(Cell("revenue", 4, 30, 2, "relative"))[1][0] == pytest.approx([3.6] * 4)


@pytest.mark.parametrize(
    ("outcome", "wanted"),
    [
        ("normal", [[1.0, 5.0], [20.0, 100.0], [3.0, 3.0]]),
        ("poisson", [[1.0, 5.0], [20.0, 100.0], [3.0, 3.0]]),
        ("binary", [[0.1, 0.3], [0.5, 0.9], [0.2, 0.2]]),
    ],
)
def test_draw_takes_a_mean_for_each_replication_and_cohort(outcome: str, wanted: list) -> None:
    wanted_array = np.array(wanted)

    sample = draw(outcome, wanted_array, 4000, np.random.default_rng(6), 3)

    assert sample.shape == (3, 2, 4000)
    np.testing.assert_allclose(sample.mean(axis=2), wanted_array, atol=0.04 * wanted_array.max())


def test_a_binary_rate_above_one_is_refused() -> None:
    with pytest.raises(ValueError, match="above 1"):
        draw("binary", np.array([[0.5, 1.2]]), 5, np.random.default_rng(0), 1)


def test_the_tail_shapes_are_what_the_rules_measures_and_scipy_give_for_the_same_players() -> None:
    (row,) = tail_shapes(outcomes=("revenue",), sizes=(250,), samples=300, seed=1)
    values = shape_sample("revenue", 250, 300, 1)
    measured = [heavy_tail_measures(v.tolist()) for v in values]
    found = {  # the rule's measures are the kurtosis and the top share; it has no skewness
        "skewness": np.array([stats.skew(v) for v in values]),
        "excess_kurtosis": np.array([m.excess_kurtosis for m in measured]),
        "top_1_percent_share": np.array([m.top_share for m in measured]),
        "sd_ratio": np.array([v.std(ddof=1) for v in values]) / population_sd("revenue"),
    }

    assert (row["outcome"], row["n"], row["samples"]) == ("revenue", 250, 300)
    for name, numbers in found.items():
        for percentile in (5, 50, 95):
            expected = float(np.percentile(numbers, percentile))
            assert row[f"{name}_p{percentile}"] == pytest.approx(expected, abs=2e-4), name


# --- The grids ---------------------------------------------------------------------------------


def test_the_heavy_grid_holds_equal_arms_unequal_arms_at_the_raised_floors_and_the_shifts() -> None:
    cells = heavy_grid()
    shifts = [c for c in cells if c.scenario == "null_se_shift"]
    located = [c for c in cells if c.scenario == "null_se_location"]
    rest = [c for c in cells if c.scenario not in ("null_se_shift", "null_se_location")]
    equal = [c for c in rest if c.n == c.control_n]
    unequal = [c for c in rest if c.n != c.control_n]

    assert len(cells) == 540 == len(shifts) + len(located) + len(equal) + len(unequal)
    assert len({(c.outcome, c.cohorts, c.n, c.control_n, c.scenario) for c in cells}) == 540
    assert all(c.arms == 2 and c.control_n is not None for c in cells)
    assert {c.outcome for c in rest} == set(TAILED)
    assert len(equal) == 180 and {c.n for c in equal} == set(EQUAL_PLAYERS)
    assert {c.scenario for c in equal} == {*NULL_SCENARIOS, "fade"}
    assert {c.cohorts for c in equal} == {c.cohorts for c in unequal} == set(HEAVY_COHORTS)
    assert len(unequal) == 288 and {c.scenario for c in unequal} == {"zero", "relative"}
    for cell in unequal:
        smaller = min(cell.n, cell.control_n)
        assert cell.ratio in SPLITS
        assert smaller in {m * raised_floor(cell.ratio) for m in FLOOR_MULTIPLES}
        assert max(cell.n, cell.control_n) == cell.ratio * smaller
    assert sorted({min(c.n, c.control_n) for c in unequal}) == sorted(
        m * floor
        for m in FLOOR_MULTIPLES
        for floor in (43, 69, 98, 258)  # the floors of 21.6
    )
    for split in SPLITS:  # each split, at each size, with the variant the larger and the smaller
        for multiple in FLOOR_MULTIPLES:
            both = {
                c.n > c.control_n
                for c in unequal
                if c.ratio == split and min(c.n, c.control_n) == multiple * raised_floor(split)
            }
            assert both == {True, False}
    assert len(shifts) == 42 and {c.outcome for c in shifts} == set(SHIFT_OUTCOMES)
    assert {c.cohorts for c in shifts} == set(SHIFT_COHORTS)
    assert {c.n for c in shifts} == set(SHIFT_PLAYERS) and all(c.n == c.control_n for c in shifts)
    assert len(located) == 30 and {c.outcome for c in located} == set(LOCATION_OUTCOMES)
    assert set(LOCATION_OUTCOMES) == {"normal", "lognormal", *TAILED}  # where a shift can be added
    assert {c.cohorts for c in located} == set(SHIFT_COHORTS)
    assert {c.n for c in located} == set(SHIFT_PLAYERS) and all(c.n == c.control_n for c in located)


def test_the_printed_grid_holds_every_outcome_with_equal_arms_and_five_with_the_shift_added() -> (
    None
):
    cells = printed_grid()
    scaled = [c for c in cells if c.scenario == "printed_shift"]
    added = [c for c in cells if c.scenario == "printed_location"]

    assert len(cells) == 72 == len(scaled) + len(added)
    assert len({(c.outcome, c.cohorts, c.n, c.scenario) for c in cells}) == 72
    assert {c.outcome for c in scaled} == set(SHIFT_OUTCOMES) == set(OUTCOMES) | set(TAILED)
    assert {c.outcome for c in added} == set(LOCATION_OUTCOMES) and len(added) == 30
    assert {c.cohorts for c in cells} == set(SHIFT_COHORTS)
    assert {c.n for c in cells} == set(SHIFT_PLAYERS) and all(c.n == c.control_n for c in cells)


def test_the_grids_of_the_first_study_are_the_cells_of_the_committed_files() -> None:
    def made(cells: list[Cell]) -> list[tuple]:
        return [(c.outcome, c.cohorts, c.n, c.arms, c.scenario) for c in cells]

    def stored(data: dict) -> list[tuple]:
        return [
            (c["outcome"], c["cohorts"], c["n"], c["arms"], c["scenario"]) for c in data["cells"]
        ]

    assert made(grid()) == stored(NULL)
    assert made(grid(scenarios=("fade",))) == stored(FADE)


# --- The standard error under no effect, and the shift a finding prints --------------------------


@pytest.mark.parametrize("outcome", [*OUTCOMES, *TAILED])
def test_the_population_sd_is_the_standard_deviation_of_the_outcome_that_is_drawn(
    outcome: str,
) -> None:
    mean = BASE[outcome]
    if outcome in SPEND_SD:  # exact, from the moments of the lognormal a payer spends
        spend_sd = SPEND_SD[outcome]
        spends = stats.lognorm(s=spend_sd, scale=mean / PAYING * math.exp(-(spend_sd**2) / 2))
        expected = math.sqrt(PAYING * spends.moment(2) - mean**2)
    elif outcome == "lognormal":
        expected = math.sqrt(stats.lognorm(s=LOG_SD, scale=mean * math.exp(-(LOG_SD**2) / 2)).var())
    else:  # sampled: the standard deviation of these is well estimated
        sample = draw(outcome, np.array([mean]), 400_000, np.random.default_rng(8), 1).reshape(-1)
        expected = float(sample.std())

    assert population_sd(outcome) == pytest.approx(expected, rel=0.01)
    with pytest.raises(ValueError, match="unknown outcome"):
        population_sd("cauchy")


def test_the_null_se_shift_is_what_cohort_detectable_shift_gives_for_the_cells_design() -> None:
    cell = Cell("normal", 6, 40, 2, "null_se_shift", control_n=120)
    se = 4.0 * math.sqrt(1 / 40 + 1 / 120)  # the standard error of one cohort's difference
    three_arms = Cell("normal", 6, 40, 3, "null_se_shift", control_n=120)

    assert null_se_shift(cell) == pytest.approx(
        cohort_detectable_shift([se] * 6, shape="linear_fade", level=0.025), rel=1e-12
    )
    assert null_se_shift(three_arms) > null_se_shift(cell)  # a stricter level needs more
    assert null_se_shift(Cell("normal", 6, 40, 2, "null_se_shift")) > null_se_shift(
        Cell("normal", 6, 80, 2, "null_se_shift")
    )


def test_the_null_se_shift_scenario_is_a_linear_fade_of_that_size_from_the_first_cohort() -> None:
    cell = Cell("revenue", 5, 300, 2, "null_se_shift", control_n=300)
    control, (arm,) = means(cell)

    assert control == pytest.approx([3.0] * 5)
    assert arm[0] - control[0] == pytest.approx(null_se_shift(cell))
    assert arm[-1] == pytest.approx(control[-1])
    assert np.diff(arm - control) == pytest.approx(-null_se_shift(cell) / 4)


@pytest.mark.parametrize(
    "cell",
    [
        Cell("normal", 6, 100, 2, "null_se_shift", control_n=100),
        Cell("normal", 6, 240, 2, "null_se_shift", control_n=80),
        Cell("normal", 6, 60, 2, "null_se_shift", control_n=180),
        Cell("normal", 6, 100, 3, "null_se_shift", control_n=100),
        Cell("normal", 6, 100, 2, "null_se_location", control_n=100),
        Cell("normal", 6, 100, 3, "null_se_location", control_n=100),
    ],
    ids=[
        "equal",
        "variant-larger",
        "variant-smaller",
        "three-arms",
        "added-to-every-player",
        "three-arms-added-to-every-player",
    ],
)
def test_for_a_normal_outcome_the_null_se_shift_is_flagged_with_the_probability_it_names(
    cell: Cell,
) -> None:
    reps = 2000

    found = run_cell(cell, reps, seed=3)["absolute"]

    assert abs(found - 0.8) <= 4.5 * math.sqrt(0.8 * 0.2 / reps) + 0.01


@pytest.mark.parametrize("scenario", ["printed_shift", "printed_location"])
def test_a_row_of_a_printed_scenario_is_its_cell_and_what_the_printed_study_gives(
    scenario: str,
) -> None:
    cell = Cell("lognormal", 4, 60, 2, scenario, control_n=60)

    (row,) = study([cell], 30, 5)

    assert row == {**asdict(cell), "reps": 30, "seed": 5, **run_printed(cell, 30, 5)}
    assert list(row)[:8] == [*asdict(cell), "reps", "seed"][:8]
    assert row["scenario"] == scenario and "shift" not in row  # and no column of a null cell
    assert 0 < row["runs"] <= 30 and "q_abs" not in row


def test_every_scenario_a_grid_makes_is_described() -> None:
    made = {c.scenario for c in (*grid(scenarios=(*NULL_SCENARIOS, "fade")), *heavy_grid())}
    made |= {c.scenario for c in printed_grid()}

    assert made <= SCENARIOS.keys()
    assert {"null_se_shift", "null_se_location", "printed_shift", "printed_location"} <= made


def test_a_row_carries_the_shift_only_for_the_scenario_that_has_one() -> None:
    shifted = Cell("normal", 4, 100, 2, "null_se_shift", control_n=100)
    plain = Cell("normal", 4, 100, 2, "zero", control_n=100)

    row_shifted, row_plain = study([shifted, plain], 100, 3)

    assert row_shifted["shift"] == pytest.approx(2.311, abs=5e-4)
    assert row_shifted["shift_share_of_mean"] == pytest.approx(0.2311, abs=5e-5)
    assert "shift" not in row_plain and "shift_share_of_mean" not in row_plain


PRINTED_DATA = [  # (outcome, variant players, control players, mean of the draws or None, no shift)
    ("normal", 60, 60, None, False),
    ("revenue", 150, 50, None, False),
    ("revenue_heavy", 80, 240, None, False),
    ("poisson", 30, 90, None, False),
    ("binary", 30, 30, 0.04, True),  # rare events: cohorts with no events, some runs unevaluated
    ("normal", 60, 60, -2.0, True),  # no cohort has a mean above 0: the log-ratio scale is not run
]


@pytest.mark.parametrize(("outcome", "n_arm", "n_control", "mean", "missing"), PRINTED_DATA)
def test_the_printed_shifts_are_the_rules_own_detectable_shifts(
    outcome: str, n_arm: int, n_control: int, mean: float | None, missing: bool
) -> None:
    k = 6
    base = np.full(k, mean if mean is not None else BASE[outcome])
    rng = np.random.default_rng(5)
    control = draw(outcome, base, n_control, rng, 20)
    arm = draw(outcome, base, n_arm, rng, 20)

    ours = printed_shifts(arm, control, 0.025)

    blocks = list(range(k))
    not_evaluated = 0
    for r in range(20):
        treatment = {b: list(arm[r, b]) for b in blocks}
        reference = {b: list(control[r, b]) for b in blocks}
        absolute = _scale_test("absolute", blocks, treatment, reference)
        log_ratio = _scale_test("log_ratio", blocks, treatment, reference)
        real = detectable_shifts(absolute, 0.025)
        if real is None or log_ratio.heterogeneity is None:  # the finding prints no shift
            assert np.isnan(ours[r])
            not_evaluated += 1
        else:
            assert ours[r] == pytest.approx(real["linear_fade"], rel=1e-9)
    assert (not_evaluated > 0) == missing  # the cases where a scale is not run, and only those
    assert (np.isfinite(ours).sum() > 3) != (outcome == "normal" and mean is not None)


def test_a_printed_shift_uses_the_level_it_is_given_and_the_cohorts_that_give_an_estimate() -> None:
    rng = np.random.default_rng(9)
    base = np.full(6, 3.0)
    control = draw("poisson", base, 80, rng, 12)
    arm = draw("poisson", base, 80, rng, 12)
    arm[0, 2, :] = 3.0  # no variation anywhere in this cohort: it gives no estimate
    control[0, 2, :] = 3.0

    stricter, looser = printed_shifts(arm, control, 0.0125), printed_shifts(arm, control, 0.05)

    assert (stricter > looser).all()
    blocks = [0, 1, 3, 4, 5]
    treatment = {b: list(arm[0, b]) for b in blocks}
    reference = {b: list(control[0, b]) for b in blocks}
    real = detectable_shifts(_scale_test("absolute", blocks, treatment, reference), 0.0125)
    assert stricter[0] == pytest.approx(real["linear_fade"], rel=1e-9)


def test_the_low_information_label_is_the_rules_own_for_the_control_mean_criterion() -> None:
    cell = Cell("revenue", 8, 1000, 2, "printed_shift", control_n=1000)

    chunk = _printed_chunk(cell, 100, np.random.default_rng(2))

    labels = []
    for shift, control_mean in zip(chunk["shift"], chunk["control_mean"], strict=True):
        found = low_information(
            shift=shift, control_mean=control_mean, registered_mde=None, expected_events=None
        )
        labels.append("shift_exceeds_control_mean" in found)
    assert chunk["low_information"].tolist() == labels
    assert 10 < sum(labels) < 90  # a mixture, so the comparison bites


def test_the_fade_that_is_simulated_is_the_one_the_replication_printed(monkeypatch) -> None:
    import cohort_simulation as module

    cell = Cell("normal", 6, 200, 2, "printed_shift", control_n=200)

    def stub(value):
        return lambda arm, control, level: np.full(arm.shape[0], value)

    monkeypatch.setattr(module, "printed_shifts", stub(8.0))  # twice the player sd: always seen
    big = module.run_printed(cell, 300, 1)
    monkeypatch.setattr(module, "printed_shifts", stub(0.0))  # no fade: only false alarms
    none = module.run_printed(cell, 300, 1)
    monkeypatch.setattr(module, "printed_shifts", stub(np.nan))  # not evaluated
    nan = module.run_printed(cell, 300, 1)
    monkeypatch.setattr(
        module,
        "printed_shifts",
        lambda arm, control, level: np.where(np.arange(arm.shape[0]) % 2 == 0, 8.0, 0.0),
    )
    half = module.run_printed(cell, 300, 1)

    assert big["absolute"] > 0.99 and big["both"] > 0.99 and big["printed"] == 1.0
    assert none["absolute"] < 0.1 and none["both"] < 0.1
    assert half["absolute"] == pytest.approx(0.5, abs=0.06)
    assert nan["printed"] == 0.0
    assert [nan[k] for k in ("absolute", "both", "low_information", "ratio_p50")] == [None] * 4
    assert nan["absolute_not_low_information"] is None


def test_a_shift_above_the_control_mean_is_low_information_and_leaves_no_unlabelled_runs(
    monkeypatch,
) -> None:
    import cohort_simulation as module

    cell = Cell("normal", 6, 200, 2, "printed_shift", control_n=200)  # a control mean of 10
    monkeypatch.setattr(module, "printed_shifts", lambda a, c, level: np.full(a.shape[0], 12.0))
    high = module.run_printed(cell, 250, 1)
    monkeypatch.setattr(module, "printed_shifts", lambda a, c, level: np.full(a.shape[0], 9.0))
    low = module.run_printed(cell, 250, 1)

    assert high["low_information"] == 1.0
    assert high["absolute_not_low_information"] is None and high["both_not_low_information"] is None
    assert low["low_information"] == 0.0
    assert low["absolute_not_low_information"] == low["absolute"]
    assert low["both_not_low_information"] == low["both"]


def test_a_fade_added_to_every_player_keeps_the_spread_of_control_and_a_scaled_mean_does_not(
    monkeypatch,
) -> None:
    import cohort_simulation as module

    seen: dict[str, tuple] = {}
    real = module.p_values

    def recording(scenario):
        def p_values(arm, control):
            seen[scenario] = (arm.copy(), control.copy())
            return real(arm, control)

        return p_values

    monkeypatch.setattr(
        module, "printed_shifts", lambda arm, control, level: np.full(arm.shape[0], 10.0)
    )
    for scenario in ("printed_shift", "printed_location"):
        monkeypatch.setattr(module, "p_values", recording(scenario))
        cell = Cell("lognormal", 4, 3000, 2, scenario, control_n=3000)  # a control mean of 10
        module._printed_chunk(cell, 6, np.random.default_rng(1))

    def spread(arm, control):  # the arm's sd over control's, in each cohort
        return arm.std(axis=-1).mean(axis=0) / control.std(axis=-1).mean(axis=0)

    def gap(arm, control):  # the arm's mean less control's, in each cohort
        return arm.mean(axis=(0, 2)) - control.mean(axis=(0, 2))

    added, scaled = seen["printed_location"], seen["printed_shift"]
    assert spread(*added) == pytest.approx([1.0] * 4, rel=0.15)
    assert spread(*scaled) == pytest.approx([2.0, 5 / 3, 4 / 3, 1.0], rel=0.15)  # sd ~ mean
    for arm, control in (added, scaled):
        assert gap(arm, control) == pytest.approx([10.0, 20 / 3, 10 / 3, 0.0], abs=0.8)


def test_a_fade_added_to_every_player_is_flagged_more_than_one_that_scales_the_arm() -> None:
    kwargs = {"control_n": 1000}

    added = run_cell(Cell("revenue", 8, 1000, 2, "null_se_location", **kwargs), 400, 3)
    scaled = run_cell(Cell("revenue", 8, 1000, 2, "null_se_shift", **kwargs), 400, 3)

    assert added["absolute"] > scaled["absolute"] + 0.15  # about 0.96 and 0.69 in the study


def test_a_shift_cannot_be_added_to_every_player_of_a_count_or_a_rate() -> None:
    for outcome in ("poisson", "binary"):
        with pytest.raises(ValueError, match="cannot be added"):
            run_printed(Cell(outcome, 4, 100, 2, "printed_location", control_n=100), 10, 1)
        located = Cell(outcome, 4, 100, 2, "null_se_location", control_n=100)
        for reach in (means, lambda c: cell_flags(c, 10, 1), lambda c: run_cell(c, 10, 1)):
            with pytest.raises(ValueError, match="cannot be added"):
                reach(located)
        with pytest.raises(ValueError, match="cannot be added"):
            study([located], 10, 1)
    for outcome in LOCATION_OUTCOMES:  # and every outcome that can have it, has it
        assert means(Cell(outcome, 4, 100, 2, "null_se_location"))[1]
    with pytest.raises(ValueError, match="not a scenario"):
        run_printed(Cell("normal", 4, 100, 2, "zero", control_n=100), 10, 1)


@pytest.mark.parametrize("scenario", ["printed_shift", "printed_location"])
def test_a_printed_chunk_draws_control_then_the_quiet_arm_then_the_fade_then_a_fresh_control(
    scenario: str,
) -> None:
    cell = Cell("lognormal", 4, 60, 2, scenario, control_n=60)
    base = np.full(4, BASE["lognormal"])

    chunk = _printed_chunk(cell, 12, np.random.default_rng(7))

    rng = np.random.default_rng(7)
    control = draw("lognormal", base, 60, rng, 12)
    quiet = draw("lognormal", base, 60, rng, 12)
    shift = printed_shifts(quiet, control, cell.level)
    seen = np.where(np.isnan(shift), 0.0, shift)[:, None] * (1.0 - np.arange(4) / 3)
    if scenario == "printed_location":
        arm = draw("lognormal", base, 60, rng, 12) + seen[:, :, None]
    else:
        arm = draw("lognormal", BASE["lognormal"] + seen, 60, rng, 12)
    fresh = draw("lognormal", base, 60, rng, 12)
    found = flags(p_values(arm, fresh), cell.level)

    np.testing.assert_array_equal(chunk["shift"], shift)
    np.testing.assert_allclose(chunk["control_mean"], control.mean(axis=(1, 2)))
    assert (chunk["absolute"] == found["absolute"]).all() and (chunk["both"] == found["both"]).all()
    assert (chunk["low_information"] == (shift > control.mean(axis=(1, 2)))).all()


def test_for_a_normal_outcome_the_printed_shift_is_the_true_one_and_is_flagged_as_claimed() -> None:
    cell = Cell("normal", 8, 300, 2, "printed_shift", control_n=300)

    found = run_printed(cell, 150, seed=5)

    assert found["printed"] == 1.0 and found["low_information"] == 0.0
    assert found["ratio_p5"] < found["ratio_p50"] < found["ratio_p95"]
    assert found["ratio_p50"] == pytest.approx(1.0, abs=0.03)
    assert found["true_shift"] == round(null_se_shift(cell), 4)
    assert 0.68 < found["absolute"] < 0.92
    assert found["absolute_not_low_information"] == found["absolute"]


def test_the_shift_a_finding_prints_is_simulated_for_two_arms_of_equal_size_only() -> None:
    with pytest.raises(ValueError, match="two arms of equal size"):
        run_printed(Cell("normal", 4, 100, 2, "printed_shift", control_n=50), 10, 1)
    with pytest.raises(ValueError, match="two arms of equal size"):
        run_printed(Cell("normal", 4, 100, 3, "printed_shift", control_n=100), 10, 1)


# --- Regenerating, processes and the command line ------------------------------------------------

RATES = (
    "q_abs",
    "s_abs",
    "q_log",
    "s_log",
    "absolute",
    "relative",
    "both",
    "q_both",
    "any_arm_both",
)


def _regenerates(rows: list[dict], stored: list[dict], header: dict) -> None:
    """The same numbers where numpy and scipy are those that made the file, the same within
    chance elsewhere (a random stream is not promised to stay the same between versions)."""
    assert len(rows) == len(stored) > 0
    if (np.__version__, scipy.__version__) == (header["numpy"], header["scipy"]):
        assert rows == stored
        assert [list(row) for row in rows] == [list(old) for old in stored]
        return
    for row, old in zip(rows, stored, strict=True):
        assert list(row) == list(old)  # the same columns in the same order
        for key, value in row.items():
            if key in RATES:
                p = old[key]
                spread = math.sqrt(max(p * (1 - p), 1e-4) * (2 / old["reps"]))
                assert abs(value - p) <= 4.5 * spread + 0.002, (key, value, p)
            elif isinstance(value, float):
                assert value == pytest.approx(old[key], rel=1e-3)
            else:
                assert value == old[key]


def test_the_module_still_makes_the_committed_rows_of_the_first_study() -> None:
    for data in (NULL, FADE):
        header = {k: v for k, v in data.items() if k != "cells"}
        chosen = [
            next(
                c
                for c in data["cells"]
                if (c["outcome"], c["n"], c["cohorts"], c["arms"]) == (outcome, 30, 3, arms)
            )
            for outcome in OUTCOMES
            for arms in (2, 3)
        ]
        cells = [Cell(c["outcome"], c["cohorts"], c["n"], c["arms"], c["scenario"]) for c in chosen]

        rows = study(cells, data["reps"], data["seed"])

        assert len(chosen) == 8 and {c["outcome"] for c in chosen} == set(OUTCOMES)
        _regenerates(rows, chosen, header)
        assert all("control_n" not in row for row in rows)  # a cell without it writes none


def test_what_the_regeneration_check_cannot_see_in_other_versions_is_pinned_apart() -> None:
    rng = np.random.default_rng(2)
    lognormal = draw("lognormal", np.array([10.0]), 4000, rng, 50)

    assert np.log(lognormal).std() == pytest.approx(1.0, rel=0.02)  # LOG_SD
    assert np.log(lognormal).mean() == pytest.approx(np.log(10.0) - 0.5, abs=0.02)
    assert inspect.signature(tail_shapes).parameters["samples"].default == 4000
    assert inspect.signature(tail_shapes).parameters["seed"].default == 20261211
    assert SPLITS == (2, 3, 4, 9) and FLOOR_MULTIPLES == (1, 3) and HEAVY_COHORTS == (4, 8, 12)


def test_the_regeneration_check_notices_a_changed_number_whatever_the_versions() -> None:
    rows = [{"outcome": "normal", "reps": 5000, "both": 0.04, "shift": 1.0}]
    header = {"numpy": np.__version__, "scipy": scipy.__version__}
    other = {"numpy": "0.0", "scipy": "0.0"}

    _regenerates(rows, [dict(rows[0])], header)  # exact where the versions are the same
    _regenerates(rows, [{**rows[0], "both": 0.042, "shift": 1.0004}], other)  # chance elsewhere
    with pytest.raises(AssertionError):
        _regenerates(rows, [{**rows[0], "both": 0.0401}], header)
    with pytest.raises(AssertionError):
        _regenerates(rows, [{**rows[0], "both": 0.08}], other)
    with pytest.raises(AssertionError):
        _regenerates(rows, [{**rows[0], "outcome": "poisson"}], other)
    with pytest.raises(AssertionError):
        _regenerates(rows, [{**rows[0], "shift": 1.02}], other)  # a deterministic number is 1%
    with pytest.raises(AssertionError):
        _regenerates(rows, [{**rows[0], "extra": 1}], other)  # a column that is not made
    two = [{"outcome": "normal", "reps": 5000, "both": 0.04}]
    for versions in (header, other):
        with pytest.raises(AssertionError):  # the same columns in another order
            _regenerates(two, [{"both": 0.04, "reps": 5000, "outcome": "normal"}], versions)
    with pytest.raises(AssertionError):
        _regenerates([], [], header)  # nothing compared is not a pass


def test_a_study_with_workers_runs_them_in_spawned_processes_and_one_worker_runs_none(
    monkeypatch,
) -> None:
    import cohort_simulation as module

    seen: list[tuple] = []

    class Recording(module.ProcessPoolExecutor):
        def __init__(self, *args, **kwargs):
            seen.append((args, kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "ProcessPoolExecutor", Recording)
    cells = [Cell("normal", 3, 30, 2, "zero"), Cell("normal", 3, 30, 2, "fade")]

    in_processes, in_this_one = study(cells, 40, 9, workers=2), study(cells, 40, 9)

    assert in_processes == in_this_one
    assert len(seen) == 1  # the second study made no pool
    assert seen[0][0] == (2,) and seen[0][1]["mp_context"].get_start_method() == "spawn"


def test_the_command_line_writes_the_study_it_describes(tmp_path, monkeypatch, capsys) -> None:
    import cohort_simulation as module

    cheap = [
        Cell("revenue", 4, 43, 2, "zero", control_n=86),
        Cell("normal", 4, 100, 2, "null_se_shift", control_n=100),
    ]
    printed = [Cell("normal", 4, 40, 2, "printed_shift", control_n=40)]
    monkeypatch.setattr(module, "REPLICATION", ("normal", 3, 30, 40, "zero", 20, 777))
    monkeypatch.setattr(module, "heavy_grid", lambda: cheap)
    monkeypatch.setattr(module, "printed_grid", lambda: printed)
    monkeypatch.setattr(module, "tail_shapes", lambda seed: [{"outcome": "revenue", "seed": seed}])
    monkeypatch.setattr(
        module, "grid", lambda scenarios: [Cell("normal", 3, 30, 2, s) for s in scenarios]
    )
    out = tmp_path / "a" / "b" / "heavy.json"  # directories that do not exist yet

    module.main(
        ["--heavy", "--reps", "60", "--printed-reps", "12", "--seed", "4"]
        + ["--out", str(out), "--workers", "2"]
    )
    heavy = json.loads(out.read_text(encoding="utf-8"))

    assert list(heavy)[-4:] == ["shapes", "cells", "printed", "replication"]
    assert heavy["what"].startswith("heavy-tailed outcomes")
    assert heavy["command"] == (
        "python tests/cohort_simulation.py --heavy --reps 60 --printed-reps 12 --seed 4 "
        f"--out {out}"
    )
    assert (heavy["reps"], heavy["printed_reps"], heavy["seed"]) == (60, 12, 4)
    assert (heavy["numpy"], heavy["scipy"]) == (np.__version__, scipy.__version__)
    assert heavy["trigger"] == HEAVY["trigger"] and "part" not in heavy
    assert "a share 0.13 of the players spend" in heavy["outcomes"]
    assert all(f"{sd} ({name})" in heavy["outcomes"] for name, sd in SPEND_SD.items())
    assert "mean 3.0 per player (23.08 per paying player)" in heavy["outcomes"]
    assert heavy["shapes"] == [{"outcome": "revenue", "seed": 4}]
    assert heavy["cells"] == study(cheap, 60, 4)
    assert heavy["printed"] == study(printed, 12, 4)
    again = Cell("normal", 3, 30, 2, "zero", control_n=40)
    assert heavy["replication"] == study([again], 20, 777)  # its own settings, not the study's

    module.main(["--power", "--reps", "20", "--out", str(out)])
    power = json.loads(out.read_text(encoding="utf-8"))
    assert (power["what"], power["command"]) == (
        "fade (power)",
        f"python tests/cohort_simulation.py --power --reps 20 --seed 20261211 --out {out}",
    )
    assert [c["scenario"] for c in power["cells"]] == ["fade"]
    assert not {"shapes", "printed", "printed_reps", "replication"} & power.keys()

    module.main(["--reps", "20", "--part", "1", "--parts", "2"])  # to the screen, every other cell
    null = json.loads(capsys.readouterr().out)
    assert null["what"] == "null (false alarms)"
    assert null["command"] == (
        "python tests/cohort_simulation.py --reps 20 --seed 20261211 --part 1 --parts 2"
    )
    assert (null["part"], null["parts"]) == (1, 2)
    assert [c["scenario"] for c in null["cells"]] == ["relative", "absolute_drift"]
    assert not {"outcomes", "shapes", "printed", "replication"} & null.keys()


def test_the_defaults_of_the_command_line_are_pinned() -> None:
    import cohort_simulation as module

    arguments = module._parser().parse_args([])

    assert (arguments.reps, arguments.printed_reps, arguments.seed) == (4000, 3000, 20261211)
    assert (arguments.part, arguments.parts, arguments.workers) == (0, 1, 1)
    assert arguments.out is None and not arguments.power and not arguments.heavy


def test_the_command_line_finds_out_that_it_cannot_write_before_it_computes(
    tmp_path, monkeypatch
) -> None:
    import cohort_simulation as module

    def computing(*args, **kwargs):
        raise AssertionError("the study ran although the file could not have been written")

    monkeypatch.setattr(module, "study", computing)
    monkeypatch.setattr(module, "grid", lambda scenarios: [Cell("normal", 3, 30, 2, "zero")])
    blocker = tmp_path / "a file"
    blocker.write_text("not a directory", encoding="utf-8")

    for out in (blocker / "study.json", tmp_path):  # a directory below a file; a directory
        with pytest.raises(SystemExit) as stopped:
            module.main(["--reps", "5", "--out", str(out)])
        assert stopped.value.code == 2
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_a_study_that_fails_leaves_no_new_file_and_does_not_empty_an_old_one(
    tmp_path, monkeypatch
) -> None:
    import cohort_simulation as module

    def failing(*args, **kwargs):
        raise RuntimeError("the study failed")

    monkeypatch.setattr(module, "study", failing)
    monkeypatch.setattr(module, "grid", lambda scenarios: [Cell("normal", 3, 30, 2, "zero")])
    new, old = tmp_path / "x" / "new.json", tmp_path / "old.json"
    old.write_text("the last study", encoding="utf-8")

    for out in (new, old):
        with pytest.raises(RuntimeError, match="the study failed"):
            module.main(["--reps", "5", "--out", str(out)])

    assert not new.exists()
    assert old.read_text(encoding="utf-8") == "the last study"


@pytest.mark.parametrize("name", ["null", "fade", "heavy"])
def test_the_recorded_command_of_each_file_makes_its_header_and_tables(
    name: str, tmp_path, monkeypatch
) -> None:
    import shlex

    import cohort_simulation as module

    data = {"null": NULL, "fade": FADE, "heavy": HEAVY}[name]
    tables = [key for key in data if isinstance(data[key], list)]
    real_shapes = module.tail_shapes
    monkeypatch.setattr(module, "study", lambda cells, reps, seed, workers=1: [{} for _ in cells])
    monkeypatch.setattr(module, "tail_shapes", lambda seed: real_shapes(samples=2, seed=seed))
    words = shlex.split(data["command"])
    out = tmp_path / words[words.index("--out") + 1]  # not into the repository
    words[words.index("--out") + 1] = str(out)

    module.main(words[2:])
    made = json.loads(out.read_text(encoding="utf-8"))

    assert list(made) == list(data)  # the same keys in the same order
    own = {"numpy": np.__version__, "scipy": scipy.__version__, "command": " ".join(words)}
    for key in made:
        if key in own:
            assert made[key] == own[key]
        elif key not in tables:
            assert made[key] == data[key], key
    assert {t: len(made[t]) for t in tables} == {t: len(data[t]) for t in tables}
    if name == "heavy":  # the shapes of the file are those of the module's own defaults
        assert [list(r) for r in made["shapes"]] == [list(r) for r in data["shapes"]]
        assert [(r["outcome"], r["n"]) for r in made["shapes"]] == [
            (r["outcome"], r["n"]) for r in data["shapes"]
        ]


def test_the_command_line_hands_the_number_of_workers_to_every_study(monkeypatch) -> None:
    import cohort_simulation as module

    seen = []
    one = [Cell("normal", 3, 30, 2, "zero")]
    monkeypatch.setattr(module, "heavy_grid", lambda: one)
    monkeypatch.setattr(module, "printed_grid", lambda: one)
    monkeypatch.setattr(module, "tail_shapes", lambda seed: [])
    monkeypatch.setattr(
        module, "study", lambda cells, reps, seed, workers=1: seen.append(workers) or []
    )

    module.main(["--heavy", "--workers", "3"])

    assert seen == [3, 3, 1]  # the cells and the printed study; the replication is one cell


@pytest.mark.parametrize(
    "arguments",
    [
        ["--reps", "0"],
        ["--printed-reps", "0"],
        ["--workers", "0"],
        ["--parts", "0"],
        ["--part", "2", "--parts", "2"],
        ["--part", "-1"],
        ["--part", "5", "--parts", "10"],  # the stub grid below holds 3 cells
        ["--seed", "-1"],
        ["--heavy", "--parts", "2"],
        ["--power", "--heavy"],
    ],
)
def test_the_command_line_refuses_arguments_that_would_give_a_wrong_or_empty_study(
    arguments: list[str], monkeypatch
) -> None:
    import cohort_simulation as module

    # Without the check the study would run: a cheap one, so that its absence fails at once.
    monkeypatch.setattr(module, "REPLICATION", ("normal", 3, 30, 40, "zero", 20, 777))
    monkeypatch.setattr(module, "heavy_grid", lambda: [Cell("normal", 3, 30, 2, "zero")] * 3)
    monkeypatch.setattr(module, "printed_grid", lambda: [])
    monkeypatch.setattr(module, "tail_shapes", lambda seed: [])
    monkeypatch.setattr(module, "grid", lambda scenarios: [Cell("normal", 3, 30, 2, "zero")] * 3)

    with pytest.raises(SystemExit) as stopped:
        module.main(arguments)

    assert stopped.value.code == 2


def test_a_row_of_the_printed_study_aggregates_what_the_chunk_flagged() -> None:
    # Revenue, 4 cohorts of 1,000: some runs are called low information and some are not, and
    # the trigger flags fewer of the fades than the absolute scale alone.
    cell = Cell("revenue", 4, 1000, 2, "printed_shift", control_n=1000)
    stream = cell.seed_sequence(5).spawn(1)[0]
    chunk = _printed_chunk(cell, 60, np.random.default_rng(stream))
    printed = ~np.isnan(chunk["shift"])
    kept = printed & ~chunk["low_information"]

    row = run_printed(cell, 60, 5)

    assert printed.all() and 0 < kept.sum() < printed.sum()
    assert chunk["absolute"].sum() > chunk["both"].sum()
    assert (row["printed"], row["runs"]) == (1.0, 60)
    assert row["not_low_information_runs"] == kept.sum()
    for name in ("absolute", "both", "low_information"):
        assert row[name] == chunk[name][printed].mean(), name
    assert row["absolute_not_low_information"] == chunk["absolute"][kept].mean()
    assert row["both_not_low_information"] == chunk["both"][kept].mean()
    shift = chunk["shift"] / null_se_shift(cell)
    for q in (5, 50, 95):
        assert row[f"ratio_p{q}"] == round(float(np.percentile(shift, q)), 4)


def test_a_row_counts_the_runs_that_print_a_shift_and_those_not_called_low_information(
    monkeypatch,
) -> None:
    import cohort_simulation as module

    cell = Cell("normal", 6, 200, 2, "printed_shift", control_n=200)  # a control mean of 10

    def shifts(arm, control, level):  # a quarter print none; of the rest 100 give 12, 50 give 9
        out = np.where(np.arange(arm.shape[0]) % 2 == 0, 12.0, 9.0)
        out[np.arange(arm.shape[0]) % 4 == 3] = np.nan
        return out

    monkeypatch.setattr(module, "printed_shifts", shifts)

    row = module.run_printed(cell, 200, 1)

    assert row["printed"] == 0.75 and row["runs"] == 150
    assert row["low_information"] == pytest.approx(2 / 3)  # 12 > 10 in 100 of the 150 that print
    assert row["not_low_information_runs"] == 50  # the 9s


# --- The committed heavy-tailed study ------------------------------------------------------------

HEAVY = json.loads((DOCS / "simulations/cohort_trigger_heavy.json").read_text(encoding="utf-8"))
FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"


def _heavy(**match):
    return _cells(HEAVY, **match)


def _is_equal(cell: dict) -> bool:
    return cell["n"] == cell["control_n"]


def _key(row: dict) -> tuple:
    return (row["outcome"], row["cohorts"], row["n"], row["control_n"], row["scenario"])


def test_the_heavy_study_covers_the_whole_grids_in_the_order_the_module_makes_them() -> None:
    def key(cell) -> tuple:
        return (cell.outcome, cell.cohorts, cell.n, cell.control_n, cell.scenario)

    assert list(HEAVY)[-4:] == ["shapes", "cells", "printed", "replication"]
    assert (HEAVY["reps"], HEAVY["printed_reps"], HEAVY["seed"]) == (5000, 3000, 20261211)
    assert [_key(c) for c in HEAVY["cells"]] == [key(c) for c in heavy_grid()]  # in this order
    assert [_key(c) for c in HEAVY["printed"]] == [key(c) for c in printed_grid()]
    assert (len(HEAVY["cells"]), len(HEAVY["printed"]), len(HEAVY["replication"])) == (540, 72, 1)
    assert {c["reps"] for c in HEAVY["cells"]} == {5000}
    assert {c["reps"] for c in HEAVY["printed"]} == {3000}
    assert [(s["outcome"], s["n"]) for s in HEAVY["shapes"]] == [
        (o, n) for o in TAILED for n in SHAPE_SIZES
    ]
    assert {s["samples"] for s in HEAVY["shapes"]} == {4000}
    shifted = ("null_se_shift", "null_se_location")
    assert all(("shift" in c) == (c["scenario"] in shifted) for c in HEAVY["cells"])
    assert all(
        0 < c["runs"] <= c["reps"]  # the runs that print a shift
        and c["runs"] == round(c["printed"] * c["reps"])
        and 0 <= c["not_low_information_runs"] <= c["runs"]
        for c in HEAVY["printed"]
    )
    outcome, cohorts, n, control_n, scenario, reps, seed = REPLICATION
    (again,) = HEAVY["replication"]
    assert (again["outcome"], again["cohorts"], again["n"], again["control_n"]) == (
        outcome,
        cohorts,
        n,
        control_n,
    )
    assert (again["scenario"], again["reps"], again["seed"]) == (scenario, reps, seed)
    stored = _heavy(outcome=outcome, cohorts=cohorts, n=n, control_n=control_n, scenario=scenario)
    assert stored[0]["both"] == max(  # the highest of the cells with this number of cohorts
        c["both"] for c in HEAVY["cells"] if not _is_equal(c) and c["cohorts"] == cohorts
    )


@pytest.mark.parametrize(
    ("name", "flags"), [("null", []), ("fade", ["--power"]), ("heavy", ["--heavy"])]
)
def test_each_committed_file_records_a_command_that_regenerates_it(name: str, flags: list) -> None:
    import shlex

    import cohort_simulation as module

    data = {"null": NULL, "fade": FADE, "heavy": HEAVY}[name]
    words = shlex.split(data["command"])
    arguments = module._parser().parse_args(words[2:])

    assert words[:2] == ["python", "tests/cohort_simulation.py"]
    assert arguments.heavy == ("--heavy" in flags) and arguments.power == ("--power" in flags)
    assert (
        arguments.parts == 1 and arguments.reps == data["reps"] and arguments.seed == data["seed"]
    )
    assert arguments.out == Path(f"docs/simulations/cohort_trigger_{name}.json")
    assert isinstance(data["numpy"], str) and isinstance(data["scipy"], str)  # recorded
    assert data["trigger"] == (
        f"both scales show heterogeneity (Q or slope, p below {LEVEL} / non-control arms)"
    )
    if name == "heavy":
        assert arguments.printed_reps == data["printed_reps"]
        assert "mean 3.0 per player (23.08 per paying player)" in data["outcomes"]


@pytest.mark.parametrize(
    ("name", "tables"),
    [
        ("null", ("cells",)),
        ("fade", ("cells",)),
        ("heavy", ("shapes", "cells", "printed", "replication")),
    ],
)
def test_each_committed_file_is_written_by_the_module_in_the_form_it_reads_it(
    name: str, tables: tuple[str, ...]
) -> None:
    text = (DOCS / f"simulations/cohort_trigger_{name}.json").read_text(encoding="utf-8")
    data = {"null": NULL, "fade": FADE, "heavy": HEAVY}[name]
    header = {k: v for k, v in data.items() if k not in tables}

    produced = render(header, {table: data[table] for table in tables})

    if produced != text:  # say where, at once: a diff of the two strings takes minutes to build
        lines = zip(produced.splitlines(), text.splitlines(), strict=False)
        first = next((i for i, (a, b) in enumerate(lines, 1) if a != b), "past the end")
        pytest.fail(f"the file is not what render makes of it: first difference at line {first}")


def test_the_module_still_makes_cheap_rows_of_the_heavy_study() -> None:
    wanted = {
        ("revenue_mild", 4, 30, 30, "zero"),
        ("revenue", 4, 43, 86, "relative"),
        ("revenue_heavy", 4, 86, 43, "zero"),
        ("revenue", 8, 258, 2322, "relative"),  # the 9 to 1 behind the headline
        ("normal", 4, 100, 100, "null_se_shift"),
        ("normal", 4, 100, 100, "null_se_location"),
        ("revenue", 4, 100, 100, "null_se_location"),
        ("lognormal", 4, 100, 100, "null_se_location"),
        ("revenue", 4, 100, 100, "null_se_shift"),
        ("poisson", 4, 100, 100, "null_se_shift"),
        ("binary", 4, 100, 100, "null_se_shift"),
    }
    chosen = [c for c in HEAVY["cells"] if _key(c) in wanted]
    cells = [
        Cell(c["outcome"], c["cohorts"], c["n"], 2, c["scenario"], control_n=c["control_n"])
        for c in chosen
    ]
    header = {k: v for k, v in HEAVY.items() if k not in ("shapes", "cells", "printed")}

    rows = study(cells, HEAVY["reps"], HEAVY["seed"])

    assert len(chosen) == len(wanted)
    _regenerates(rows, chosen, header)
    (shapes_row,) = tail_shapes(outcomes=("revenue_mild",), sizes=(300,), seed=HEAVY["seed"])
    stored_shapes = next(
        s for s in HEAVY["shapes"] if (s["outcome"], s["n"]) == ("revenue_mild", 300)
    )
    if (np.__version__, scipy.__version__) == (HEAVY["numpy"], HEAVY["scipy"]):
        assert shapes_row == stored_shapes
    else:
        assert shapes_row["skewness_p50"] == pytest.approx(stored_shapes["skewness_p50"], rel=0.1)


HEAVY_CHECKED = [
    (Cell("revenue", 8, 100, 2, "zero", control_n=100), ("both", "relative", "absolute")),
    (Cell("revenue_mild", 8, 1000, 2, "relative_drift", control_n=1000), ("both", "absolute")),
    (Cell("revenue", 12, 258, 2, "zero", control_n=2322), ("both", "absolute")),
    (Cell("revenue", 8, 774, 2, "relative", control_n=6966), ("both",)),
    (Cell("revenue_mild", 4, 69, 2, "relative", control_n=207), ("both",)),
    (Cell("revenue", 8, 1000, 2, "fade", control_n=1000), ("both", "absolute")),
    (Cell("revenue_heavy", 8, 300, 2, "null_se_shift", control_n=300), ("both", "absolute")),
    (Cell("lognormal", 8, 300, 2, "null_se_shift", control_n=300), ("both", "absolute")),
    (Cell("revenue", 8, 1000, 2, "null_se_location", control_n=1000), ("both", "absolute")),
    (Cell("revenue_heavy", 4, 300, 2, "null_se_location", control_n=300), ("both", "absolute")),
]


@pytest.mark.parametrize(("cell", "names"), HEAVY_CHECKED, ids=lambda x: getattr(x, "outcome", ""))
def test_a_rerun_of_a_heavy_cell_agrees_with_the_committed_study(
    cell: Cell, names: tuple[str, ...]
) -> None:
    stored = _heavy(
        outcome=cell.outcome,
        cohorts=cell.cohorts,
        n=cell.n,
        control_n=cell.control_n,
        scenario=cell.scenario,
    )
    assert len(stored) == 1, "the cell is not one of the committed grid"
    (stored,) = stored
    reps = 2000

    rerun = run_cell(cell, reps, seed=20261299)  # another seed: an independent sample

    for name in names:
        p = stored[name]
        spread = math.sqrt(max(p * (1 - p), 1e-4) * (1 / reps + 1 / stored["reps"]))
        assert abs(rerun[name] - p) <= 4.5 * spread + 0.002, (name, rerun[name], p)


@pytest.mark.parametrize(
    ("outcome", "cohorts", "n", "scenario"),
    [
        ("normal", 4, 100, "printed_shift"),
        ("revenue", 4, 100, "printed_shift"),
        ("revenue", 4, 100, "printed_location"),
    ],
)
def test_a_rerun_of_a_printed_cell_agrees_with_the_committed_study(
    outcome: str, cohorts: int, n: int, scenario: str
) -> None:
    (stored,) = [
        c
        for c in HEAVY["printed"]
        if (c["outcome"], c["cohorts"], c["n"], c["scenario"]) == (outcome, cohorts, n, scenario)
    ]
    reps = 200

    rerun = run_printed(Cell(outcome, cohorts, n, 2, scenario, control_n=n), reps, 20261299)

    assert rerun["true_shift"] == stored["true_shift"]
    for name in ("absolute", "both", "low_information"):
        p = stored[name]
        spread = math.sqrt(max(p * (1 - p), 1e-4) * (1 / reps + 1 / stored["reps"]))
        assert abs(rerun[name] - p) <= 4.5 * spread + 0.01, (name, rerun[name], p)
    assert rerun["ratio_p50"] == pytest.approx(stored["ratio_p50"], abs=0.08)


# --- What the committed heavy-tailed study shows --------------------------------------------------


def _percent(value: float, places: int = 2) -> str:
    return f"{100 * value:.{places}f}%"


def _span(values, places: int = 1) -> str:
    values = list(values)
    return f"{_percent(min(values), places)} to {_percent(max(values), places)}"


def _points(values, places: int = 1) -> str:
    values = list(values)
    return f"{100 * min(values):.{places}f} to {100 * max(values):.{places}f}"


def _split(cell: dict) -> int:
    return max(cell["n"], cell["control_n"]) // min(cell["n"], cell["control_n"])


def _printed_cell(outcome: str, cohorts: int, n: int, scenario: str = "printed_shift") -> dict:
    return next(
        c
        for c in HEAVY["printed"]
        if (c["outcome"], c["cohorts"], c["n"], c["scenario"]) == (outcome, cohorts, n, scenario)
    )


def _population_skewness(outcome: str) -> float:
    """The skewness of the population of a tailed outcome, from the moments of its lognormal."""
    spend_sd = SPEND_SD[outcome]
    spends = stats.lognorm(s=spend_sd, scale=BASE[outcome] / PAYING * math.exp(-(spend_sd**2) / 2))
    raw = [PAYING * spends.moment(k) for k in (1, 2, 3)]
    variance = raw[1] - raw[0] ** 2
    return (raw[2] - 3 * raw[0] * raw[1] + 2 * raw[0] ** 3) / variance**1.5


def _heavy_figures() -> dict:
    """The figures of the heavy-tailed study that its claims rest on, worked out from the file."""
    cells = HEAVY["cells"]
    printed = [c for c in HEAVY["printed"] if c["scenario"] == "printed_shift"]
    located = [c for c in HEAVY["printed"] if c["scenario"] == "printed_location"]
    null = ("zero", "relative", "relative_drift", "absolute_drift")
    equal = [c for c in cells if c["outcome"] in TAILED and _is_equal(c) and c["scenario"] in null]
    stable = [c for c in equal if c["scenario"] in ("zero", "relative")]
    unequal = [c for c in cells if not _is_equal(c)]
    over = [c for c in unequal if c["both"] > 0.05]
    standard_error = math.sqrt(0.05 * 0.95 / HEAVY["reps"])
    fade = {(c["outcome"], c["cohorts"], c["n"]): c for c in cells if c["scenario"] == "fade"}
    shifts = [c for c in cells if c["scenario"] == "null_se_shift"]
    shifted = [c for c in cells if c["scenario"] == "null_se_location"]
    sections = {
        "normal": ("normal",),
        "poisson": ("poisson",),
        "lognormal": ("lognormal",),
        "binary": ("binary",),
        "revenue-like": TAILED,
        "middle": ("revenue",),
    }

    def group(rows, outcomes):
        return [c for c in rows if c["outcome"] in outcomes]

    def of_outcome(rows, key, agg):
        return [agg(c[key] for c in rows if c["outcome"] == o) for o in TAILED]

    def pairs():
        found = []
        for c in unequal:
            floor = raised_floor(_split(c))
            if min(c["n"], c["control_n"]) != floor:
                continue
            side = (c["outcome"], c["cohorts"], c["scenario"], _split(c), c["n"] > c["control_n"])
            (d,) = [
                d
                for d in unequal
                if (d["outcome"], d["cohorts"], d["scenario"], _split(d), d["n"] > d["control_n"])
                == side
                and min(d["n"], d["control_n"]) == 3 * floor
            ]
            found.append((c, d))
        assert len(found) == 144
        return found

    matched = pairs()
    mild_nine = [(a, b) for a, b in matched if a["outcome"] == "revenue_mild" and _split(a) == 9]
    fall_elsewhere = [
        (a, b)
        for a, b in matched
        if b["both"] < a["both"] and not (a["outcome"] == "revenue_mild" and _split(a) == 9)
    ]
    relative = lambda outcome, n: _span(  # noqa: E731
        (c["relative"] for c in stable if c["outcome"] == outcome and c["n"] == n), 1
    )
    drifting = lambda outcome, n: _percent(  # noqa: E731
        max(
            c["absolute"]
            for c in equal
            if c["scenario"] == "relative_drift" and c["outcome"] == outcome and c["n"] == n
        ),
        1,
    )
    fade_two_arms = [c for c in FADE["cells"] if c["arms"] == 2]
    fade_cost = lambda outcome, rows: [  # noqa: E731
        100 * (c["absolute"] - c["both"]) for c in rows if c["outcome"] == outcome
    ]
    fade_example = [c for c in fade_two_arms if (c["cohorts"], c["n"]) == (8, 100)]
    nine_twelve = lambda mult: [  # noqa: E731
        c["both"]
        for c in unequal
        if _split(c) == 9
        and c["cohorts"] == 12
        and min(c["n"], c["control_n"]) == mult * raised_floor(9)
    ]
    shapes = {(r["outcome"], r["n"]): r for r in HEAVY["shapes"]}
    ran = lambda c: round(c["not_low_information_runs"])  # noqa: E731
    enough = [c for c in printed if c["outcome"] in TAILED and ran(c) >= 200]
    (again,) = HEAVY["replication"]
    cell_8 = next(
        c
        for c in cells
        if _key(c)
        == (again["outcome"], again["cohorts"], again["n"], again["control_n"], "relative")
    )
    shortfall = lambda rows, key: [  # noqa: E731
        100 * (0.8 - c[key]) for c in rows
    ]
    return {
        "equal": (len(equal), sum(c["both"] > 0.05 for c in equal)),
        "stable cells": len(stable) // len(TAILED),
        "printed error": f"{100 * math.sqrt(0.25 / HEAVY['printed_reps']):.1f}",
        "all middle 1000": [
            _percent(_printed_cell("revenue", k, 1000)["absolute"], 1) for k in SHIFT_COHORTS
        ],
        "equal max": [_percent(m) for m in of_outcome(equal, "both", max)],
        "stable mean": [
            _percent(sum(c["both"] for c in stable if c["outcome"] == o) / (len(stable) // 3))
            for o in TAILED
        ],
        "relative alone": [_percent(m, 1) for m in of_outcome(equal, "relative", max)],
        "relative alone heavy 12": [
            _percent(
                next(
                    c
                    for c in equal
                    if (c["outcome"], c["cohorts"], c["n"], c["scenario"])
                    == ("revenue_heavy", 12, n, "zero")
                )["relative"],
                1,
            )
            for n in (30, 1000)
        ],
        "absolute alone stable": [_percent(m, 1) for m in of_outcome(stable, "absolute", max)],
        "absolute alone drift": _percent(
            max(c["absolute"] for c in equal if c["scenario"] == "relative_drift"), 1
        ),
        "unequal": (
            len(unequal),
            len(over),
            _percent(min(c["both"] for c in over)),
            _percent(max(c["both"] for c in over)),
            sum(c["both"] > 0.05 + 2 * standard_error for c in unequal),
            _percent(0.05 + 2 * standard_error, 1),
            f"{100 * standard_error:.2f}",
        ),
        "over": {
            "nine to one": sum(_split(c) == 9 for c in over),
            "cohorts": sorted({c["cohorts"] for c in over}),
            "outcomes": [sum(c["outcome"] == o for c in over) for o in TAILED],
            "heavy max": _percent(max(c["both"] for c in over if c["outcome"] == "revenue_heavy")),
        },
        "nine to one means": [_percent(sum(r) / len(r)) for r in (nine_twelve(1), nine_twelve(3))],
        "pairs": (
            sum(b["both"] > a["both"] for a, b in matched),
            len(matched),
            f"{100 * sum(b['both'] - a['both'] for a, b in matched) / len(matched):+.2f}",
            f"{100 * sum(b['both'] - a['both'] for a, b in mild_nine) / len(mild_nine):+.2f}",
            sum(b["both"] < a["both"] for a, b in mild_nine),
            len(mild_nine),
            sum(b["both"] == a["both"] for a, b in matched),
            sum(b["both"] < a["both"] for a, b in matched),
            len(fall_elsewhere),
            f"{100 * max(a['both'] - b['both'] for a, b in fall_elsewhere):.2f}",
        ),
        "relative stable": {
            "mild small": relative("revenue_mild", EQUAL_PLAYERS[0]),
            "mild 300": relative("revenue_mild", EQUAL_PLAYERS[2]),
            "mild 1000": relative("revenue_mild", EQUAL_PLAYERS[-1]),
            "middle 1000": relative("revenue", EQUAL_PLAYERS[-1]),
            "heavy 1000": relative("revenue_heavy", EQUAL_PLAYERS[-1]),
        },
        "absolute drifting": {
            o: (drifting(o, EQUAL_PLAYERS[0]), drifting(o, EQUAL_PLAYERS[-1])) for o in TAILED
        },
        "fade cost": {
            o: f"{max(fade_cost(o, fade_two_arms)):.1f}"
            for o in OUTCOMES  # normal, Poisson, lognormal, binary
        },
        "fade cost example": {o: f"{fade_cost(o, fade_example)[0]:.1f}" for o in OUTCOMES},
        "by split": {
            o: [
                _percent(max(c["both"] for c in unequal if c["outcome"] == o and _split(c) == s))
                for s in SPLITS
            ]
            for o in TAILED
        },
        "most with 8 cohorts": _percent(max(c["both"] for c in unequal if c["cohorts"] == 8)),
        "replication": (
            _percent(cell_8["both"]),
            _percent(again["both"]),
            f"{100 * math.sqrt(again['both'] * (1 - again['both']) / again['reps']):.2f}",
            again["reps"],
            again["seed"],
        ),
        "fade 1000": [_percent(fade[(o, 8, 1000)]["both"], 1) for o in TAILED],
        "fade 100": [_percent(fade[(o, 8, 100)]["both"], 1) for o in TAILED],
        "null se": {
            name: (
                _span(c["absolute"] for c in group(shifts, outcomes)),
                _span(c["both"] for c in group(shifts, outcomes)),
            )
            for name, outcomes in sections.items()
        },
        "null se location": {
            name: _span(c["absolute"] for c in group(shifted, outcomes))
            for name, outcomes in sections.items()
            if name in ("lognormal", "revenue-like", "middle")
        },
        "printed": {
            name: (
                _span(c["absolute"] for c in group(printed, outcomes)),
                _span(c["both"] for c in group(printed, outcomes)),
            )
            for name, outcomes in sections.items()
        },
        "printed location": {
            name: (
                _span(c["absolute"] for c in group(located, outcomes)),
                _span(c["both"] for c in group(located, outcomes)),
            )
            for name, outcomes in sections.items()
            if name in ("lognormal", "revenue-like", "middle")
        },
        "ratio": {
            name: (
                f"{min(c['ratio_p5'] for c in group(printed, outcomes)):.2f}",
                f"{max(c['ratio_p95'] for c in group(printed, outcomes)):.2f}",
                f"{min(c['ratio_p50'] for c in group(printed, outcomes)):.2f}",
                f"{max(c['ratio_p50'] for c in group(printed, outcomes)):.2f}",
            )
            for name, outcomes in sections.items()
        },
        "label small": _span(
            (c["low_information"] for c in group(printed, TAILED) if c["n"] in (100, 300)), 0
        ),
        "label 1000": {
            o: [_percent(_printed_cell(o, k, 1000)["low_information"], 0) for k in (4, 8)]
            for o in TAILED
        },
        "unlabelled": (
            _span(c["absolute_not_low_information"] for c in enough),
            len(enough),
            len([c for c in printed if c["outcome"] in TAILED]),
        ),
        "unlabelled middle 1000": [
            (
                _percent(_printed_cell("revenue", k, 1000)["absolute_not_low_information"], 1),
                ran(_printed_cell("revenue", k, 1000)),
            )
            for k in (4, 8)
        ],
        "smallest shift": min(
            c["ratio_p5"] * next(x for x in shifts if _same(x, c))["shift"] / BASE[c["outcome"]]
            for c in printed
            if c["outcome"] in TAILED
        ),
        "second scale": {
            name: _points((c["absolute"] - c["both"]) for c in group(shifts, outcomes))
            for name, outcomes in sections.items()
        },
        "second scale location": _points(
            (c["absolute"] - c["both"]) for c in group(shifted, TAILED)
        ),
        "located": {
            "ratio": (
                f"{min(c['ratio_p50'] for c in group(located, TAILED)):.2f}",
                f"{max(c['ratio_p50'] for c in group(located, TAILED)):.2f}",
            ),
            "short": (
                f"{100 * POWER - 100 * max(c['both'] for c in group(located, TAILED)):.0f}",
                f"{100 * POWER - 100 * min(c['both'] for c in group(located, TAILED)):.0f}",
            ),
            "cost": _points(((c["absolute"] - c["both"]) for c in group(located, TAILED)), 0).split(
                " to "
            ),
        },
        "shortfall": {
            name: (
                f"{min(shortfall(group(printed, outcomes), 'absolute')):.0f}",
                f"{max(shortfall(group(printed, outcomes), 'absolute')):.0f}",
                f"{max(shortfall(group(printed, outcomes), 'both')):.0f}",
            )
            for name, outcomes in sections.items()
        },
        "sd ratio": {
            o: f"{shapes[(o, 900)]['sd_ratio_p50']:.2f}" for o in ("revenue", "revenue_heavy")
        },
        "sd ratio range": (
            f"{shapes[('revenue', 900)]['sd_ratio_p5']:.2f}",
            f"{shapes[('revenue', 900)]['sd_ratio_p95']:.2f}",
        ),
    }


def _same(shift_cell: dict, printed_cell: dict) -> bool:
    return (shift_cell["outcome"], shift_cell["cohorts"], shift_cell["n"]) == (
        printed_cell["outcome"],
        printed_cell["cohorts"],
        printed_cell["n"],
    ) and shift_cell["scenario"] == "null_se_shift"


EXPORT_PHRASE = (
    "731 to 969 an arm, 12% to 15% of them paying; skewness 11.5 to 19.4, excess kurtosis 151 to "
    "463, 51% to 62% in the top 1%"
)
EXPORT_MARGIN = "51.2% against the band's lower edge of 50.4%"  # the thinnest margin of the six


# the sentences that are in 21.7 or 21.9 and not in the new bullets


def test_the_exports_revenue_phrase_in_the_text_is_the_one_the_export_gives(raw_spec: dict) -> None:
    from results_helpers import results_spec

    from referee.data import load_export
    from referee.results import ExportMetric, ResultsContext

    context = ResultsContext.of(results_spec(raw_spec), load_export(FIXTURE, "hybrid_offer_page"))
    revenue: dict[str, list[float]] = {}
    for player in context.analysed:
        revenue.setdefault(player.arm, []).append(player.revenue_usd_7d)
    found = {
        arm: {
            "n": len(v),
            "paying": sum(x > 0 for x in v) / len(v),
            "skewness": float(stats.skew(v)),
            "excess_kurtosis": heavy_tail_measures(v).excess_kurtosis,
            "top_1_percent_share": heavy_tail_measures(v).top_share,
        }
        for arm, v in revenue.items()
    }
    values = lambda key: [a[key] for a in found.values()]  # noqa: E731

    assert EXPORT_PHRASE == (
        f"{min(values('n'))} to {max(values('n'))} an arm, "
        f"{100 * min(values('paying')):.0f}% to {100 * max(values('paying')):.0f}% of them paying; "
        f"skewness {min(values('skewness')):.1f} to {max(values('skewness')):.1f}, "
        f"excess kurtosis {min(values('excess_kurtosis')):.0f} to "
        f"{max(values('excess_kurtosis')):.0f}, "
        f"{100 * min(values('top_1_percent_share')):.0f}% to "
        f"{100 * max(values('top_1_percent_share')):.0f}% in the top 1%"
    )
    band = {s["outcome"]: s for s in HEAVY["shapes"] if s["n"] == 900}

    def inside(outcome: str, arm: str) -> bool:
        return all(
            band[outcome][f"{key}_p5"] <= found[arm][key] <= band[outcome][f"{key}_p95"]
            for key in ("skewness", "excess_kurtosis", "top_1_percent_share")
        )

    assert all(inside("revenue", arm) and inside("revenue_heavy", arm) for arm in found)
    margin = {  # how far inside the band, as a share of its width
        (arm, outcome, key): min(
            found[arm][key] - band[outcome][f"{key}_p5"],
            band[outcome][f"{key}_p95"] - found[arm][key],
        )
        / (band[outcome][f"{key}_p95"] - band[outcome][f"{key}_p5"])
        for arm in found
        for outcome in ("revenue", "revenue_heavy")
        for key in ("skewness", "excess_kurtosis", "top_1_percent_share")
    }
    (arm, outcome, key), thinnest = min(margin.items(), key=lambda item: item[1])
    lower = band[outcome][f"{key}_p5"]
    assert (outcome, key) == ("revenue_heavy", "top_1_percent_share") and thinnest < 0.05
    assert EXPORT_MARGIN == (
        f"{100 * found[arm][key]:.1f}% against the band's lower edge of {100 * lower:.1f}%"
    )
    assert sorted(m for m in margin.values())[1] > 2 * thinnest  # and no other is as thin
    mild = band["revenue_mild"]
    assert all(a["top_1_percent_share"] > mild["top_1_percent_share_p95"] for a in found.values())
    above = [arm for arm in found if found[arm]["skewness"] > mild["skewness_p95"]]
    assert sorted(f"{found[arm]['skewness']:.1f}" for arm in above) == ["19.3", "19.4"]
    assert [round(_population_skewness(o), 1) for o in TAILED] == [12.7, 82.4, 1122.8]
    # what the decision bullet says about the registered effect, for the primary metric only
    revenue_metric = ExportMetric("revenue_usd_7d", "continuous", lambda p: p.revenue_usd_7d)
    primary = context.metrics[context.spec.primary_metric.name]
    assert registered_mde(context, primary) is not None
    assert registered_mde(context, revenue_metric) is None  # not the primary metric
    examples = Path(__file__).parent.parent / "examples"
    for name in ("offer-page-powered.yaml", "offer-page-underpowered.yaml"):  # the design examples
        assert "mde_relative: 0.05" in (examples / name).read_text(encoding="utf-8"), name


def test_what_the_text_says_about_the_bootstrap_is_what_the_code_does() -> None:
    from referee.methods import BootstrapInterval, _bootstrap_means, bootstrap_difference

    ratios = []
    for n in (10, 40):
        values = np.random.default_rng(4).lognormal(sigma=1.5, size=n)

        resampled = _bootstrap_means(values, 200_000, np.random.PCG64(np.random.SeedSequence(1)))

        # the variance of the resampled means is the sample variance times (n - 1) over n squared
        assert resampled.var() == pytest.approx(values.var(ddof=1) * (n - 1) / n**2, rel=0.02)
        welch = values.std(ddof=1) / math.sqrt(n)  # and its square root the Welch standard error
        assert resampled.std() / welch == pytest.approx(math.sqrt((n - 1) / n), rel=0.01)
        ratios.append(resampled.std() / welch)
    assert 1 - ratios[0] > 0.04 > 1 - ratios[1] > 0.01  # the factor is not nothing at 10 players
    interval = bootstrap_difference([1.0, 2.0, 4.0, 8.0], [1.0, 1.5, 2.0, 3.0], seed=1)
    assert isinstance(interval, BootstrapInterval) and interval.ci_low < interval.ci_high
    fields = BootstrapInterval.__dataclass_fields__
    assert {"ci_low", "ci_high"} <= fields.keys() and not any("error" in k for k in fields)


def test_the_claims_that_join_the_sentences_follow_from_the_study() -> None:
    f = _heavy_figures()
    cells = HEAVY["cells"]
    drift = [
        c
        for c in cells
        if c["scenario"] == "relative_drift" and _is_equal(c) and c["outcome"] in TAILED
    ]
    stable = [c for c in cells if c["scenario"] in ("zero", "relative") and _is_equal(c)]

    # the relative scale alone is worst with the smallest cohorts; for the middle and heavy
    # outcome it is above 5% at every size tried, for the mild one at every size below the last
    for outcome in TAILED:
        alone = {
            n: [c["relative"] for c in stable if c["outcome"] == outcome and c["n"] == n]
            for n in EQUAL_PLAYERS
        }
        highest = [max(v) for v in alone.values()]
        assert highest == sorted(highest, reverse=True), outcome
        lowest = {n: min(v) for n, v in alone.items()}
        sizes = EQUAL_PLAYERS[:-1] if outcome == "revenue_mild" else EQUAL_PLAYERS
        assert all(lowest[n] > 0.05 for n in sizes), outcome
    assert (
        max(c["relative"] for c in stable if c["outcome"] == "revenue_mild" and c["n"] == 1000)
        < 0.07
    )
    # under a drifting baseline the absolute scale alone flags more as the cohorts grow
    for outcome in TAILED:
        by_size = [
            max(c["absolute"] for c in drift if c["outcome"] == outcome and c["n"] == n)
            for n in EQUAL_PLAYERS
        ]
        assert all(a < b for a, b in zip(by_size, by_size[1:], strict=False)), outcome
    # the absolute scale alone holds 5% for a stable baseline; it does not for the mild outcome
    # under a baseline that drifts, and for the others it does there as well
    assert max(c["absolute"] for c in stable if c["outcome"] in TAILED) < 0.05
    assert max(c["absolute"] for c in drift if c["outcome"] == "revenue_mild") > 0.05
    assert max(c["absolute"] for c in drift if c["outcome"] != "revenue_mild") < 0.05
    # the rate does not fall with larger arms on the whole, and rises with the cohorts
    assert f["pairs"][0] > 100 and float(f["pairs"][2]) > 0 and float(f["pairs"][3]) < 0
    assert f["nine to one means"][0] > _percent(0.05) and f["over"]["cohorts"] == [8, 12]
    # only the normal outcome is calibrated at the shift from the standard error under no effect
    cut = {name: _span_low(f["null se"][name][0]) for name in f["null se"]}
    assert 0.785 < cut["normal"] and all(cut[n] < 0.77 for n in cut if n != "normal")
    # the printed shift is the true one for the normal and the Poisson outcome and smaller on tails
    printed = [c for c in HEAVY["printed"] if c["scenario"] == "printed_shift"]
    assert all(
        abs(c["ratio_p50"] - 1) < 0.01 for c in printed if c["outcome"] in ("normal", "poisson")
    )
    assert all(c["ratio_p50"] < 1 for c in printed if c["outcome"] in TAILED)
    # a fade added to every player is flagged more than one that scales the arm, for every
    # heavy-tailed cell and for the middle outcome up to near the claimed power
    located = {_key(c)[:3]: c for c in HEAVY["printed"] if c["scenario"] == "printed_location"}
    for c in printed:
        if c["outcome"] in TAILED:
            assert located[_key(c)[:3]]["absolute"] > c["absolute"], _key(c)
    assert max(c["absolute"] for c in located.values() if c["outcome"] == "revenue") > 0.7


def _span_low(span: str) -> float:
    return float(span.split("%")[0]) / 100
